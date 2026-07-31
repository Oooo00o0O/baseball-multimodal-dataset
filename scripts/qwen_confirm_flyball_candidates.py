from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from audit_flyball_main import (
    frame_features,
    read_wav_mono,
    transient_candidates,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FIELDS = [
    "repair_batch",
    "repair_batch_index",
    "collector",
    "sample_id",
    "main_relative_path",
    "media_variant",
    "media_video_path",
    "media_audio_path",
    "recut_status",
    "before_event_start",
    "before_event_end",
    "review_event_start",
    "review_event_end",
    "selected_candidate_index",
    "selected_candidate_time",
    "visual_contact_time",
    "audio_visual_offset",
    "final_event_start",
    "final_event_end",
    "decision",
    "binding_status",
    "contact_audible",
    "contact_sound_normal_speed",
    "contact_visible",
    "live_play",
    "replay_or_slow_motion",
    "replay_or_slow_motion_at_contact",
    "trailing_replay_present",
    "fly_ball_semantics",
    "full_play_visible",
    "clip_context_sufficient",
    "trajectory_type",
    "confidence",
    "model",
    "total_tokens",
    "audio_evidence",
    "visual_evidence",
    "failure_reason",
    "error",
]


class QuotaError(RuntimeError):
    pass


class AuthenticationError(RuntimeError):
    pass


class ModelUnavailableError(RuntimeError):
    pass


def load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        # An explicitly supplied env file must override stale desktop-session
        # variables so usage accounting and model rotation target that account.
        os.environ[name.strip()] = value.strip().strip('"').strip("'")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_global_usage_records(path: Path) -> list[dict[str, Any]]:
    """Load and deduplicate model usage across every audit shard."""
    candidates = {path.resolve()}
    if path.parent.is_dir():
        candidates.update(
            item.resolve()
            for item in path.parent.rglob("qwen_usage*.jsonl")
            if item.is_file()
        )
    records: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for candidate in sorted(candidates):
        for record in load_jsonl(candidate):
            usage = record.get("usage") or {}
            key = (
                record.get("account_fingerprint"),
                record.get("model"),
                record.get("sample_id"),
                record.get("recorded_at_unix"),
                total_tokens(usage),
            )
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return records


def write_summary(path: Path, records: list[dict[str, Any]]) -> None:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("sample_id"):
            latest[record["main_relative_path"]] = record
    rows = [latest[key] for key in sorted(latest, key=lambda item: int(latest[item]["repair_batch_index"]))]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in SUMMARY_FIELDS})


def total_tokens(usage: dict[str, Any] | None) -> int:
    if not usage:
        return 0
    direct = usage.get("total_tokens")
    if direct is not None:
        try:
            return int(direct)
        except (TypeError, ValueError):
            return 0
    return int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)


def model_usage(records: list[dict[str, Any]], fingerprint: str) -> dict[str, int]:
    usage: dict[str, int] = {}
    for record in records:
        if record.get("account_fingerprint") != fingerprint:
            continue
        model = record.get("model")
        if model:
            usage[model] = usage.get(model, 0) + total_tokens(record.get("usage"))
    return usage


def data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def upload_video_path(
    video_path: Path,
    *,
    cache_root: Path,
    ffmpeg: str,
    max_source_bytes: int,
) -> Path:
    if video_path.stat().st_size <= max_source_bytes:
        return video_path
    fingerprint = hashlib.sha256(
        f"{video_path.resolve()}:{video_path.stat().st_size}:{video_path.stat().st_mtime_ns}".encode(
            "utf-8"
        )
    ).hexdigest()[:20]
    cache_root.mkdir(parents=True, exist_ok=True)
    preview = cache_root / f"{video_path.parent.name}_{fingerprint}.mp4"
    if preview.is_file() and preview.stat().st_size <= max_source_bytes:
        return preview
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            "scale=-2:min(480\\,ih)",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            "-y",
            str(preview),
        ],
        check=True,
        timeout=300,
    )
    if not preview.is_file() or preview.stat().st_size > max_source_bytes:
        raise RuntimeError("Qwen preview transcode did not meet the upload size limit.")
    return preview


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def chunk_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    return ""


