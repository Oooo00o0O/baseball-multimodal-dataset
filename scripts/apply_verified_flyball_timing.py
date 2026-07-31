from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


REQUIRED_EVIDENCE = (
    "contact_audible",
    "contact_sound_normal_speed",
    "contact_visible",
    "batting_action_visible",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def bool_value(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def evidence_is_confirmed(row: dict[str, Any]) -> bool:
    result = row.get("result") or {}
    return (
        row.get("normalized_decision") == "confirm"
        and not row.get("error")
        and bool(row.get("crosscheck_model"))
        and all(bool_value(result.get(field)) for field in REQUIRED_EVIDENCE)
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply timing corrections only after independent multimodal confirmation."
    )
    parser.add_argument("--bound", type=Path, required=True)
    parser.add_argument("--crosscheck", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-confirmed", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    bound = {
        row["main_relative_path"]: row
        for row in read_csv(args.bound)
        if row.get("disposition") == "candidate_bound_pending_second_review"
    }
    crosschecks: dict[str, dict[str, Any]] = {}
    for source in args.crosscheck:
        for row in read_jsonl(source):
            item_key = str(row.get("main_relative_path") or "")
            if not item_key:
                raise SystemExit(f"crosscheck has no main-relative path: {source}")
            if item_key in crosschecks:
                raise SystemExit(f"duplicate crosscheck result: {item_key}")
            crosschecks[item_key] = row

    if set(bound) != set(crosschecks):
        missing = sorted(set(bound) - set(crosschecks))
        extra = sorted(set(crosschecks) - set(bound))
        raise SystemExit(
            f"bound/crosscheck mismatch; missing={len(missing)} extra={len(extra)}"
        )

    report: list[dict[str, Any]] = []
    confirmed = 0
    for path_key, bound_row in bound.items():
        crosscheck = crosschecks[path_key]
        candidate_time = float(bound_row["selected_candidate_time"])
        new_start = max(0.0, candidate_time - 0.05)
        new_end = candidate_time + 0.05
        sample_path = root / path_key / "sample.csv"
        sample_rows = read_csv(sample_path)
        if len(sample_rows) != 1:
            raise SystemExit(f"expected one sample.csv row: {sample_path}")
        sample = sample_rows[0]
        is_confirmed = evidence_is_confirmed(crosscheck)
        if is_confirmed:
            confirmed += 1
        report.append(
            {
                "global_index": bound_row["global_index"],
                "sample_id": bound_row["sample_id"],
                "main_relative_path": path_key,
                "before_event_start": sample.get("event_start", ""),
                "before_event_end": sample.get("event_end", ""),
                "candidate_time": f"{candidate_time:.3f}",
                "after_event_start": f"{new_start:.3f}" if is_confirmed else "",
                "after_event_end": f"{new_end:.3f}" if is_confirmed else "",
                "crosscheck_model": crosscheck.get("crosscheck_model", ""),
                "crosscheck_decision": crosscheck.get("normalized_decision", ""),
                "outcome": (
                    "metadata_time_correction" if is_confirmed else "needs_source_recut"
                ),
                "failure_reason": (crosscheck.get("result") or {}).get(
                    "failure_reason", ""
                ),
            }
        )
        if args.apply and is_confirmed:
            fieldnames = list(sample)
            sample["event_start"] = f"{new_start:.3f}"
            sample["event_end"] = f"{new_end:.3f}"
            with sample_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(sample)

    if args.expected_confirmed and confirmed != args.expected_confirmed:
        raise SystemExit(
            f"expected {args.expected_confirmed} confirmed rows, found {confirmed}"
        )
    write_csv(args.output, report)
    print(
        json.dumps(
            {
                "rows": len(report),
                "confirmed": confirmed,
                "applied": bool(args.apply),
                "output": str(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
