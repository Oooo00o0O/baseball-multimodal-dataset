from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def source_recut_category(disposition: str) -> tuple[str, str]:
    mapping = {
        "contact_visible_audio_unresolved": (
            "visible_contact_audio_unresolved",
            "recover source and re-localize normal-speed bat-contact audio",
        ),
        "needs_source_recut_no_visual_contact": (
            "no_verified_live_contact_in_clip",
            "recover source and recut around an actual live batting action",
        ),
        "needs_source_recut": (
            "contact_pair_unverified",
            "recover source and recut to make video and normal-speed audio unambiguous",
        ),
    }
    return mapping.get(
        disposition,
        ("manual_source_review", "recover source and perform manual multimodal review"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile one completed flyball audit batch into publish and recut queues."
    )
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--bound", type=Path, required=True)
    parser.add_argument("--verified", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--recut-csv", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    queue = read_csv(args.queue)
    bound = {row["main_relative_path"]: row for row in read_csv(args.bound)}
    verified = {row["main_relative_path"]: row for row in read_csv(args.verified)}
    reconciliation: list[dict[str, Any]] = []
    recut: list[dict[str, Any]] = []

    for row in queue:
        path_key = row["main_relative_path"]
        bound_row = bound.get(path_key, {})
        verified_row = verified.get(path_key, {})
        if verified_row.get("outcome") == "metadata_time_correction":
            outcome = "metadata_time_correction"
            category = "independent_multimodal_confirmation"
            action = "publish corrected event_start/event_end"
            after_start = verified_row["after_event_start"]
            after_end = verified_row["after_event_end"]
            review_model = verified_row["crosscheck_model"]
        elif verified_row.get("outcome") == "needs_source_recut":
            outcome = "needs_source_recut"
            category = "candidate_rejected_by_independent_review"
            action = "recover source and replace only after a new full review"
            after_start = ""
            after_end = ""
            review_model = verified_row["crosscheck_model"]
        else:
            source_disposition = bound_row.get("disposition", "manual_review")
            category, action = source_recut_category(source_disposition)
            outcome = "needs_source_recut"
            after_start = ""
            after_end = ""
            review_model = bound_row.get("qwen_model", "")

        result = {
            "global_index": row["global_index"],
            "repair_batch_index": row.get("repair_batch_index", ""),
            "collector": row["collector"],
            "sample_id": row["sample_id"],
            "main_relative_path": path_key,
            "before_event_start": row["current_event_start"],
            "before_event_end": row["current_event_end"],
            "after_event_start": after_start,
            "after_event_end": after_end,
            "outcome": outcome,
            "category": category,
            "action": action,
            "first_pass_disposition": bound_row.get("disposition", ""),
            "first_pass_model": bound_row.get("qwen_model", ""),
            "independent_review_model": review_model,
            "old_prefilter_status": row.get("status", ""),
            "old_primary_error": row.get("primary_error", ""),
        }
        reconciliation.append(result)
        if outcome == "needs_source_recut":
            recut.append(
                {
                    "global_index": row["global_index"],
                    "collector": row["collector"],
                    "sample_id": row["sample_id"],
                    "main_relative_path": path_key,
                    "source_txt_path": f"{path_key}/source.txt",
                    "before_event_start": row["current_event_start"],
                    "before_event_end": row["current_event_end"],
                    "reason_category": category,
                    "required_next_action": action,
                    "status": "pending_source_recovery",
                }
            )

    if len(reconciliation) != len(queue):
        raise SystemExit("queue reconciliation did not preserve every row")
    write_csv(args.output_csv, reconciliation)
    write_csv(args.recut_csv, recut)

    counts = Counter(row["outcome"] for row in reconciliation)
    categories = Counter(row["category"] for row in reconciliation)
    corrected = [row for row in reconciliation if row["outcome"] == "metadata_time_correction"]
    lines = [
        "# Flyball Reverse Batch 001 Audit Report",
        "",
        "## Scope",
        "",
        f"- Queue rows: {len(reconciliation)}",
        "- Audit order: global index 1207 down to 958",
        "- Decision standard: visible batting/contact action plus matching normal-speed bat-contact audio.",
        "- Trailing catch/play replay is allowed; selected slow-motion or commentary audio is not.",
        "",
        "## Outcomes",
        "",
    ]
    for name, count in sorted(counts.items()):
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Recut Categories", ""])
    for name, count in sorted(categories.items()):
        lines.append(f"- {name}: {count}")
    lines.extend(
        [
            "",
            "## Applied Metadata Corrections",
            "",
            "| Sample | Before | After | Independent reviewer |",
            "|---|---:|---:|---|",
        ]
    )
    for row in corrected:
        before = f"{row['before_event_start']} to {row['before_event_end']}"
        after = f"{row['after_event_start']} to {row['after_event_end']}"
        lines.append(
            f"| {row['main_relative_path']} | {before} | {after} | {row['independent_review_model']} |"
        )
    lines.extend(
        [
            "",
            "## Pending Source Recovery",
            "",
            f"- {len(recut)} rows remain unchanged in the dataset and are listed in the recut CSV.",
            "- They are not cleared, deleted, or published as corrected training samples.",
        ]
    )
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        {
            "rows": len(reconciliation),
            "metadata_time_correction": counts["metadata_time_correction"],
            "needs_source_recut": counts["needs_source_recut"],
            "output_csv": str(args.output_csv),
            "recut_csv": str(args.recut_csv),
            "output_md": str(args.output_md),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