def call_qwen(
    *,
    model: str,
    video_path: Path,
    prompt: str,
    base_url: str,
    api_key: str,
    media_type: str = "video_url",
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if media_type not in {"video_url", "image_url"}:
        raise ValueError(f"unsupported Qwen media type: {media_type}")
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": media_type, media_type: {"url": data_url(video_path)}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "modalities": ["text"],
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0,
    }
    if model.startswith("qwen3-omni-flash"):
        body["enable_thinking"] = False
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=240)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if "AllocationQuota.FreeTierOnly" in detail or "free quota has been exhausted" in detail:
            raise QuotaError(f"{model}: free quota exhausted") from exc
        if exc.code in {401, 403}:
            raise AuthenticationError(f"HTTP {exc.code}: API authentication failed") from exc
        if exc.code in {400, 404} and any(
            marker in detail.lower()
            for marker in ("model", "not exist", "not support", "unsupported")
        ):
            raise ModelUnavailableError(
                f"{model}: endpoint does not support this model"
            ) from exc
        raise RuntimeError(f"HTTP {exc.code}: {detail[:800]}") from exc
    text_parts: list[str] = []
    usage = None
    with response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            content = line.removeprefix("data:").strip()
            if content == "[DONE]":
                break
            chunk = json.loads(content)
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices", []):
                text_parts.append(chunk_text((choice.get("delta") or {}).get("content")))
    return extract_json("".join(text_parts)), usage


def candidates_for_audio(
    audio_path: Path,
    anchor_time: float,
    limit: int = 24,
) -> list[dict[str, float]]:
    audio, sample_rate, _duration = read_wav_mono(audio_path)
    # A 10 ms-only detector missed two human-confirmed contacts during
    # calibration. Short cracks can peak only at 5 ms, while noisy contacts are
    # more stable at 20 ms, so merge all three resolutions before Qwen sees a
    # finite candidate list.
    global_candidates: list[tuple[float, float, float, float]] = []
    local_candidates: list[tuple[float, float, float, float]] = []
    for frame_ms in (5.0, 10.0, 20.0):
        times, rms_ratio, diff_ratio, score = frame_features(audio, sample_rate, frame_ms)
        for time_value, score_value, index in transient_candidates(
            times,
            score,
            minimum_score=1.50,
            minimum_separation=0.08,
            limit=limit,
        ):
            global_candidates.append(
                (time_value, score_value, float(rms_ratio[index]), float(diff_ratio[index]))
            )
        local_mask = (times >= max(0.0, anchor_time - 0.60)) & (times <= anchor_time + 0.60)
        if local_mask.any():
            first = int(local_mask.nonzero()[0][0])
            for time_value, score_value, index in transient_candidates(
                times[local_mask],
                score[local_mask],
                minimum_score=1.15,
                minimum_separation=0.05,
                limit=12,
            ):
                source_index = first + index
                local_candidates.append(
                    (
                        time_value,
                        score_value,
                        float(rms_ratio[source_index]),
                        float(diff_ratio[source_index]),
                    )
                )

    def deduplicate(
        candidates: list[tuple[float, float, float, float]],
    ) -> list[tuple[float, float, float, float]]:
        selected: list[tuple[float, float, float, float]] = []
        for candidate in sorted(candidates, key=lambda item: item[1], reverse=True):
            if all(abs(candidate[0] - existing[0]) > 0.035 for existing in selected):
                selected.append(candidate)
        return selected

    prioritized = sorted(
        deduplicate(local_candidates),
        key=lambda item: (abs(item[0] - anchor_time), -item[1]),
    )
    for candidate in deduplicate(global_candidates):
        if all(abs(candidate[0] - existing[0]) > 0.035 for existing in prioritized):
            prioritized.append(candidate)
        if len(prioritized) >= limit:
            break
    ranked = prioritized[:limit]
    return [
        {
            "index": index,
            "time": round(time_value, 3),
            "score": round(score_value, 3),
            "rms_ratio": round(rms_value, 3),
            "diff_ratio": round(diff_value, 3),
        }
        for index, (time_value, score_value, rms_value, diff_value) in enumerate(ranked, start=1)
    ]


