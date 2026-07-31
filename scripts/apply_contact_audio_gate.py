from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from evaluate_contact_audio_gate import (
    FEATURE_NAMES,
    Model,
    load_candidate_rows,
    predict,
    sample_predictions,
)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_model(path: Path) -> tuple[Model, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("feature_names") != FEATURE_NAMES:
        raise ValueError("model feature names do not match the current extractor")
    coefficients = payload["coefficients"]
    weights = np.asarray(
        [
            float(payload["intercept"]),
            *(float(coefficients[name]) for name in FEATURE_NAMES),
        ],
        dtype=np.float64,
    )
    model = Model(
        mean=np.asarray(payload["feature_mean"], dtype=np.float64),
        scale=np.asarray(payload["feature_scale"], dtype=np.float64),
        weights=weights,
    )
    return model, float(payload["threshold"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply a fitted contact-audio candidate gate to calibration evidence."
    )
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-label-tolerance", type=float, default=0.05)
    parser.add_argument("--positive-time-tolerance", type=float, default=0.15)
    args = parser.parse_args()

    rows = load_candidate_rows(
        args.evidence,
        positive_candidate_tolerance=args.candidate_label_tolerance,
    )
    model, threshold = load_model(args.model)
    probabilities = predict(model, rows)
    predictions = sample_predictions(
        rows,
        probabilities,
        threshold=threshold,
        positive_time_tolerance=args.positive_time_tolerance,
    )
    scored_by_sample: dict[str, list[dict[str, float | int]]] = {}
    counters: dict[str, int] = {}
    for row, probability in zip(rows, probabilities, strict=True):
        index = counters.get(row.sample_id, 0) + 1
        counters[row.sample_id] = index
        scored_by_sample.setdefault(row.sample_id, []).append(
            {
                "index": index,
                "time": row.time,
                "score": row.score,
                "contact_probability": round(float(probability), 8),
            }
        )
    for prediction in predictions:
        scored = scored_by_sample[str(prediction["sample_id"])]
        best = max(scored, key=lambda candidate: candidate["contact_probability"])
        prediction["best_candidate_index"] = best["index"]
        prediction["best_candidate_time"] = best["time"]
        prediction["best_candidate_probability"] = best["contact_probability"]
        prediction["scored_candidates_json"] = json.dumps(
            scored,
            ensure_ascii=True,
            separators=(",", ":"),
        )
    write_csv(args.output, predictions)
    print(
        json.dumps(
            {
                "samples": len(predictions),
                "threshold": threshold,
                "selected": sum(row["selected"] == "yes" for row in predictions),
                "output": str(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
