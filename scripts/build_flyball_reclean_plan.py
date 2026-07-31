from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_rows(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def split_evenly(rows: list[dict[str, str]], parts: int) -> list[list[dict[str, str]]]:
    base, extra = divmod(len(rows), parts)
    batches: list[list[dict[str, str]]] = []
    offset = 0
    for index in range(parts):
        size = base + (1 if index < extra else 0)
        batches.append(rows[offset : offset + size])
        offset += size
    return batches


def count_actions(rows: list[dict[str, str]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for action in row.get("required_actions", "").split(";"):
            if action:
                counts[action] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine fly-ball audit chunks and create four repair batches.")
    parser.add_argument(
        "--chunk-dir",
        type=Path,
        default=REPO_ROOT
        / "reports"
        / "flyball_main_reclean_20260728"
        / "audit_chunks",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "flyball_main_reclean_20260728",
    )
    parser.add_argument("--batches", type=int, default=4)
    args = parser.parse_args()

    chunk_paths = sorted(args.chunk_dir.glob("audit_*.csv"))
    if not chunk_paths:
        raise SystemExit(f"No audit chunks found under {args.chunk_dir}")
    rows = read_rows(chunk_paths)
    rows.sort(key=lambda row: int(row["global_index"]))
    indices = [int(row["global_index"]) for row in rows]
    expected = list(range(1, len(rows) + 1))
    if indices != expected:
        raise SystemExit("Audit rows are not a complete, unique 1-based sequence.")
    paths = [row["main_relative_path"] for row in rows]
    if len(paths) != len(set(paths)):
        raise SystemExit("Duplicate main_relative_path values found in audit.")

    repair_rows = [row for row in rows if row["status"] == "needs_edit"]
    batches = split_evenly(repair_rows, args.batches)
    batch_lookup: dict[str, tuple[int, int]] = {}
    for batch_number, batch in enumerate(batches, start=1):
        for batch_index, row in enumerate(batch, start=1):
            batch_lookup[row["main_relative_path"]] = (batch_number, batch_index)

    all_fieldnames = [*rows[0].keys(), "repair_batch", "repair_batch_index"]
    augmented_rows: list[dict[str, Any]] = []
    for row in rows:
        batch_number, batch_index = batch_lookup.get(row["main_relative_path"], ("", ""))
        augmented_rows.append(
            {
                **row,
                "repair_batch": batch_number,
                "repair_batch_index": batch_index,
            }
        )
    write_csv(args.output_dir / "flyball_audit_all.csv", augmented_rows, all_fieldnames)
    public_fieldnames = [
        name for name in all_fieldnames if name != "resolved_source_path"
    ]
    public_rows = [
        {name: row.get(name, "") for name in public_fieldnames}
        for row in augmented_rows
    ]
    write_csv(
        args.output_dir / "flyball_audit.csv",
        public_rows,
        public_fieldnames,
    )

    batch_summary_rows: list[dict[str, Any]] = []
    for batch_number, batch in enumerate(batches, start=1):
        batch_dir = args.output_dir / f"batch_{batch_number:02d}"
        batch_rows: list[dict[str, Any]] = []
        for batch_index, row in enumerate(batch, start=1):
            batch_rows.append(
                {
                    **row,
                    "repair_batch": batch_number,
                    "repair_batch_index": batch_index,
                }
            )
        write_csv(batch_dir / "work_queue.csv", batch_rows, all_fieldnames)
        for category in sorted({row["primary_error"] for row in batch}):
            category_rows = [row for row in batch_rows if row["primary_error"] == category]
            write_csv(batch_dir / f"{category}.csv", category_rows, all_fieldnames)

        category_counts = Counter(row["primary_error"] for row in batch)
        audio_counts = Counter(row["event_audio_assessment"] for row in batch)
        source_available = sum(row["source_available_locally"] == "yes" for row in batch)
        batch_summary_rows.append(
            {
                "batch": batch_number,
                "samples": len(batch),
                "first_global_index": batch[0]["global_index"] if batch else "",
                "last_global_index": batch[-1]["global_index"] if batch else "",
                "first_sample_path": batch[0]["main_relative_path"] if batch else "",
                "last_sample_path": batch[-1]["main_relative_path"] if batch else "",
                "clip_too_short": category_counts["clip_too_short"],
                "contact_timestamp_wrong": category_counts["contact_timestamp_wrong"],
                "source_recovery_required": category_counts["source_recovery_required"],
                "audio_candidate_review": category_counts["audio_candidate_review"],
                "semantic_or_schema_review": category_counts["semantic_or_schema_review"],
                "audio_confirmed_at_current_time": audio_counts[
                    "annotated_contact_audio_confirmed"
                ],
                "source_available_locally": source_available,
                "source_not_available_locally": len(batch) - source_available,
            }
        )
    write_csv(
        args.output_dir / "repair_batch_summary.csv",
        batch_summary_rows,
        list(batch_summary_rows[0]) if batch_summary_rows else [],
    )

    status_counts = Counter(row["status"] for row in rows)
    category_counts = Counter(row["primary_error"] for row in rows)
    audio_counts = Counter(row["event_audio_assessment"] for row in rows)
    collector_counts = Counter(row["collector"] for row in rows)
    action_counts = count_actions(rows)
    source_available = sum(row["source_available_locally"] == "yes" for row in rows)
    lines = [
        "# Fly Ball Main Audio-First Audit",
        "",
        "This report is based on the checked-out `origin/main` tree. The audit did not edit dataset samples.",
        "",
        "## Inventory",
        "",
        f"- Total fly_ball sample directories: {len(rows)}",
        *[f"- {name}: {count}" for name, count in collector_counts.items()],
        f"- Local original source available: {source_available}",
        f"- Local original source unavailable: {len(rows) - source_available}",
        "",
        "## First-Pass Result",
        "",
        f"- Direct-use candidates: {status_counts['direct_use_candidate']}",
        f"- Needs editing or focused review: {status_counts['needs_edit']}",
        "",
        "A direct-use candidate passed the automated audio and context gates. It still requires the planned visual spot check. A needs-edit row remains unchanged until a replacement passes all batch gates.",
        "",
        "## Primary Error Counts",
        "",
        *[f"- {name}: {count}" for name, count in category_counts.most_common()],
        "",
        "## Audio Assessment Counts",
        "",
        *[f"- {name}: {count}" for name, count in audio_counts.most_common()],
        "",
        "## Required Action Counts",
        "",
        *[f"- {name}: {count}" for name, count in action_counts.most_common()],
        "",
        "## Four Repair Batches",
        "",
        "| batch | samples | index range | short clip | wrong timestamp | source recovery | audio review | semantic/schema | local source missing |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in batch_summary_rows:
        lines.append(
            f"| {row['batch']} | {row['samples']} | "
            f"{row['first_global_index']}-{row['last_global_index']} | "
            f"{row['clip_too_short']} | {row['contact_timestamp_wrong']} | "
            f"{row['source_recovery_required']} | {row['audio_candidate_review']} | "
            f"{row['semantic_or_schema_review']} | {row['source_not_available_locally']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `contact_timestamp_wrong` means a stronger nearby audio candidate lies outside the current event interval; video confirmation is required before writing the new interval.",
            "- `clip_too_short` means the automated context target was not met. Qwen or manual video review may prove that the full play is already visible; otherwise the sample is recut from source.",
            "- `source_recovery_required` means the current annotation lacks convincing contact audio and must return to the source before any rejection decision.",
            "- No unresolved row may be replaced by an empty folder.",
        ]
    )
    (args.output_dir / "audit_summary.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print(
        f"total={len(rows)} direct={status_counts['direct_use_candidate']} "
        f"needs_edit={status_counts['needs_edit']} batches="
        + ",".join(str(len(batch)) for batch in batches)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
