from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from qwen_confirm_flyball_candidates import (
    AuthenticationError,
    ModelUnavailableError,
    QuotaError,
    append_jsonl,
    bool_value,
    call_qwen,
    load_env,
    load_jsonl,
    model_usage,
    total_tokens,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FIELDS = [
    "repair_batch",
    "repair_batch_index",
    "collector",
    "sample_id",
    "main_relative_path",
    "first_pass_model",
    "selected_candidate_time",
    "contact_clip_path",
    "expected_relative_candidate_time",
    "decision",
    "contact_gate_status",
    "relative_visual_contact_time",
    "relative_audio_visual_offset",
    "contact_visible",
    "live_pitch_and_swing_visible",
    "candidate_sound_is_bat_contact",
    "replay_or_slow_motion",
    "confidence",
    "visual_evidence",
    "audio_evidence",
    "failure_reason",
    "model",
    "total_tokens",
    "error",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_summary(path: Path, records: list[dict[str, Any]]) -> None:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("main_relative_path"):
            latest[record["main_relative_path"]] = normalize_record(record)
    rows = sorted(
        latest.values(),
        key=lambda row: int(row["repair_batch_index"]),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in SUMMARY_FIELDS})


def build_contact_clip(
    video_path: Path,
    selected_time: float,
    *,
    cache_root: Path,
    ffmpeg: str,
    radius: float,
) -> tuple[Path, float]:
    start = max(0.0, selected_time - radius)
    expected_relative = selected_time - start
    duration = 2.0 * radius
    fingerprint = hashlib.sha256(
        f"{video_path.resolve()}:{video_path.stat().st_size}:{video_path.stat().st_mtime_ns}:{selected_time:.3f}".encode(
            "utf-8"
        )
    ).hexdigest()[:20]
    cache_root.mkdir(parents=True, exist_ok=True)
    output = cache_root / f"{video_path.parent.name}_{fingerprint}.mp4"
    if output.is_file() and output.stat().st_size > 0:
        return output, expected_relative
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(video_path),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            "scale=-2:min(480\\,ih)",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "25",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            "-y",
            str(output),
        ],
        check=True,
        timeout=180,
    )
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("contact clip extraction produced no media")
    return output, expected_relative


def evidence_is_specific(value: Any) -> bool:
    text = str(value or "").strip()
    lowered = text.lower()
    placeholders = {
        "brief evidence",
        "specific frame-level description",
        "specific sound description",
        "n/a",
        "none",
    }
    return len(text) >= 24 and lowered not in placeholders


