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


PROMPT = """Inspect the entire supplied baseball broadcast video without any
preselected timestamp. This is the video-first gate: first locate a visible
batting action, then listen for its corresponding bat-ball contact sound. Do
not infer contact from a loud sound, commentary, the title, or later ball
flight alone.

First find an actually visible batter. Return contact only when the video shows
an ordered live-play sequence containing the pitch arriving, the batter
swinging, and immediate follow-through or batted-ball departure. The exact
baseball may be too small to see. A view containing only an outfielder, ball
flight, catch, runner, celebration, dugout, replay, or aftermath is not visual
evidence of live bat-ball contact.

The clip does not need to show the landing, catch, or entire ball flight. A
contact near the beginning or end is acceptable when the visible swing/contact
and the matching normal-speed hit sound are still unambiguous. A replay of the
catch or play after an already verified contact does not invalidate the sample.

Return `contact_needs_recut` only when the contact pair cannot be verified, for
example: visual contact without a corresponding hit sound, a candidate sound
without a visible batting action, or the selected batting action itself is
slow motion with altered/slow audio. Do not use this decision merely because
the post-contact result is incomplete.

When live contact exists, provide:
- an approximate visual contact time;
- a broad visual search window spanning pitch arrival through follow-through.
These are only used to search the original WAV. They are not final audio
timestamps.

Return strict JSON only. Use null times when no live contact is visible:
{
  \"decision\": \"contact_context_ok|contact_needs_recut|no_live_contact|review\",
  \"approx_visual_contact_seconds\": 0.0,
  \"window_start_seconds\": 0.0,
  \"window_end_seconds\": 0.0,
  \"batter_visible\": true,
  \"live_pitch_and_swing_visible\": true,
  \"contact_sound_audible\": true,
  \"contact_sound_normal_speed\": true,
  \"replay_or_slow_motion_at_contact\": false,
  \"trailing_replay_present\": false,
  \"pre_contact_context_sufficient\": true,
  \"post_contact_context_sufficient\": true,
  \"clip_context_sufficient\": true,
  \"visual_evidence\": \"specific ordered visible actions with approximate times\",
  \"failure_reason\": \"\"
}
"""


def rows_from_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def completed_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    complete: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not row.get("error") and row.get("model") and row.get("result"):
                complete.add(row["sample_id"])
    return complete


def main() -> None:
    parser = argparse.ArgumentParser(description="Propose video-first live swing windows with Qwen.")
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--preview-cache", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/qwen_reclean_models.json"))
    parser.add_argument(
        "--usage-jsonl",
        type=Path,
        required=True,
        help="Usage log; all sibling audit usage logs are aggregated before model selection.",
    )
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Override the configured model order for a controlled comparison.",
    )
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
    done = completed_ids(args.output_jsonl)
    rows = [
        row
        for row in rows_from_csv(args.queue)
        if row["sample_id"] not in done and (not requested or row["sample_id"] in requested)
    ]
    if args.limit:
        rows = rows[: args.limit]

    root = Path(__file__).resolve().parents[1]
    for position, row in enumerate(rows, start=1):
        video = root / row["main_relative_path"] / "video.mp4"
        preview = upload_video_path(
            video,
            cache_root=args.preview_cache,
            ffmpeg=args.ffmpeg,
            max_source_bytes=args.max_upload_video_bytes,
        )
        result: dict[str, Any] | None = None
        model_used = ""
        errors: list[str] = []
        used_usage: dict[str, Any] | None = None
        available = [
            str(model)
            for model in configured_models
            if model not in blocked
            and usage.get(str(model), 0) + per_request_reserve <= switch_at
        ]
        if not available:
            errors.append(
                "No configured model is available below the quota safety threshold."
            )
        for model in available:
            for attempt in range(2):
                try:
                    result, used_usage = call_qwen(
                        model=model,
                        video_path=preview,
                        prompt=PROMPT,
                        base_url=os.getenv("QWEN_BASE_URL") or config["base_url"],
                        api_key=api_key,
                    )
                    model_used = model
                    break
                except (QuotaError, ModelUnavailableError, AuthenticationError) as exc:
                    blocked.add(model)
                    errors.append(str(exc))
                    break
                except RuntimeError as exc:
                    errors.append(str(exc))
                    if attempt == 0:
                        time.sleep(2)
            if result is not None:
                break
        if result is not None:
            token_count = total_tokens(used_usage)
            usage[model_used] = usage.get(model_used, 0) + token_count
            append_jsonl(
                args.usage_jsonl,
                {
                    "account_fingerprint": fingerprint,
                    "sample_id": row["sample_id"],
                    "main_relative_path": row["main_relative_path"],
                    "model": model_used,
                    "usage": used_usage,
                    "recorded_at_unix": time.time(),
                    "stage": "video_first_window_proposal",
                },
            )
        elif not errors:
            errors.append("No model result was returned for this sample.")
        record = {
            "sample_id": row["sample_id"],
            "main_relative_path": row["main_relative_path"],
            "model": model_used,
            "result": result or {},
            "error": " | ".join(errors) if result is None else "",
            "model_attempt_errors": errors,
            "account_fingerprint": fingerprint,
            "usage": used_usage,
        }
        append_jsonl(args.output_jsonl, record)
        print(json.dumps({"position": position, "sample_id": row["sample_id"], "model": model_used, "error": bool(record["error"])}), flush=True)


if __name__ == "__main__":
    main()
