from __future__ import annotations

import argparse
import csv
from pathlib import Path


RECUT_FIELDS = [
    "main_relative_path",
    "video_path",
    "audio_path",
    "status",
    "new_event_start",
    "new_event_end",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare every audio-prefilter row for full-clip Qwen review."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--empty-recut-manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=int, required=True)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument(
        "--order",
        choices=("input", "global-index-desc"),
        default="input",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Keep only the first N rows after ordering and offset, before sharding.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip this many rows after ordering, before max-rows and sharding.",
    )
    args = parser.parse_args()

    with args.input.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("input audit chunk is empty")
    if args.order == "global-index-desc":
        rows.sort(key=lambda row: int(row["global_index"]), reverse=True)
    if args.offset < 0:
        raise SystemExit("offset must be non-negative")
    rows = rows[args.offset:]
    if args.max_rows:
        rows = rows[: args.max_rows]
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("invalid shard count or shard index")
    rows = [
        row
        for position, row in enumerate(rows)
        if position % args.shard_count == args.shard_index
    ]
    fieldnames = [*rows[0].keys(), "repair_batch", "repair_batch_index"]
    args.queue.parent.mkdir(parents=True, exist_ok=True)
    with args.queue.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for position, row in enumerate(rows, start=1):
            writer.writerow(
                {
                    **row,
                    "repair_batch": f"audit_checkpoint_{args.checkpoint:03d}",
                    "repair_batch_index": position,
                }
            )
    with args.empty_recut_manifest.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.DictWriter(handle, fieldnames=RECUT_FIELDS).writeheader()
    print(
        f"queue={len(rows)} checkpoint={args.checkpoint} "
        f"shard={args.shard_index + 1}/{args.shard_count}"
    )


if __name__ == "__main__":
    main()