def validate_result(
    result: dict[str, Any],
    expected_relative: float,
) -> tuple[str, float | None, str]:
    required_keys = {
        "decision",
        "confidence",
        "contact_visible",
        "live_pitch_and_swing_visible",
        "candidate_sound_is_bat_contact",
        "replay_or_slow_motion",
        "relative_visual_contact_seconds",
        "visual_evidence",
        "audio_evidence",
    }
    missing = sorted(required_keys - result.keys())
    if missing:
        return "invalid_model_schema", None, "missing keys: " + ",".join(missing)
    if result.get("decision") not in {"confirm", "reject", "review"}:
        return "invalid_model_schema", None, "invalid decision"
    if result.get("decision") != "confirm":
        return (
            "contact_gate_reject",
            None,
            str(result.get("failure_reason") or "model did not confirm"),
        )
    try:
        visual_time = float(result["relative_visual_contact_seconds"])
    except (TypeError, ValueError):
        return "invalid_visual_contact_time", None, "relative visual time is not numeric"
    if not bool_value(result.get("contact_visible")):
        return "contact_gate_reject", visual_time, "contact is not visible"
    if not bool_value(result.get("live_pitch_and_swing_visible")):
        return "contact_gate_reject", visual_time, "live pitch and swing are not visible"
    if not bool_value(result.get("candidate_sound_is_bat_contact")):
        return "contact_gate_reject", visual_time, "candidate sound is not bat contact"
    if bool_value(result.get("replay_or_slow_motion")):
        return "contact_gate_reject", visual_time, "excerpt is replay or slow motion"
    # Preserve audio-centered labels when a verified broadcast offset exists.
    # Larger separations are not close enough to establish the same contact.
    if abs(visual_time - expected_relative) > 0.50:
        return (
            "contact_gate_time_mismatch",
            visual_time,
            f"visual={visual_time:.3f}, expected={expected_relative:.3f}",
        )
    if not evidence_is_specific(result.get("visual_evidence")):
        return "contact_gate_bad_evidence", visual_time, "visual evidence is missing or generic"
    if not evidence_is_specific(result.get("audio_evidence")):
        return "contact_gate_bad_evidence", visual_time, "audio evidence is missing or generic"
    try:
        confidence = float(result.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.80:
        return "contact_gate_low_confidence", visual_time, "confidence below 0.80"
    return "contact_gate_pass", visual_time, ""


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    raw_result = record.get("raw_result")
    expected = record.get("expected_relative_candidate_time")
    if not isinstance(raw_result, dict) or expected in {None, ""} or record.get("error"):
        return record
    try:
        expected_relative = float(expected)
    except (TypeError, ValueError):
        return record
    gate_status, visual_time, gate_reason = validate_result(
        raw_result,
        expected_relative,
    )
    normalized = dict(record)
    normalized.update(
        {
            "decision": raw_result.get("decision", ""),
            "contact_gate_status": gate_status,
            "relative_visual_contact_time": (
                f"{visual_time:.3f}" if visual_time is not None else ""
            ),
            "relative_audio_visual_offset": (
                f"{abs(visual_time - expected_relative):.3f}"
                if visual_time is not None
                else ""
            ),
            "contact_visible": raw_result.get("contact_visible", ""),
            "live_pitch_and_swing_visible": raw_result.get(
                "live_pitch_and_swing_visible",
                "",
            ),
            "candidate_sound_is_bat_contact": raw_result.get(
                "candidate_sound_is_bat_contact",
                "",
            ),
            "replay_or_slow_motion": raw_result.get("replay_or_slow_motion", ""),
            "confidence": raw_result.get("confidence", ""),
            "visual_evidence": raw_result.get("visual_evidence", ""),
            "audio_evidence": raw_result.get("audio_evidence", ""),
            "failure_reason": raw_result.get("failure_reason", "") or gate_reason,
        }
    )
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an independent Qwen check on candidate-centered contact clips.")
    parser.add_argument("--first-pass-summary", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--summary-csv", type=Path, required=True)
    parser.add_argument("--usage-jsonl", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument(
        "--prompt",
        type=Path,
        default=REPO_ROOT / "prompts" / "contact_candidate_adjudication.md",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "qwen_reclean_models.json",
    )
    parser.add_argument("--radius", type=float, default=0.70)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Override the configured model order; may be repeated.",
    )
    args = parser.parse_args()

    load_env(args.env_file)
    api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise SystemExit("QWEN_API_KEY or DASHSCOPE_API_KEY is not configured.")
    account_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    config = json.loads(args.config.read_text(encoding="utf-8"))
    models = args.model or [str(model) for model in config["models"]]
    base_url = os.getenv("QWEN_BASE_URL") or config["base_url"]
    switch_at = int(config.get("switch_at_used_tokens", 900000))
    request_reserve = int(config.get("per_request_reserve_tokens", 20000))
    prompt_template = args.prompt.read_text(encoding="utf-8")

    first_pass = [
        row
        for row in read_csv(args.first_pass_summary)
        if row.get("binding_status") == "audio_candidate_bound"
    ]
    if args.sample_id:
        requested = set(args.sample_id)
        first_pass = [row for row in first_pass if row["sample_id"] in requested]
    if args.limit:
        first_pass = first_pass[: args.limit]
    existing = load_jsonl(args.output_jsonl)
    completed = {
        record["main_relative_path"]
        for record in existing
        if record.get("main_relative_path") and not record.get("error")
    }
    usage = model_usage(load_jsonl(args.usage_jsonl), account_fingerprint)
    blocked: set[str] = set()

    for position, row in enumerate(first_pass, start=1):
        if row["main_relative_path"] in completed:
            continue
        base_record: dict[str, Any] = {
            "repair_batch": row["repair_batch"],
            "repair_batch_index": row["repair_batch_index"],
            "collector": row["collector"],
            "sample_id": row["sample_id"],
            "main_relative_path": row["main_relative_path"],
            "first_pass_model": row.get("model", ""),
            "selected_candidate_time": row["selected_candidate_time"],
            "contact_clip_path": "",
            "expected_relative_candidate_time": "",
            "decision": "",
            "contact_gate_status": "",
            "relative_visual_contact_time": "",
            "relative_audio_visual_offset": "",
            "contact_visible": "",
            "live_pitch_and_swing_visible": "",
            "candidate_sound_is_bat_contact": "",
            "replay_or_slow_motion": "",
            "confidence": "",
            "visual_evidence": "",
            "audio_evidence": "",
            "failure_reason": "",
            "model": "",
            "total_tokens": "",
            "error": "",
            "account_fingerprint": account_fingerprint,
            "usage": None,
        }
        video_path = Path(row["media_video_path"])
        if not video_path.is_file():
            append_jsonl(
                args.output_jsonl,
                {**base_record, "contact_gate_status": "media_missing", "error": "first-pass video is missing"},
            )
            continue
        selected_time = float(row["selected_candidate_time"])
        try:
            contact_clip, expected_relative = build_contact_clip(
                video_path,
                selected_time,
                cache_root=args.cache_root,
                ffmpeg=args.ffmpeg,
                radius=args.radius,
            )
        except Exception as exc:
            append_jsonl(
                args.output_jsonl,
                {
                    **base_record,
                    "contact_gate_status": "contact_clip_error",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            continue
        context = {
            "sample_id": row["sample_id"],
            "expected_relative_candidate_seconds": round(expected_relative, 3),
            "clip_duration_seconds": round(2.0 * args.radius, 3),
            "first_pass_selected_audio_candidate_seconds": round(selected_time, 3),
            "first_pass_visual_evidence_is_untrusted": True,
        }
        prompt = prompt_template + "\n\nInput context:\n" + json.dumps(context, ensure_ascii=False)
        available = [
            model
            for model in models
            if model not in blocked
            and model != row.get("model")
            and usage.get(model, 0) + request_reserve <= switch_at
        ]
        if not available:
            append_jsonl(
                args.output_jsonl,
                {
                    **base_record,
                    "contact_clip_path": str(contact_clip),
                    "expected_relative_candidate_time": f"{expected_relative:.3f}",
                    "contact_gate_status": "model_error",
                    "error": "No independent second-pass model remains below the 90% switch threshold.",
                },
            )
            break

        result: dict[str, Any] | None = None
        used_model = ""
        used_usage = None
        error = ""
        attempt_errors: list[str] = []
        for model in available:
            for attempt in range(3):
                try:
                    result, used_usage = call_qwen(
                        model=model,
                        video_path=contact_clip,
                        prompt=prompt,
                        base_url=base_url,
                        api_key=api_key,
                    )
                    used_model = model
                    break
                except (QuotaError, AuthenticationError, ModelUnavailableError) as exc:
                    blocked.add(model)
                    error = f"{type(exc).__name__}: {exc}"
                    attempt_errors.append(error)
                    break
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    attempt_errors.append(error)
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            if result is not None:
                break
        if result is None:
            append_jsonl(
                args.output_jsonl,
                {
                    **base_record,
                    "contact_clip_path": str(contact_clip),
                    "expected_relative_candidate_time": f"{expected_relative:.3f}",
                    "contact_gate_status": "model_error",
                    "error": " | ".join(attempt_errors) or error or "all available models failed",
                },
            )
            continue

        gate_status, visual_time, gate_reason = validate_result(
            result,
            expected_relative,
        )
        token_count = total_tokens(used_usage)
        usage[used_model] = usage.get(used_model, 0) + token_count
        append_jsonl(
            args.usage_jsonl,
            {
                "account_fingerprint": account_fingerprint,
                "model": used_model,
                "usage": used_usage,
                "sample_id": row["sample_id"],
                "main_relative_path": row["main_relative_path"],
                "repair_batch": row["repair_batch"],
                "stage": "contact_clip_adjudication",
                "recorded_at_unix": round(time.time(), 3),
            },
        )
        record = {
            **base_record,
            "contact_clip_path": str(contact_clip),
            "expected_relative_candidate_time": f"{expected_relative:.3f}",
            "decision": result.get("decision", ""),
            "contact_gate_status": gate_status,
            "relative_visual_contact_time": (
                f"{visual_time:.3f}" if visual_time is not None else ""
            ),
            "relative_audio_visual_offset": (
                f"{abs(visual_time - expected_relative):.3f}"
                if visual_time is not None
                else ""
            ),
            "contact_visible": result.get("contact_visible", ""),
            "live_pitch_and_swing_visible": result.get("live_pitch_and_swing_visible", ""),
            "candidate_sound_is_bat_contact": result.get("candidate_sound_is_bat_contact", ""),
            "replay_or_slow_motion": result.get("replay_or_slow_motion", ""),
            "confidence": result.get("confidence", ""),
            "visual_evidence": result.get("visual_evidence", ""),
            "audio_evidence": result.get("audio_evidence", ""),
            "failure_reason": result.get("failure_reason", "") or gate_reason,
            "model": used_model,
            "total_tokens": token_count,
            "error": "",
            "usage": used_usage,
            "raw_result": result,
        }
        append_jsonl(args.output_jsonl, record)
        print(
            json.dumps(
                {
                    "position": position,
                    "total": len(first_pass),
                    "sample_id": row["sample_id"],
                    "contact_gate_status": gate_status,
                    "model": used_model,
                    "model_used_tokens": usage[used_model],
                }
            ),
            flush=True,
        )

    write_summary(args.summary_csv, load_jsonl(args.output_jsonl))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
