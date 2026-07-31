from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

from qwen_confirm_flyball_candidates import (
    AuthenticationError,
    ModelUnavailableError,
    QuotaError,
    call_qwen,
    load_env,
)


PROMPT = """You are verifying a baseball bat-ball contact candidate using a
chronological contact sheet extracted from the original video. Each tile has
its original-video timestamp. The candidate audio time is supplied below.

Decide only from the supplied frames whether a live pitch, bat swing, and
bat-ball contact are visibly present at or very near the candidate time. A
frame sequence showing the batter before and after the candidate is evidence;
do not reject merely because the exact ball is small or partly occluded.

Return strict JSON only:
{
  \"decision\": \"confirm|reject|review\",
  \"contact_visible\": true,
  \"live_pitch_and_swing_visible\": true,
  \"visual_contact_seconds\": 0.0,
  \"visual_evidence\": \"specific description using timestamped frames\",
  \"failure_reason\": \"\"
}
"""


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def existing_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        json.loads(line)["sample_id"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not json.loads(line).get("error")
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Review original-video contact sheets with Qwen image input.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/qwen_reclean_models.json"))
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    load_env(args.env_file)
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        raise SystemExit("QWEN_API_KEY is not set")
    config = load_config(args.config)
    models = args.model or config["models"]
    complete = existing_keys(args.output_jsonl)
    rows = [row for row in read_csv(args.manifest) if row["sample_id"] not in complete]
    if args.limit:
        rows = rows[: args.limit]

    for position, row in enumerate(rows, start=1):
        context = {
            "sample_id": row["sample_id"],
            "candidate_audio_seconds": float(row["candidate_time"]),
            "frame_offsets_seconds": row["frame_offsets"],
            "full_clip_visual_contact_seconds": row["full_clip_visual_contact"],
        }
        prompt = PROMPT + "\nInput context:\n" + json.dumps(context)
        result: dict[str, Any] | None = None
        used_model = ""
        errors: list[str] = []
        for model in models:
            try:
                result, _usage = call_qwen(
                    model=model,
                    video_path=Path(row["contact_sheet"]),
                    prompt=prompt,
                    base_url=os.getenv("QWEN_BASE_URL") or config["base_url"],
                    api_key=api_key,
                    media_type="image_url",
                )
                used_model = model
                break
            except (QuotaError, ModelUnavailableError, AuthenticationError, RuntimeError) as exc:
                errors.append(str(exc))
        record = {
            "sample_id": row["sample_id"],
            "candidate_time": row["candidate_time"],
            "contact_sheet": row["contact_sheet"],
            "audio_excerpt": row["audio_excerpt"],
            "model": used_model,
            "result": result or {},
            "error": " | ".join(errors) if result is None else "",
        }
        append_jsonl(args.output_jsonl, record)
        print(json.dumps({"position": position, "sample_id": row["sample_id"], "model": used_model, "error": bool(record["error"])}), flush=True)


if __name__ == "__main__":
    main()
