from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from apply_contact_audio_gate import load_model
from audit_flyball_main import read_wav_mono
from evaluate_contact_audio_gate import extract_features, sigmoid
from qwen_confirm_flyball_candidates import candidates_for_audio


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def candidate_probabilities(
    audio_path: Path,
    candidates: list[dict[str, float]],
    model,
) -> list[dict[str, float]]:
    audio, sample_rate, _ = read_wav_mono(audio_path)
    features = np.vstack(
        [
            extract_features(audio, sample_rate, candidate)
            for candidate in candidates
        ]
    )
    standardized = (features - model.mean) / model.scale
    design = np.column_stack([np.ones(len(candidates)), standardized])
    probabilities = sigmoid(design @ model.weights)
    scored = [
        {
            **candidate,
            "contact_probability": round(float(probability), 8),
        }
        for candidate, probability in zip(candidates, probabilities, strict=True)
    ]
    return scored


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the fitted audio contact gate to a production review queue."
    )
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    requested = set(args.sample_id)
    queue = [
        row
        for row in read_csv(args.queue)
        if not requested or row["sample_id"] in requested
    ]
    if args.limit:
        queue = queue[: args.limit]

    model, threshold = load_model(args.model)
    output: list[dict[str, object]] = []
    for row in queue:
        audio_path = repo_root / row["main_relative_path"] / "audio.wav"
        anchor = (
            float(row["current_event_start"]) + float(row["current_event_end"])
        ) / 2.0
        candidates = candidates_for_audio(audio_path, anchor_time=anchor, limit=24)
        if not candidates:
            output.append(
                {
                    "global_index": row["global_index"],
                    "sample_id": row["sample_id"],
                    "main_relative_path": row["main_relative_path"],
                    "existing_anchor_time": round(anchor, 6),
                    "selected": "no",
                    "selected_candidate_index": "",
                    "selected_candidate_time": "",
                    "selected_probability": "",
                    "selected_score": "",
                    "model_threshold": "",
                    "candidate_count": 0,
                    "candidates_json": "[]",
                    "audio_gate_reason": "no_transient_candidates",
                }
            )
            continue
        scored = candidate_probabilities(
            audio_path,
            candidates,
            model,
        )
        best = max(scored, key=lambda candidate: candidate["contact_probability"])
        selected = best["contact_probability"] >= threshold
        output.append(
            {
                "global_index": row["global_index"],
                "sample_id": row["sample_id"],
                "main_relative_path": row["main_relative_path"],
                "existing_anchor_time": round(anchor, 6),
                "selected": "yes" if selected else "no",
                "selected_candidate_index": best["index"] if selected else "",
                "selected_candidate_time": best["time"] if selected else "",
                "selected_probability": best["contact_probability"],
                "selected_score": best["score"] if selected else "",
                "model_threshold": threshold,
                "candidate_count": len(scored),
                "candidates_json": json.dumps(
                    scored,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                "audio_gate_reason": (
                    "candidate_selected"
                    if selected
                    else "best_candidate_below_threshold"
                ),
            }
        )
        print(
            json.dumps(
                {
                    "sample_id": row["sample_id"],
                    "selected": selected,
                    "time": best["time"],
                    "probability": best["contact_probability"],
                }
            ),
            flush=True,
        )
    write_csv(args.output, output)
    print(
        json.dumps(
            {
                "rows": len(output),
                "selected": sum(row["selected"] == "yes" for row in output),
                "output": str(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
