#!/usr/bin/env python3
"""Fill the bounded review-media buffer and compute contact proposals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from contact_detector import DetectorConfig
from media_preparation import MediaPreparer, read_review_rows
from scheduling import ScheduleConfig, select_for_preparation
from stores import CandidateInventoryStore


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA = PROJECT_ROOT / "data" / "review" / "mlb_candidate_curation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=DEFAULT_DATA / "candidate_inventory.csv",
    )
    parser.add_argument(
        "--reviews-dir",
        type=Path,
        default=DEFAULT_DATA / "reviews",
    )
    parser.add_argument(
        "--media-root",
        type=Path,
        default=DEFAULT_DATA / "media",
    )
    parser.add_argument("--buffer-target", type=int, default=30)
    parser.add_argument("--per-game-cap", type=int, default=3)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--ffmpeg", default="")
    parser.add_argument("--ffprobe", default="")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--force-analysis", action="store_true")
    parser.add_argument("--mid-low-hz", type=float, default=1800.0)
    parser.add_argument("--mid-high-hz", type=float, default=7000.0)
    parser.add_argument("--high-low-hz", type=float, default=5000.0)
    parser.add_argument("--high-high-hz", type=float, default=16000.0)
    return parser.parse_args()


def prepare(args: argparse.Namespace) -> dict[str, object]:
    inventory = CandidateInventoryStore(args.inventory)
    review_rows = read_review_rows(args.reviews_dir)
    schedule_config = ScheduleConfig(
        buffer_target=args.buffer_target,
        per_game_cap=args.per_game_cap,
    )
    selected = select_for_preparation(
        inventory.all(),
        review_rows,
        schedule_config,
    )
    reason_by_id = {item.source_play_id: item.reason_zh for item in selected}
    for item in selected:
        inventory.upsert(
            {
                "source_play_id": item.source_play_id,
                "media_status": "queued_for_preparation",
            }
        )

    reviewed_ids = {
        str(row.get("source_play_id") or "").strip()
        for row in review_rows
    }
    queue = [
        row
        for row in inventory.all()
        if row["source_play_id"] not in reviewed_ids
        and str(row.get("media_status") or "") == "queued_for_preparation"
    ]
    queue.sort(
        key=lambda row: (
            0 if str(row.get("media_match_confidence")) == "high" else 1,
            str(row.get("game_date") or ""),
            str(row.get("source_play_id") or ""),
        )
    )
    if args.max_files > 0:
        queue = queue[: args.max_files]

    detector_config = DetectorConfig(
        mid_band_low_hz=args.mid_low_hz,
        mid_band_high_hz=args.mid_high_hz,
        high_band_low_hz=args.high_low_hz,
        high_band_high_hz=args.high_high_hz,
    )
    preparer = MediaPreparer(
        project_root=PROJECT_ROOT,
        media_root=args.media_root,
        ffmpeg=args.ffmpeg or None,
        ffprobe=args.ffprobe or None,
        detector_config=detector_config,
    )
    prepared: list[str] = []
    failed: list[dict[str, str]] = []
    for row in queue:
        source_play_id = str(row["source_play_id"])
        try:
            result = preparer.prepare(
                row,
                force_download=args.force_download,
                force_analysis=args.force_analysis,
            )
            inventory.upsert(result.inventory_update)
            prepared.append(source_play_id)
        except Exception as error:
            inventory.upsert(
                {
                    "source_play_id": source_play_id,
                    "media_status": "preparation_failed",
                }
            )
            failed.append(
                {
                    "source_play_id": source_play_id,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    return {
        "selected": len(selected),
        "attempted": len(queue),
        "prepared": len(prepared),
        "failed": len(failed),
        "prepared_source_play_ids": prepared,
        "selection_reasons_zh": reason_by_id,
        "failures": failed,
    }


def main() -> None:
    print(json.dumps(prepare(parse_args()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
