from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_latest_jsonl(paths: list[Path]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                latest[row["main_relative_path"]] = row
    return latest


def category(row: dict[str, str], gate: dict[str, Any]) -> tuple[str, str, str, str]:
    if row["final_status"] == "model_error_pending":
        return (
            "P04",
            "technical_retry",
            "The preview could not be transcoded, so no content conclusion exists yet.",
            "Retry preview generation and the full-clip Qwen check before any source decision.",
        )
    if row["first_pass_status"] == "no_candidate_selected":
        return (
            "P03",
            "no_reliable_audio_candidate",
            "The full-clip review could not bind any detected audio transient to bat-ball contact.",
            "Re-run audio candidate extraction; if still empty, recover a longer/cleaner source clip.",
        )
    if row["first_pass_status"] == "audio_visual_time_mismatch":
        return (
            "P03",
            "audio_visual_time_mismatch",
            "Audio and visual contact candidates disagree by more than the allowed alignment window.",
            "Re-check A/V alignment on the source and re-cut around the verified contact point.",
        )
    if gate.get("live_pitch_and_swing_visible") is False:
        return (
            "P02",
            "candidate_outside_live_contact_window",
            "The short clip shows no live pitch/swing at the selected candidate time; it is post-contact or another play moment.",
            "Search the original video for the live pitch and re-localize the audio candidate before re-cutting.",
        )
    return (
        "P01",
        "swing_visible_but_candidate_not_bat_contact",
        "A live swing is visible near the candidate, but the selected sound is not confirmed as bat-ball contact.",
        "Re-analyze nearby audio transients and retain only a candidate that matches the visible contact moment.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an actionable failure taxonomy for one audit checkpoint.")
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--gate-jsonl", type=Path, action="append", required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    gates = read_latest_jsonl(args.gate_jsonl)
    rows: list[dict[str, str]] = []
    for item in read_csv(args.reconciliation):
        if item["final_status"] == "verified_usable":
            continue
        gate = gates.get(item["main_relative_path"], {})
        code, name, explanation, action = category(item, gate)
        rows.append(
            {
                "sample_id": item["sample_id"],
                "global_index": item["global_index"],
                "main_relative_path": item["main_relative_path"],
                "problem_code": code,
                "problem_category": name,
                "problem_explanation": explanation,
                "recommended_next_action": action,
                "audio_prefilter_result": item["audio_prefilter_error"],
                "first_pass_status": item["first_pass_status"],
                "selected_candidate_time": item["selected_candidate_time"],
                "contact_gate_status": item["contact_gate_status"],
                "gate_failure_reason": item["contact_gate_reason"],
            }
        )

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['problem_code']} {row['problem_category']}"
        counts[key] = counts.get(key, 0) + 1
    args.output_md.write_text(
        "# Checkpoint 001 Failure Taxonomy\n\n"
        + f"- Problem samples: {len(rows)}\n\n"
        + "## Counts\n\n"
        + "\n".join(f"- {key}: {count}" for key, count in counts.items())
        + "\n\nThis is a review and repair queue only; it does not alter dataset media.\n",
        encoding="utf-8",
    )
    print(f"problem_samples={len(rows)} categories={counts}")


if __name__ == "__main__":
    main()
