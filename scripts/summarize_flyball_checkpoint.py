from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(paths: list[Path]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                row = json.loads(raw)
                key = row.get("main_relative_path")
                if key:
                    latest[key] = row
    return latest


def as_true(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize one non-destructive fly-ball Qwen checkpoint.")
    parser.add_argument("--audio-audit", type=Path, required=True)
    parser.add_argument("--first-pass-jsonl", type=Path, action="append", required=True)
    parser.add_argument("--gate-jsonl", type=Path, action="append", required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    audit_rows = read_csv(args.audio_audit)
    first_by_path = read_jsonl(args.first_pass_jsonl)
    gate_by_path = read_jsonl(args.gate_jsonl)
    output_rows: list[dict[str, str]] = []
    for row in audit_rows:
        key = row["main_relative_path"]
        first = first_by_path.get(key, {})
        gate = gate_by_path.get(key, {})
        first_status = str(first.get("binding_status", ""))
        gate_status = str(gate.get("contact_gate_status", ""))
        if not first:
            status = "qwen_full_clip_pending"
            action = "resume_full_clip_review"
        elif first.get("error"):
            status = "model_error_pending"
            action = "resume_full_clip_review"
        elif first_status != "audio_candidate_bound":
            status = "needs_source_recovery"
            action = "failure_directed_source_recovery"
        elif not gate:
            status = "qwen_contact_gate_pending"
            action = "resume_centered_contact_gate"
        elif gate.get("error"):
            status = "model_error_pending"
            action = "resume_centered_contact_gate"
        elif gate_status == "contact_gate_pass":
            if as_true(first.get("full_play_visible")):
                status = "verified_usable"
                action = "keep_current_sample_pending_final_reconciliation"
            else:
                status = "verified_contact_needs_longer_recut"
                action = "recover_source_and_recut_longer"
        else:
            status = "needs_source_recovery"
            action = "failure_directed_source_recovery"
        output_rows.append(
            {
                "global_index": row["global_index"],
                "sample_id": row["sample_id"],
                "main_relative_path": key,
                "audio_prefilter_error": row["primary_error"],
                "first_pass_status": first_status,
                "first_pass_model": str(first.get("model", "")),
                "selected_candidate_time": str(first.get("selected_candidate_time", "")),
                "full_play_visible": str(first.get("full_play_visible", "")),
                "contact_gate_status": gate_status,
                "contact_gate_model": str(gate.get("model", "")),
                "final_status": status,
                "next_action": action,
                "first_pass_reason": str(first.get("failure_reason", "")),
                "contact_gate_reason": str(gate.get("failure_reason", "")),
            }
        )
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    statuses = Counter(row["final_status"] for row in output_rows)
    gate_statuses = Counter(row["contact_gate_status"] or "pending" for row in output_rows)
    lines = [
        "# Fly Ball Checkpoint Report",
        "",
        f"- Expected samples: {len(output_rows)}",
        f"- Full-clip Qwen completed: {sum(bool(first_by_path.get(row['main_relative_path'])) for row in audit_rows)}",
        f"- Independent contact gate completed: {sum(bool(gate_by_path.get(row['main_relative_path'])) for row in audit_rows)}",
        "",
        "## Final Status Counts",
        "",
        *[f"- {name}: {count}" for name, count in statuses.most_common()],
        "",
        "## Independent Gate Counts",
        "",
        *[f"- {name}: {count}" for name, count in gate_statuses.most_common()],
        "",
        "Rows not marked `verified_usable` remain unchanged. A contact-gate rejection must enter failure-directed source recovery before any replacement decision.",
    ]
    args.output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"samples": len(output_rows), "statuses": dict(statuses)}))


if __name__ == "__main__":
    main()