def bool_value(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def validate_result(
    result: dict[str, Any],
    candidates: list[dict[str, float]],
) -> tuple[str, int | None, float | None, str]:
    if result.get("decision") not in {"accept", "review", "reject"}:
        return "invalid_model_schema", None, None, "invalid decision"
    raw_index = result.get("selected_audio_candidate_index")
    raw_time = result.get("selected_audio_candidate_seconds")
    if raw_index is None or raw_time is None:
        return "no_candidate_selected", None, None, "model did not verify a supplied candidate"
    try:
        selected_index = int(raw_index)
        selected_time = float(raw_time)
    except (TypeError, ValueError):
        return "invalid_candidate_binding", None, None, "candidate index/time is not numeric"
    if not 1 <= selected_index <= len(candidates):
        return "invalid_candidate_binding", None, None, "candidate index is outside supplied list"
    expected_time = candidates[selected_index - 1]["time"]
    if abs(selected_time - expected_time) > 0.030:
        return (
            "invalid_candidate_binding",
            None,
            None,
            f"returned {selected_time:.3f}, expected candidate {expected_time:.3f}",
        )
    try:
        visual_time = float(result.get("visual_contact_seconds"))
    except (TypeError, ValueError):
        return "invalid_visual_contact_time", selected_index, expected_time, "missing numeric visual contact time"
    # Manual calibration includes verified broadcast clips with a stable
    # audio-video offset close to 0.45 seconds. Audio remains the label clock;
    # the model must still explicitly bind the candidate to the same live swing.
    if abs(visual_time - expected_time) > 0.50:
        return (
            "audio_visual_time_mismatch",
            selected_index,
            expected_time,
            f"visual={visual_time:.3f}, audio={expected_time:.3f}",
        )
    if not bool_value(result.get("selected_candidate_matches_visual_contact")):
        return (
            "audio_visual_time_mismatch",
            selected_index,
            expected_time,
            "model says selected candidate does not match visual contact",
        )
    required_true = ["contact_audible", "contact_visible"]
    if not all(bool_value(result.get(field)) for field in required_true):
        return (
            "candidate_not_verified",
            selected_index,
            expected_time,
            "audio/video contact pair failed",
        )
    normal_speed = result.get("contact_sound_normal_speed")
    if normal_speed is not None and not bool_value(normal_speed):
        return (
            "altered_contact_audio",
            selected_index,
            expected_time,
            "selected contact sound is slowed or otherwise altered",
        )
    if bool_value(result.get("replay_or_slow_motion_at_contact")) and not bool_value(
        result.get("contact_sound_normal_speed")
    ):
        return (
            "altered_contact_audio",
            selected_index,
            expected_time,
            "selected replay/slow-motion contact lacks a normal-speed hit sound",
        )
    if result.get("decision") != "accept":
        return "model_requires_review", selected_index, expected_time, "model did not accept the sample"
    return "audio_candidate_bound", selected_index, expected_time, ""


def prepare_media_rows(
    queue: list[dict[str, str]],
    recuts: list[dict[str, str]],
) -> list[dict[str, str]]:
    recut_by_path = {row["main_relative_path"]: row for row in recuts}
    prepared: list[dict[str, str]] = []
    for row in queue:
        recut = recut_by_path.get(row["main_relative_path"])
        if recut:
            prepared.append(
                {
                    **row,
                    "media_variant": "recut",
                    "media_video_path": recut["video_path"],
                    "media_audio_path": recut["audio_path"],
                    "recut_status": recut["status"],
                    "review_event_start": recut["new_event_start"],
                    "review_event_end": recut["new_event_end"],
                }
            )
        else:
            sample_dir = REPO_ROOT / row["main_relative_path"]
            suggested = row.get("suggested_contact_time", "")
            if (
                row.get("event_audio_assessment") == "likely_contact_timestamp_wrong"
                and suggested
            ):
                review_start = f"{max(0.0, float(suggested) - 0.05):.3f}"
                review_end = f"{float(suggested) + 0.05:.3f}"
            else:
                review_start = row["current_event_start"]
                review_end = row["current_event_end"]
            prepared.append(
                {
                    **row,
                    "media_variant": "original",
                    "media_video_path": str((sample_dir / "video.mp4").resolve()),
                    "media_audio_path": str((sample_dir / "audio.wav").resolve()),
                    "recut_status": "not_required",
                    "review_event_start": review_start,
                    "review_event_end": review_end,
                }
            )
    return prepared


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind Qwen visual review to local audio candidates.")
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--recut-manifest", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary-csv", type=Path, required=True)
    parser.add_argument(
        "--usage-jsonl",
        type=Path,
        default=REPO_ROOT
        / "reports"
        / "flyball_main_reclean_20260728"
        / "qwen_account_usage.jsonl",
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=REPO_ROOT / "prompts" / "flyball_candidate_confirmation.md",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "qwen_reclean_models.json",
    )
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument(
        "--preview-cache",
        type=Path,
        default=Path(os.getenv("QWEN_PREVIEW_CACHE", str(REPO_ROOT / ".qwen_preview_cache"))),
    )
    parser.add_argument(
        "--max-upload-video-bytes",
        type=int,
        default=14 * 1024 * 1024,
    )
    args = parser.parse_args()

    load_env(args.env_file)
    api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise SystemExit("QWEN_API_KEY or DASHSCOPE_API_KEY is not configured.")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    base_url = os.getenv("QWEN_BASE_URL") or config["base_url"]
    models = [str(model) for model in config["models"]]
    switch_at = int(config.get("switch_at_used_tokens", 900000))
    per_request_reserve = int(config.get("per_request_reserve_tokens", 20000))
    prompt_template = args.prompt.read_text(encoding="utf-8")
    queue = read_csv(args.queue)
    recuts = read_csv(args.recut_manifest)
    rows = prepare_media_rows(queue, recuts)
    if args.sample_id:
        requested = set(args.sample_id)
        rows = [row for row in rows if row["sample_id"] in requested]
    if args.limit:
        rows = rows[: args.limit]

    existing = load_jsonl(args.output_jsonl)
    completed_paths = {
        record["main_relative_path"]
        for record in existing
        if record.get("main_relative_path") and not record.get("error")
    }
    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    usage_records = load_global_usage_records(args.usage_jsonl)
    usage = model_usage(usage_records, fingerprint)
    blocked: set[str] = set()

    for position, row in enumerate(rows, start=1):
        if row["main_relative_path"] in completed_paths:
            continue
        video_path = Path(row["media_video_path"])
        audio_path = Path(row["media_audio_path"])
        base_record: dict[str, Any] = {
            "repair_batch": row["repair_batch"],
            "repair_batch_index": row["repair_batch_index"],
            "collector": row["collector"],
            "sample_id": row["sample_id"],
            "main_relative_path": row["main_relative_path"],
            "media_variant": row["media_variant"],
            "media_video_path": str(video_path),
            "media_audio_path": str(audio_path),
            "recut_status": row["recut_status"],
            "before_event_start": row["current_event_start"],
            "before_event_end": row["current_event_end"],
            "review_event_start": row["review_event_start"],
            "review_event_end": row["review_event_end"],
            "selected_candidate_index": "",
            "selected_candidate_time": "",
            "visual_contact_time": "",
            "audio_visual_offset": "",
            "final_event_start": "",
            "final_event_end": "",
            "decision": "",
            "binding_status": "",
            "contact_audible": "",
            "contact_sound_normal_speed": "",
            "contact_visible": "",
            "live_play": "",
            "replay_or_slow_motion": "",
            "replay_or_slow_motion_at_contact": "",
            "trailing_replay_present": "",
            "fly_ball_semantics": "",
            "full_play_visible": "",
            "clip_context_sufficient": "",
            "trajectory_type": "",
            "confidence": "",
            "model": "",
            "total_tokens": "",
            "audio_evidence": "",
            "visual_evidence": "",
            "failure_reason": "",
            "error": "",
            "account_fingerprint": fingerprint,
            "usage": None,
        }
        if not video_path.is_file() or not audio_path.is_file():
            record = {
                **base_record,
                "binding_status": "media_missing",
                "error": "review media is missing",
            }
            append_jsonl(args.output_jsonl, record)
            continue
        anchor_time = (
            float(row["review_event_start"]) + float(row["review_event_end"])
        ) / 2.0
        candidates = candidates_for_audio(audio_path, anchor_time)
        try:
            api_video_path = upload_video_path(
                video_path,
                cache_root=args.preview_cache,
                ffmpeg=args.ffmpeg,
                max_source_bytes=args.max_upload_video_bytes,
            )
        except Exception as exc:
            record = {
                **base_record,
                "binding_status": "preview_transcode_error",
                "error": f"{type(exc).__name__}: {exc}",
                "audio_candidates": candidates,
            }
            append_jsonl(args.output_jsonl, record)
            continue
        context = {
            "sample_id": row["sample_id"],
            "current_untrusted_event_start": row["review_event_start"],
            "current_untrusted_event_end": row["review_event_end"],
            "local_audio_search_anchor_seconds": round(anchor_time, 3),
            "expected_dataset_label": "fly_ball",
            "expected_trajectory_type": row["trajectory_type"],
            "primary_error": row["primary_error"],
            "recut_status": row["recut_status"],
            "local_audio_transient_candidates": candidates,
        }
        prompt = prompt_template + "\n\nInput context:\n" + json.dumps(context, ensure_ascii=False)
        available = [
            model
            for model in models
            if model not in blocked
            and usage.get(model, 0) + per_request_reserve <= switch_at
        ]
        if not available:
            raise SystemExit("Every configured model reached the 90% switch threshold or was blocked.")
        result: dict[str, Any] | None = None
        used_model = ""
        used_usage = None
        error = ""
        started = time.time()
        for model in available:
            for attempt in range(3):
                try:
                    result, used_usage = call_qwen(
                        model=model,
                        video_path=api_video_path,
                        prompt=prompt,
                        base_url=base_url,
                        api_key=api_key,
                    )
                    used_model = model
                    break
                except (QuotaError, AuthenticationError, ModelUnavailableError) as exc:
                    blocked.add(model)
                    error = f"{type(exc).__name__}: {exc}"
                    break
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            if result is not None:
                break
        if result is None:
            record = {
                **base_record,
                "binding_status": "model_error",
                "error": error or "all available models failed",
                "elapsed_seconds": round(time.time() - started, 3),
                "audio_candidates": candidates,
            }
            append_jsonl(args.output_jsonl, record)
            print(json.dumps({"position": position, "sample_id": row["sample_id"], "status": "model_error"}), flush=True)
            continue

        binding_status, selected_index, selected_time, binding_reason = validate_result(
            result,
            candidates,
        )
        accepted = binding_status == "audio_candidate_bound" and selected_time is not None
        token_count = total_tokens(used_usage)
        usage[used_model] = usage.get(used_model, 0) + token_count
        append_jsonl(
            args.usage_jsonl,
            {
                "account_fingerprint": fingerprint,
                "model": used_model,
                "usage": used_usage,
                "sample_id": row["sample_id"],
                "main_relative_path": row["main_relative_path"],
                "repair_batch": row["repair_batch"],
                "recorded_at_unix": round(time.time(), 3),
            },
        )
        try:
            visual_contact_time = float(result.get("visual_contact_seconds"))
        except (TypeError, ValueError):
            visual_contact_time = None
        record = {
            **base_record,
            "selected_candidate_index": selected_index or "",
            "selected_candidate_time": f"{selected_time:.3f}" if selected_time is not None else "",
            "visual_contact_time": (
                f"{visual_contact_time:.3f}" if visual_contact_time is not None else ""
            ),
            "audio_visual_offset": (
                f"{abs(visual_contact_time - selected_time):.3f}"
                if selected_time is not None and visual_contact_time is not None
                else ""
            ),
            "final_event_start": f"{max(0.0, selected_time - 0.05):.3f}" if accepted else "",
            "final_event_end": f"{selected_time + 0.05:.3f}" if accepted else "",
            "decision": result.get("decision", ""),
            "binding_status": binding_status,
            "contact_audible": result.get("contact_audible", ""),
            "contact_sound_normal_speed": result.get(
                "contact_sound_normal_speed", ""
            ),
            "contact_visible": result.get("contact_visible", ""),
            "live_play": result.get("live_play", ""),
            "replay_or_slow_motion": result.get("replay_or_slow_motion", ""),
            "replay_or_slow_motion_at_contact": result.get(
                "replay_or_slow_motion_at_contact", ""
            ),
            "trailing_replay_present": result.get(
                "trailing_replay_present", ""
            ),
            "fly_ball_semantics": result.get("fly_ball_semantics", ""),
            "full_play_visible": result.get("full_play_visible", ""),
            "clip_context_sufficient": result.get("clip_context_sufficient", ""),
            "trajectory_type": result.get("trajectory_type", ""),
            "confidence": result.get("confidence", ""),
            "model": used_model,
            "total_tokens": token_count,
            "audio_evidence": result.get("audio_evidence", ""),
            "visual_evidence": result.get("visual_evidence", ""),
            "failure_reason": result.get("failure_reason", "") or binding_reason,
            "error": "",
            "account_fingerprint": fingerprint,
            "usage": used_usage,
            "elapsed_seconds": round(time.time() - started, 3),
            "audio_candidates": candidates,
            "api_video_path": str(api_video_path),
            "api_video_bytes": api_video_path.stat().st_size,
            "raw_result": result,
        }
        append_jsonl(args.output_jsonl, record)
        print(
            json.dumps(
                {
                    "position": position,
                    "total": len(rows),
                    "sample_id": row["sample_id"],
                    "binding_status": binding_status,
                    "model": used_model,
                    "model_used_tokens": usage[used_model],
                }
            ),
            flush=True,
        )

    all_records = load_jsonl(args.output_jsonl)
    write_summary(args.summary_csv, all_records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
