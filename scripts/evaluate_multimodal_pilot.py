from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


POSITIVE = "confirmed_contact"


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


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def bool_value(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def select_candidate(
    qwen: dict[str, Any],
    scored_candidates: list[dict[str, Any]],
    *,
    probability_floor: float,
    window_margin: float,
) -> dict[str, Any] | None:
    result = qwen.get("result") or {}
    if result.get("decision") != "contact_context_ok":
        return None
    if not bool_value(result.get("batter_visible")):
        return None
    if not bool_value(result.get("live_pitch_and_swing_visible")):
        return None
    if not bool_value(result.get("contact_sound_audible")):
        return None
    if not bool_value(result.get("contact_sound_normal_speed")):
        return None

    start = as_float(result.get("window_start_seconds"))
    end = as_float(result.get("window_end_seconds"))
    if start is None or end is None or end < start:
        center = as_float(result.get("approx_visual_contact_seconds"))
        if center is None:
            return None
        start = center - 0.75
        end = center + 0.75
    eligible = [
        candidate
        for candidate in scored_candidates
        if float(candidate["contact_probability"]) >= probability_floor
        and float(candidate["time"]) >= start - window_margin
        and float(candidate["time"]) <= end + window_margin
    ]
    return max(
        eligible,
        key=lambda candidate: float(candidate["contact_probability"]),
        default=None,
    )


def evaluate(
    pilot_rows: list[dict[str, str]],
    qwen_by_id: dict[str, dict[str, Any]],
    audio_by_id: dict[str, dict[str, str]],
    *,
    probability_floor: float,
    window_margin: float,
    time_tolerance: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    details: list[dict[str, Any]] = []
    tp = fp = fn = tn = 0
    for row in pilot_rows:
        sample_id = row["sample_id"]
        qwen = qwen_by_id[sample_id]
        audio = audio_by_id[sample_id]
        candidates = json.loads(audio["scored_candidates_json"])
        selected = select_candidate(
            qwen,
            candidates,
            probability_floor=probability_floor,
            window_margin=window_margin,
        )
        truth_positive = row["contact_truth"] == POSITIVE
        human_time = as_float(row.get("ground_truth_contact_time"))
        if truth_positive:
            correct_time = (
                selected is not None
                and human_time is not None
                and abs(float(selected["time"]) - human_time) <= time_tolerance
            )
            if correct_time:
                outcome = "tp"
                tp += 1
            else:
                outcome = "fn"
                fn += 1
        elif selected is not None:
            outcome = "fp"
            fp += 1
        else:
            outcome = "tn"
            tn += 1
        result = qwen.get("result") or {}
        details.append(
            {
                "sample_id": sample_id,
                "contact_truth": row["contact_truth"],
                "human_time": human_time if human_time is not None else "",
                "qwen_decision": result.get("decision", ""),
                "qwen_visual_time": result.get(
                    "approx_visual_contact_seconds", ""
                ),
                "qwen_window_start": result.get("window_start_seconds", ""),
                "qwen_window_end": result.get("window_end_seconds", ""),
                "selected_candidate_time": (
                    selected["time"] if selected is not None else ""
                ),
                "selected_probability": (
                    selected["contact_probability"] if selected is not None else ""
                ),
                "outcome": outcome,
            }
        )

    def divide(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    precision = divide(tp, tp + fp)
    recall = divide(tp, tp + fn)
    specificity = divide(tn, tn + fp)
    metrics = {
        "probability_floor": probability_floor,
        "window_margin": window_margin,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": divide(tp + tn, tp + fp + fn + tn),
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "balanced_accuracy": (recall + specificity) / 2.0,
    }
    return metrics, details


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Grid-evaluate Qwen video windows plus local audio candidate probabilities."
    )
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--qwen-jsonl", type=Path, required=True)
    parser.add_argument("--audio-predictions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--time-tolerance", type=float, default=0.15)
    args = parser.parse_args()

    pilot_rows = read_csv(args.pilot)
    qwen_by_id = {
        row["sample_id"]: row for row in read_jsonl(args.qwen_jsonl)
    }
    audio_by_id = {
        row["sample_id"]: row for row in read_csv(args.audio_predictions)
    }
    missing = [
        row["sample_id"]
        for row in pilot_rows
        if row["sample_id"] not in qwen_by_id
        or row["sample_id"] not in audio_by_id
    ]
    if missing:
        raise ValueError(f"pilot evidence missing for: {', '.join(missing)}")

    grid: list[dict[str, Any]] = []
    details_by_key: dict[tuple[float, float], list[dict[str, Any]]] = {}
    for floor in (0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70):
        for margin in (0.0, 0.25, 0.50, 0.75):
            metrics, details = evaluate(
                pilot_rows,
                qwen_by_id,
                audio_by_id,
                probability_floor=floor,
                window_margin=margin,
                time_tolerance=args.time_tolerance,
            )
            grid.append(metrics)
            details_by_key[(floor, margin)] = details
    best = max(
        grid,
        key=lambda row: (
            float(row["accuracy"]),
            float(row["balanced_accuracy"]),
            float(row["precision"]),
            float(row["recall"]),
            float(row["probability_floor"]),
            -float(row["window_margin"]),
        ),
    )
    key = (float(best["probability_floor"]), float(best["window_margin"]))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "multimodal_rule_grid.csv", grid)
    write_csv(
        args.output_dir / "multimodal_best_rule_predictions.csv",
        details_by_key[key],
    )
    (args.output_dir / "multimodal_best_rule.json").write_text(
        json.dumps(best, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(best, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
