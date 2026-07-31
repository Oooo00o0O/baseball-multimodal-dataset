from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            records[row["sample_id"]] = row
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the revised audit gates against hard manual calibration rows.")
    parser.add_argument("--manual", type=Path, required=True)
    parser.add_argument("--first-pass", type=Path, required=True)
    parser.add_argument("--crosscheck", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    manual: dict[str, dict[str, str]] = {}
    for row in read_csv(args.manual):
        if row.get("calibration_use") == "hard":
            manual.setdefault(row["sample_id"], row)
    first = read_jsonl(args.first_pass)
    cross = read_jsonl(args.crosscheck)

    output: list[dict[str, str]] = []
    for sample_id, human in sorted(manual.items()):
        first_row = first.get(sample_id, {})
        cross_row = cross.get(sample_id, {})
        decision = (cross_row.get("result") or {}).get("decision", "not_run")
        output.append(
            {
                "sample_id": sample_id,
                "human_conclusion": human["human_conclusion"],
                "human_errors": human.get("errors", ""),
                "first_pass_status": first_row.get("binding_status", "not_run"),
                "first_pass_candidate_time": str(first_row.get("selected_candidate_time", "")),
                "crosscheck_decision": decision,
                "crosscheck_model": cross_row.get("crosscheck_model", ""),
                "crosscheck_evidence": str((cross_row.get("result") or {}).get("visual_evidence", "")),
                "crosscheck_failure_reason": str((cross_row.get("result") or {}).get("failure_reason", "")),
            }
        )

    confirmed = [row for row in output if row["crosscheck_decision"] == "confirm"]
    true_positive = sum(row["human_conclusion"] == "V" for row in confirmed)
    false_positive = sum(row["human_conclusion"] == "I" for row in confirmed)
    human_valid = sum(row["human_conclusion"] == "V" for row in output)
    recall = true_positive / human_valid if human_valid else 0.0
    precision = true_positive / len(confirmed) if confirmed else 0.0
    false_positive_ids = [row["sample_id"] for row in confirmed if row["human_conclusion"] == "I"]
    false_negative_ids = [
        row["sample_id"]
        for row in output
        if row["human_conclusion"] == "V" and row["crosscheck_decision"] != "confirm"
    ]

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    args.output_md.write_text(
        "# Revised Gate Calibration Report\n\n"
        f"- Hard calibration samples: {len(output)}\n"
        f"- Human valid: {human_valid}\n"
        f"- Crosscheck confirmed: {len(confirmed)}\n"
        f"- Precision among confirmed samples: {precision:.1%} ({true_positive}/{len(confirmed)})\n"
        f"- Recall for human-valid samples: {recall:.1%} ({true_positive}/{human_valid})\n\n"
        "## Failed Safety Gate\n\n"
        "The revised full-video crosscheck is not safe to use as an automatic training-data acceptance gate.\n"
        f"- Human-invalid samples confirmed by both model stages: {', '.join(false_positive_ids)}\n"
        f"- Human-valid samples not confirmed by the crosscheck: {', '.join(false_negative_ids)}\n",
        encoding="utf-8",
    )
    print(json.dumps({"hard_samples": len(output), "precision": precision, "recall": recall}))


if __name__ == "__main__":
    main()
