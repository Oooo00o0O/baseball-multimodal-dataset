from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from qwen_confirm_flyball_candidates import (
    AuthenticationError,
    ModelUnavailableError,
    QuotaError,
    call_qwen,
    load_env,
    load_global_usage_records,
    model_usage,
    total_tokens,
    upload_video_path,
)


PROMPT = """You are an independent verifier for one proposed baseball
bat-ball contact time. Inspect the entire video, but specifically inspect the
candidate time plus about 0.6 seconds before and after it. The candidate was
detected from the original WAV audio, which is the authoritative time clock.

Confirm only when that fixed candidate matches a visible batting/contact action
and a corresponding normal-speed bat-ball contact sound. Do not require the
landing, catch, or complete ball flight. A catch/play replay after an already
verified contact is harmless. Reject when the fixed candidate is commentary,
crowd, glove sound, editing noise, ball flight/catch/aftermath without a batter,
or altered slow-motion contact audio. Return review when unresolved.

Return strict JSON only:
{
  \"decision\": \"confirm|reject|review\",
  \"contact_audible\": true,
  \"contact_sound_normal_speed\": true,
  \"contact_visible\": true,
  \"batting_action_visible\": true,
  \"replay_or_slow_motion_at_contact\": false,
  \"trailing_replay_present\": false,
  \"visual_evidence\": \"specific description\",
  \"audio_evidence\": \"specific description\",
  \"failure_reason\": \"\"
}
"""


def bool_value(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def normalized_decision(result: dict[str, Any]) -> tuple[str, str]:
    """Preserve raw output while resolving a review that contradicts its evidence."""
    decision = str(result.get("decision", "review"))
    confirms_event = all(
        bool_value(result.get(field))
        for field in (
            "contact_audible",
            "contact_sound_normal_speed",
            "contact_visible",
            "batting_action_visible",
        )
    )
    if decision == "review" and confirms_event:
        return "review", "review_contains_consistent_evidence_but_requires_resolution"
    return decision, ""


def rows_from_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def finished_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    complete: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not row.get("error") and row.get("crosscheck_model") and row.get("result"):
                complete.add(row["sample_id"])
    return complete


def main() -> None:
    parser = argparse.ArgumentParser(description="Independently verify a fixed audio candidate in the full original video.")
    parser.add_argument("--first-pass-summary", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--preview-cache", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/qwen_reclean_models.json"))
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--usage-jsonl", type=Path, required=True)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-upload-video-bytes", type=int, default=2 * 1024 * 1024)
    args = parser.parse_args()

    load_env(args.env_file)
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        raise SystemExit("QWEN_API_KEY is not set")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    configured_models = args.model or [str(model) for model in config["models"]]
    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    usage_records = load_global_usage_records(args.usage_jsonl)
    usage = model_usage(usage_records, fingerprint)
    switch_at = int(config.get("switch_at_used_tokens", 900000))
    per_request_reserve = int(config.get("per_request_reserve_tokens", 20000))
    blocked: set[str] = set()
    requested = set(args.sample_id)
    complete = finished_ids(args.output_jsonl)
    rows = [
        row
        for row in rows_from_csv(args.first_pass_summary)
        if (
            row.get("binding_status") == "audio_candidate_bound"
            or row.get("disposition")
            == "candidate_bound_pending_second_review"
        )
        and row["sample_id"] not in complete
        and (not requested or row["sample_id"] in requested)
    ]
    if args.limit:
        rows = rows[: args.limit]

    for position, row in enumerate(rows, start=1):
        candidate = float(row["selected_candidate_time"])
        prompt = PROMPT + "\nInput context:\n" + json.dumps(
            {"sample_id": row["sample_id"], "fixed_audio_candidate_seconds": candidate}
        )
        video = (
            Path(row["media_video_path"])
            if row.get("media_video_path")
            else Path(__file__).resolve().parents[1]
            / row["main_relative_path"]
            / "video.mp4"
        )
        preview = upload_video_path(
            video,
            cache_root=args.preview_cache,
            ffmpeg=args.ffmpeg,
            max_source_bytes=args.max_upload_video_bytes,
        )
        result: dict[str, Any] | None = None
        used_model = ""
        errors: list[str] = []
        available = [
            str(model)
            for model in configured_models
            if model not in blocked
            and model not in {row.get("model"), row.get("qwen_model")}
            and usage.get(str(model), 0) + per_request_reserve <= switch_at
        ]
        if not available:
            errors.append(
                "No configured model is available below the quota safety threshold."
            )
        used_usage: dict[str, Any] | None = None
        for model in available:
            if model == row.get("model"):
                continue
            try:
                result, used_usage = call_qwen(
                    model=model,
                    video_path=preview,
                    prompt=prompt,
                    base_url=os.getenv("QWEN_BASE_URL") or config["base_url"],
                    api_key=api_key,
                )
                used_model = model
                break
            except (QuotaError, ModelUnavailableError, AuthenticationError) as exc:
                blocked.add(model)
                errors.append(str(exc))
            except RuntimeError as exc:
                errors.append(str(exc))
            if result is not None:
                break
        if result is not None:
            token_count = total_tokens(used_usage)
            usage[used_model] = usage.get(used_model, 0) + token_count
            append_jsonl(
                args.usage_jsonl,
                {
                    "account_fingerprint": fingerprint,
                    "sample_id": row["sample_id"],
                    "main_relative_path": row["main_relative_path"],
                    "model": used_model,
                    "usage": used_usage,
                    "recorded_at_unix": time.time(),
                    "stage": "fixed_candidate_crosscheck",
                },
            )
        elif not errors:
            errors.append("No model result was returned for this sample.")
        record = {
            "sample_id": row["sample_id"],
            "main_relative_path": row["main_relative_path"],
            "candidate_time": row["selected_candidate_time"],
            "first_pass_model": row.get("model", "") or row.get("qwen_model", ""),
            "crosscheck_model": used_model,
            "result": result or {},
            "normalized_decision": normalized_decision(result or {})[0] if result else "model_error",
            "normalization_reason": normalized_decision(result or {})[1] if result else "",
            "error": " | ".join(errors) if result is None else "",
            "account_fingerprint": fingerprint,
            "usage": used_usage,
        }
        append_jsonl(args.output_jsonl, record)
        print(json.dumps({"position": position, "sample_id": row["sample_id"], "model": used_model, "error": bool(record["error"])}), flush=True)


if __name__ == "__main__":
    main()
