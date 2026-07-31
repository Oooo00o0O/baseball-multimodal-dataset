from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from evaluate_multimodal_pilot import select_candidate


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def key(row: dict[str, Any]) -> str:
    return str(row.get("main_relative_path") or row.get("sample_id"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bind Qwen video-first evidence to a finite local audio candidate."
    )
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--qwen-jsonl", type=Path, required=True)
    parser.add_argument("--audio-gate", type=Path, required=True)
    parser.add_argument("--rule", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    queue = read_csv(args.queue)
    qwen_by_key = {key(row): row for row in read_jsonl(args.qwen_jsonl)}
    audio_by_key = {key(row): row for row in read_csv(args.audio_gate)}
    rule = json.loads(args.rule.read_text(encoding="utf-8"))
    probability_floor = float(rule["probability_floor"])
    window_margin = float(rule["window_margin"])

    output: list[dict[str, Any]] = []
    for row in queue:
        row_key = key(row)
        qwen = qwen_by_key.get(row_key)
        audio = audio_by_key.get(row_key)
        if qwen is None or audio is None:
            continue
        raw_candidates = (
            audio.get("candidates_json")
            or audio.get("scored_candidates_json")
            or "[]"
        )
        candidates = json.loads(raw_candidates)
        selected = select_candidate(
            qwen,
            candidates,
            probability_floor=probability_floor,
            window_margin=window_margin,
        )
        qwen_result = qwen.get("result") or {}
        qwen_decision = qwen_result.get("decision", "review")
        if qwen.get("error"):
            disposition = "model_error_review"
        elif selected is not None:
            disposition = "candidate_bound_pending_second_review"
        elif qwen_decision == "contact_context_ok":
            disposition = "contact_visible_audio_unresolved"
        elif qwen_decision == "contact_needs_recut":
            disposition = "needs_source_recut"
        elif qwen_decision == "no_live_contact":
            disposition = "needs_source_recut_no_visual_contact"
        else:
            disposition = "manual_review"

        selected_time = (
            float(selected["time"]) if selected is not None else None
        )
        output.append(
            {
                "global_index": row["global_index"],
                "repair_batch": row.get("repair_batch", ""),
                "repair_batch_index": row.get("repair_batch_index", ""),
                "collector": row["collector"],
                "sample_id": row["sample_id"],
                "main_relative_path": row["main_relative_path"],
                "before_event_start": row["current_event_start"],
                "before_event_end": row["current_event_end"],
                "old_prefilter_status": row["status"],
                "old_primary_error": row["primary_error"],
                "qwen_model": qwen.get("model", ""),
                "qwen_decision": qwen_decision,
                "qwen_visual_time": qwen_result.get(
                    "approx_visual_contact_seconds", ""
                ),
                "qwen_window_start": qwen_result.get(
                    "window_start_seconds", ""
                ),
                "qwen_window_end": qwen_result.get(
                    "window_end_seconds", ""
                ),
                "qwen_contact_sound_audible": qwen_result.get(
                    "contact_sound_audible", ""
                ),
                "qwen_contact_sound_normal_speed": qwen_result.get(
                    "contact_sound_normal_speed", ""
                ),
                "selected_candidate_index": (
                    selected["index"] if selected is not None else ""
                ),
                "selected_candidate_time": (
                    selected_time if selected_time is not None else ""
                ),
                "selected_candidate_probability": (
                    selected["contact_probability"]
                    if selected is not None
                    else ""
                ),
                "selected_candidate_score": (
                    selected["score"] if selected is not None else ""
                ),
                "proposed_event_start": (
                    f"{max(0.0, selected_time - 0.05):.3f}"
                    if selected_time is not None
                    else ""
                ),
                "proposed_event_end": (
                    f"{selected_time + 0.05:.3f}"
                    if selected_time is not None
                    else ""
                ),
                "disposition": disposition,
                "visual_evidence": qwen_result.get("visual_evidence", ""),
                "failure_reason": qwen_result.get("failure_reason", ""),
            }
        )
    write_csv(args.output, output)
    counts: dict[str, int] = {}
    for row in output:
        disposition = str(row["disposition"])
        counts[disposition] = counts.get(disposition, 0) + 1
    print(
        json.dumps(
            {
                "rows": len(output),
                "probability_floor": probability_floor,
                "window_margin": window_margin,
                "dispositions": counts,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
