from __future__ import annotations

import argparse
import csv
from pathlib import Path


POSITIVE = "confirmed_contact"
EXPLICIT_NEGATIVE = "confirmed_noncontact"
UNKNOWN_NEGATIVE = "assumed_noncontact_from_unknown"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty queue: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def as_probability(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def sample_paths(dataset_root: Path) -> dict[str, str]:
    paths: dict[str, str] = {}
    for audio_path in dataset_root.rglob("audio.wav"):
        sample_id = audio_path.parent.name
        if sample_id in paths:
            raise ValueError(f"duplicate sample directory: {sample_id}")
        paths[sample_id] = audio_path.parent.as_posix()
    return paths


def select_rows(
    truth_rows: list[dict[str, str]],
    predictions: dict[str, dict[str, str]],
    *,
    truth: str,
    count: int,
) -> list[dict[str, str]]:
    candidates = [row for row in truth_rows if row["contact_truth"] == truth]

    def priority(row: dict[str, str]) -> tuple[int, float, str]:
        prediction = predictions[row["sample_id"]]
        if truth == POSITIVE:
            hard = 0 if prediction["outcome"] == "fn" else 1
            return hard, -as_probability(prediction["selected_probability"]), row["sample_id"]
        routed = 0 if prediction["selected"] == "yes" else 1
        return routed, -as_probability(prediction["selected_probability"]), row["sample_id"]

    selected = sorted(candidates, key=priority)[:count]
    if len(selected) != count:
        raise ValueError(f"requested {count} rows for {truth}, found {len(selected)}")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic high-risk 20-sample flyball end-to-end pilot."
    )
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--audio-predictions", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--positive-count", type=int, default=8)
    parser.add_argument("--explicit-negative-count", type=int, default=6)
    parser.add_argument("--unknown-negative-count", type=int, default=6)
    args = parser.parse_args()

    truth_rows = read_csv(args.truth)
    predictions = {
        row["sample_id"]: row for row in read_csv(args.audio_predictions)
    }
    paths = sample_paths(args.dataset_root)
    chosen: list[tuple[str, dict[str, str]]] = []
    for truth, count, stratum in (
        (POSITIVE, args.positive_count, "confirmed_contact_hard"),
        (
            EXPLICIT_NEGATIVE,
            args.explicit_negative_count,
            "confirmed_noncontact_hard",
        ),
        (
            UNKNOWN_NEGATIVE,
            args.unknown_negative_count,
            "unknown_final_negative_hard",
        ),
    ):
        chosen.extend(
            (stratum, row)
            for row in select_rows(
                truth_rows,
                predictions,
                truth=truth,
                count=count,
            )
        )

    output: list[dict[str, str]] = []
    for index, (stratum, truth_row) in enumerate(chosen, start=1):
        sample_id = truth_row["sample_id"]
        prediction = predictions.get(sample_id)
        if prediction is None:
            raise KeyError(f"missing audio prediction for {sample_id}")
        sample_path = paths.get(sample_id)
        if sample_path is None:
            raise FileNotFoundError(f"missing dataset media for {sample_id}")
        output.append(
            {
                "pilot_index": str(index),
                "pilot_stratum": stratum,
                "sample_id": sample_id,
                "main_relative_path": sample_path,
                "contact_truth": truth_row["contact_truth"],
                "project_binary_target": truth_row["project_binary_target"],
                "acoustic_training_role": truth_row["acoustic_training_role"],
                "ground_truth_contact_time": truth_row["contact_time_seconds"],
                "audio_oof_outcome": prediction["outcome"],
                "audio_oof_selected": prediction["selected"],
                "audio_oof_selected_time": prediction["selected_candidate_time"],
                "audio_oof_probability": prediction["selected_probability"],
            }
        )
    write_csv(args.output, output)
    print(
        "pilot_samples={} positive={} explicit_negative={} unknown_negative={}".format(
            len(output),
            args.positive_count,
            args.explicit_negative_count,
            args.unknown_negative_count,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
