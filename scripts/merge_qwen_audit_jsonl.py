from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def key(row: dict[str, Any]) -> str:
    return str(row.get("main_relative_path") or row.get("sample_id") or "")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge disjoint resumable Qwen audit JSONL outputs."
    )
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, default=0)
    parser.add_argument(
        "--model-field",
        default="model",
        help="Result field that identifies the model used for a completed row.",
    )
    args = parser.parse_args()

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in args.input:
        for row in read_jsonl(source):
            item_key = key(row)
            if not item_key:
                raise SystemExit(f"missing path and sample ID in {source}")
            if item_key in seen:
                raise SystemExit(f"duplicate audit result: {item_key}")
            if (
                row.get("error")
                or not row.get(args.model_field)
                or not row.get("result")
            ):
                raise SystemExit(f"incomplete audit result: {item_key}")
            seen.add(item_key)
            merged.append(row)

    if args.expected_rows and len(merged) != args.expected_rows:
        raise SystemExit(
            f"expected {args.expected_rows} unique rows, received {len(merged)}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in merged:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(merged), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
