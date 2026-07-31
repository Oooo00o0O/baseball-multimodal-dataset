from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path


def as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def existing_contact_times(dataset_root: Path) -> dict[str, float]:
    times: dict[str, float] = {}
    for sample_csv in sorted(dataset_root.rglob("sample.csv")):
        sample_id = sample_csv.parent.name
        if sample_id in times:
            raise ValueError(f"duplicate sample directory for {sample_id}")
        with sample_csv.open("r", newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != 1:
            raise ValueError(f"{sample_csv} must contain exactly one row")
        start = as_float(rows[0].get("event_start", ""))
        end = as_float(rows[0].get("event_end", ""))
        if start is None or end is None:
            raise ValueError(f"{sample_csv} lacks a numeric event interval")
        times[sample_id] = (start + end) / 2.0
    return times


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile multi-annotator fly-ball contact truth without using full-play completeness as a contact gate.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help="Dataset root used to reuse an existing timestamp when the annotator marked original_time_correct=Y.",
    )
    parser.add_argument(
        "--unknown-as-noncontact",
        action="store_true",
        help="Treat annotations without confirmed positive or explicit negative evidence as no-contact.",
    )
    args = parser.parse_args()

    with args.input.open("r", newline="", encoding="utf-8-sig") as handle:
        annotations = list(csv.DictReader(handle))
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in annotations:
        grouped[row["sample_id"]].append(row)
    dataset_times = (
        existing_contact_times(args.dataset_root) if args.dataset_root else {}
    )

    output: list[dict[str, str]] = []
    for sample_id, rows in sorted(grouped.items()):
        positive_times: list[float] = []
        time_sources: list[str] = []
        for row in rows:
            if row["sound"] != "Y" or row["visual"] != "Y":
                continue
            human_time = as_float(row["human_contact_time"])
            if human_time is not None:
                positive_times.append(human_time)
                time_sources.append("human_numeric")
                continue
            if row["original_time_correct"] == "Y":
                if not args.dataset_root:
                    raise ValueError(
                        f"{sample_id} requires --dataset-root because the annotator "
                        "marked original_time_correct=Y without a replacement time"
                    )
                if sample_id not in dataset_times:
                    raise FileNotFoundError(
                        f"dataset timestamp not found for {sample_id}"
                    )
                positive_times.append(dataset_times[sample_id])
                time_sources.append("existing_timestamp")
        explicit_negative = any(row["sound"] == "N" and row["visual"] == "N" for row in rows)
        if positive_times and explicit_negative:
            truth = "conflict"
        elif positive_times:
            truth = "confirmed_contact"
        elif explicit_negative:
            truth = "confirmed_noncontact"
        else:
            truth = "unknown"
        if truth == "unknown" and args.unknown_as_noncontact:
            truth = "assumed_noncontact_from_unknown"

        # User resolved F_0019: commentary overlap does not invalidate a
        # separately identifiable contact, so prefer its precise positive label.
        if sample_id == "F_0019" and positive_times:
            truth = "confirmed_contact"
        notes: list[str] = []
        if sample_id == "F_0019":
            notes.append("F_0019 project-resolved contact")
        if "existing_timestamp" in time_sources:
            notes.append(
                "existing timestamp reused because original_time_correct=Y"
            )
        if truth == "assumed_noncontact_from_unknown":
            notes.append("unknown annotation treated as noncontact by project rule")

        output.append(
            {
                "sample_id": sample_id,
                "contact_truth": truth,
                "project_binary_target": (
                    "contact_usable_for_contact_gate"
                    if truth == "confirmed_contact"
                    else "invalid_or_no_contact"
                ),
                "acoustic_training_role": (
                    "positive"
                    if truth == "confirmed_contact"
                    else "negative"
                    if truth == "confirmed_noncontact"
                    else "exclude_unresolved_requires_video_gate"
                ),
                "contact_time_seconds": f"{statistics.median(positive_times):.3f}" if positive_times else "",
                "annotation_count": str(len(rows)),
                "annotators": ";".join(row["annotator"] for row in rows),
                "full_process_used_for_truth": "no",
                "contact_time_source": ";".join(sorted(set(time_sources))),
                "notes": "; ".join(notes),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    counts: dict[str, int] = defaultdict(int)
    for row in output:
        counts[row["contact_truth"]] += 1
    print(f"samples={len(output)} truth_counts={dict(counts)}")


if __name__ == "__main__":
    main()
