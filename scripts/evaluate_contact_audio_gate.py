from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from audit_flyball_main import read_wav_mono


POSITIVE_TRUTH = "confirmed_contact"
EXPLICIT_NEGATIVE = "confirmed_noncontact"
ASSUMED_NEGATIVE = "assumed_noncontact_from_unknown"
NEGATIVE_TRUTHS = {EXPLICIT_NEGATIVE, ASSUMED_NEGATIVE}

FEATURE_NAMES = [
    "log_candidate_score",
    "log_candidate_rms_ratio",
    "log_candidate_diff_ratio",
    "log_short_rms_vs_context",
    "log_short_diff_vs_context",
    "log_peak_vs_context_rms",
    "short_crest_factor",
    "short_zero_crossing_rate",
    "short_kurtosis",
    "spectral_centroid",
    "spectral_bandwidth",
    "spectral_flatness",
    "spectral_entropy",
    "spectral_rolloff_85",
    "band_0_500_ratio",
    "band_500_2000_ratio",
    "band_2000_5000_ratio",
    "band_5000_nyquist_ratio",
    "log_center_rms_vs_pre",
    "log_center_rms_vs_post",
    "log_center_diff_vs_pre",
    "log_center_diff_vs_post",
    "envelope_peak_offset",
    "envelope_peak_concentration",
    "envelope_half_peak_width",
    "pre_audio_available",
    "post_audio_available",
]


@dataclass(frozen=True)
class CandidateRow:
    sample_id: str
    truth: str
    human_time: float | None
    time: float
    score: float
    is_contact_candidate: bool
    features: np.ndarray


@dataclass(frozen=True)
class Model:
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray


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


def parse_float(value: Any) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def safe_log_ratio(numerator: float, denominator: float) -> float:
    value = math.log((max(numerator, 0.0) + 1e-8) / (max(denominator, 0.0) + 1e-8))
    return float(np.clip(value, -8.0, 8.0))


def rms(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(values * values) + 1e-12))


def diff_rms(values: np.ndarray) -> float:
    if values.size < 2:
        return 0.0
    differences = np.diff(values)
    return float(np.sqrt(np.mean(differences * differences) + 1e-12))


def slice_audio(
    audio: np.ndarray,
    sample_rate: int,
    start: float,
    end: float,
) -> tuple[np.ndarray, float]:
    expected = max(1, round((end - start) * sample_rate))
    first = max(0, round(start * sample_rate))
    last = min(len(audio), round(end * sample_rate))
    if last <= first:
        return np.zeros(0, dtype=np.float32), 0.0
    values = audio[first:last]
    return values, min(1.0, len(values) / expected)


def concatenate(parts: list[np.ndarray]) -> np.ndarray:
    available = [part for part in parts if part.size]
    if not available:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(available)


def spectral_features(values: np.ndarray, sample_rate: int) -> list[float]:
    if values.size < 16:
        return [0.0] * 9
    windowed = values * np.hanning(len(values)).astype(np.float32)
    fft_size = 1 << max(8, (len(windowed) - 1).bit_length())
    spectrum = np.abs(np.fft.rfft(windowed, n=fft_size)) ** 2
    frequencies = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
    if spectrum.size <= 1:
        return [0.0] * 9
    spectrum = spectrum[1:]
    frequencies = frequencies[1:]
    total = float(np.sum(spectrum)) + 1e-12
    probabilities = spectrum / total
    nyquist = sample_rate / 2.0
    centroid_hz = float(np.sum(frequencies * probabilities))
    bandwidth_hz = float(
        np.sqrt(np.sum(((frequencies - centroid_hz) ** 2) * probabilities))
    )
    flatness = float(
        np.exp(np.mean(np.log(spectrum + 1e-12))) / (np.mean(spectrum) + 1e-12)
    )
    entropy = float(
        -np.sum(probabilities * np.log(probabilities + 1e-12))
        / max(math.log(len(probabilities)), 1e-12)
    )
    cumulative = np.cumsum(probabilities)
    rolloff_index = min(int(np.searchsorted(cumulative, 0.85)), len(frequencies) - 1)
    rolloff = float(frequencies[rolloff_index] / nyquist)

    def band_ratio(low: float, high: float) -> float:
        mask = (frequencies >= low) & (frequencies < min(high, nyquist + 1.0))
        return float(np.sum(spectrum[mask]) / total) if np.any(mask) else 0.0

    return [
        centroid_hz / nyquist,
        bandwidth_hz / nyquist,
        flatness,
        entropy,
        rolloff,
        band_ratio(0.0, 500.0),
        band_ratio(500.0, 2000.0),
        band_ratio(2000.0, 5000.0),
        band_ratio(5000.0, nyquist + 1.0),
    ]


def envelope_features(
    audio: np.ndarray,
    sample_rate: int,
    center: float,
) -> list[float]:
    frame_seconds = 0.005
    offsets = np.arange(-0.12, 0.1201, frame_seconds)
    envelope: list[float] = []
    for offset in offsets:
        frame, _ = slice_audio(
            audio,
            sample_rate,
            center + float(offset) - frame_seconds / 2.0,
            center + float(offset) + frame_seconds / 2.0,
        )
        envelope.append(rms(frame))
    values = np.asarray(envelope, dtype=np.float64)
    peak_index = int(np.argmax(values))
    peak = float(values[peak_index])
    peak_offset = float(offsets[peak_index] / 0.12)
    concentration = peak / (float(np.sum(values)) + 1e-12)
    half_width = float(np.count_nonzero(values >= peak * 0.5) / len(values))
    return [peak_offset, concentration, half_width]


def extract_features(
    audio: np.ndarray,
    sample_rate: int,
    candidate: dict[str, float],
) -> np.ndarray:
    center = float(candidate["time"])
    short, _ = slice_audio(audio, sample_rate, center - 0.020, center + 0.020)
    center_window, _ = slice_audio(
        audio, sample_rate, center - 0.010, center + 0.010
    )
    pre, pre_available = slice_audio(
        audio, sample_rate, center - 0.250, center - 0.050
    )
    post, post_available = slice_audio(
        audio, sample_rate, center + 0.050, center + 0.250
    )
    context = concatenate([pre, post])

    short_rms = rms(short)
    short_diff = diff_rms(short)
    context_rms = rms(context)
    context_diff = diff_rms(context)
    peak = float(np.max(np.abs(short))) if short.size else 0.0
    crest = peak / (short_rms + 1e-8)
    if short.size >= 2:
        zcr = float(np.mean(np.signbit(short[:-1]) != np.signbit(short[1:])))
    else:
        zcr = 0.0
    if short.size:
        centered = short - float(np.mean(short))
        variance = float(np.mean(centered * centered))
        kurtosis = float(np.mean(centered**4) / (variance * variance + 1e-12))
    else:
        kurtosis = 0.0

    feature_values = [
        math.log1p(float(candidate["score"])),
        math.log1p(float(candidate["rms_ratio"])),
        math.log1p(float(candidate["diff_ratio"])),
        safe_log_ratio(short_rms, context_rms),
        safe_log_ratio(short_diff, context_diff),
        safe_log_ratio(peak, context_rms),
        float(np.clip(crest, 0.0, 25.0)),
        zcr,
        float(np.clip(kurtosis, 0.0, 100.0)),
        *spectral_features(short, sample_rate),
        safe_log_ratio(rms(center_window), rms(pre)),
        safe_log_ratio(rms(center_window), rms(post)),
        safe_log_ratio(diff_rms(center_window), diff_rms(pre)),
        safe_log_ratio(diff_rms(center_window), diff_rms(post)),
        *envelope_features(audio, sample_rate, center),
        pre_available,
        post_available,
    ]
    features = np.asarray(feature_values, dtype=np.float64)
    if features.shape != (len(FEATURE_NAMES),):
        raise AssertionError(
            f"feature count mismatch: {features.shape[0]} != {len(FEATURE_NAMES)}"
        )
    if not np.all(np.isfinite(features)):
        raise ValueError(f"non-finite features at candidate {center:.3f}")
    return features


def load_candidate_rows(
    evidence_path: Path,
    *,
    positive_candidate_tolerance: float,
) -> list[CandidateRow]:
    result: list[CandidateRow] = []
    for row in read_csv(evidence_path):
        sample_id = row["sample_id"]
        truth = row["contact_truth"]
        human_time = parse_float(row.get("human_time"))
        audio, sample_rate, _ = read_wav_mono(Path(row["audio_path"]))
        candidates = json.loads(row["candidates_json"])
        contact_index = None
        if truth == POSITIVE_TRUTH and human_time is not None and candidates:
            nearest_index = min(
                range(len(candidates)),
                key=lambda index: abs(float(candidates[index]["time"]) - human_time),
            )
            if (
                abs(float(candidates[nearest_index]["time"]) - human_time)
                <= positive_candidate_tolerance
            ):
                contact_index = nearest_index
        for index, candidate in enumerate(candidates):
            result.append(
                CandidateRow(
                    sample_id=sample_id,
                    truth=truth,
                    human_time=human_time,
                    time=float(candidate["time"]),
                    score=float(candidate["score"]),
                    is_contact_candidate=index == contact_index,
                    features=extract_features(audio, sample_rate, candidate),
                )
            )
    return result


def stable_order(sample_id: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{sample_id}".encode("ascii")).hexdigest()


def assign_folds(rows: list[CandidateRow], folds: int, seed: int) -> dict[str, int]:
    truths: dict[str, str] = {}
    for row in rows:
        truths[row.sample_id] = row.truth
    assignments: dict[str, int] = {}
    for truth in (POSITIVE_TRUTH, EXPLICIT_NEGATIVE, ASSUMED_NEGATIVE):
        sample_ids = sorted(
            (sample_id for sample_id, value in truths.items() if value == truth),
            key=lambda sample_id: stable_order(sample_id, seed),
        )
        for index, sample_id in enumerate(sample_ids):
            assignments[sample_id] = index % folds
    return assignments


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def fit_model(
    rows: list[CandidateRow],
    *,
    regularization: float,
    iterations: int,
    learning_rate: float,
) -> Model:
    x = np.vstack([row.features for row in rows])
    y = np.asarray([row.is_contact_candidate for row in rows], dtype=np.float64)
    if np.unique(y).size != 2:
        raise ValueError("training fold must contain positive and negative candidates")
    mean = np.mean(x, axis=0)
    scale = np.std(x, axis=0)
    scale[scale < 1e-6] = 1.0
    standardized = (x - mean) / scale
    design = np.column_stack([np.ones(len(rows)), standardized])

    per_sample_counts: dict[str, int] = {}
    for row in rows:
        per_sample_counts[row.sample_id] = per_sample_counts.get(row.sample_id, 0) + 1
    sample_weights = np.asarray(
        [1.0 / per_sample_counts[row.sample_id] for row in rows],
        dtype=np.float64,
    )
    positive_mass = float(np.sum(sample_weights[y == 1.0]))
    negative_mass = float(np.sum(sample_weights[y == 0.0]))
    class_weights = np.where(
        y == 1.0,
        0.5 / max(positive_mass, 1e-12),
        0.5 / max(negative_mass, 1e-12),
    )
    weights_per_row = sample_weights * class_weights
    weights_per_row /= float(np.sum(weights_per_row))

    weights = np.zeros(design.shape[1], dtype=np.float64)
    first_moment = np.zeros_like(weights)
    second_moment = np.zeros_like(weights)
    beta1 = 0.9
    beta2 = 0.999
    for step in range(1, iterations + 1):
        probabilities = sigmoid(design @ weights)
        gradient = design.T @ ((probabilities - y) * weights_per_row)
        gradient[1:] += regularization * weights[1:] / len(FEATURE_NAMES)
        first_moment = beta1 * first_moment + (1.0 - beta1) * gradient
        second_moment = beta2 * second_moment + (1.0 - beta2) * (gradient * gradient)
        corrected_first = first_moment / (1.0 - beta1**step)
        corrected_second = second_moment / (1.0 - beta2**step)
        weights -= learning_rate * corrected_first / (
            np.sqrt(corrected_second) + 1e-8
        )
    return Model(mean=mean, scale=scale, weights=weights)


def predict(model: Model, rows: list[CandidateRow]) -> np.ndarray:
    x = np.vstack([row.features for row in rows])
    standardized = (x - model.mean) / model.scale
    design = np.column_stack([np.ones(len(rows)), standardized])
    return sigmoid(design @ model.weights)


def sample_predictions(
    rows: list[CandidateRow],
    probabilities: np.ndarray,
    *,
    threshold: float,
    positive_time_tolerance: float,
) -> list[dict[str, object]]:
    grouped: dict[str, list[tuple[CandidateRow, float]]] = {}
    for row, probability in zip(rows, probabilities, strict=True):
        grouped.setdefault(row.sample_id, []).append((row, float(probability)))
    predictions: list[dict[str, object]] = []
    for sample_id in sorted(grouped):
        candidates = grouped[sample_id]
        best_row, best_probability = max(candidates, key=lambda item: item[1])
        selected = best_probability >= threshold
        if best_row.truth == POSITIVE_TRUTH:
            time_error = (
                abs(best_row.time - best_row.human_time)
                if selected and best_row.human_time is not None
                else None
            )
            outcome = (
                "tp"
                if selected
                and time_error is not None
                and time_error <= positive_time_tolerance
                else "fn"
            )
        else:
            time_error = None
            outcome = "fp" if selected else "tn"
        predictions.append(
            {
                "sample_id": sample_id,
                "contact_truth": best_row.truth,
                "human_time": (
                    best_row.human_time if best_row.human_time is not None else ""
                ),
                "selected": "yes" if selected else "no",
                "selected_candidate_time": best_row.time if selected else "",
                "selected_probability": round(best_probability, 8),
                "selected_candidate_score": best_row.score if selected else "",
                "time_error": (
                    round(time_error, 6) if time_error is not None else ""
                ),
                "outcome": outcome,
            }
        )
    return predictions


def metrics(predictions: list[dict[str, object]]) -> dict[str, object]:
    counts = {
        outcome: sum(row["outcome"] == outcome for row in predictions)
        for outcome in ("tp", "fp", "fn", "tn")
    }
    tp = counts["tp"]
    fp = counts["fp"]
    fn = counts["fn"]
    tn = counts["tn"]

    def divide(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    precision = divide(tp, tp + fp)
    recall = divide(tp, tp + fn)
    specificity = divide(tn, tn + fp)
    f1 = divide(2.0 * precision * recall, precision + recall)
    explicit_predictions = [
        row for row in predictions if row["contact_truth"] == EXPLICIT_NEGATIVE
    ]
    assumed_predictions = [
        row for row in predictions if row["contact_truth"] == ASSUMED_NEGATIVE
    ]
    return {
        **counts,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "false_positive_rate": 1.0 - specificity,
        "balanced_accuracy": (recall + specificity) / 2.0,
        "f1": f1,
        "explicit_noncontact_fp": sum(
            row["outcome"] == "fp" for row in explicit_predictions
        ),
        "explicit_noncontact_total": len(explicit_predictions),
        "assumed_unknown_fp": sum(
            row["outcome"] == "fp" for row in assumed_predictions
        ),
        "assumed_unknown_total": len(assumed_predictions),
    }


def tune_threshold(
    rows: list[CandidateRow],
    probabilities: np.ndarray,
    *,
    positive_time_tolerance: float,
    target_specificity: float,
) -> tuple[float, dict[str, object]]:
    candidates = sorted(
        {
            0.01,
            0.99,
            *(
                float(value)
                for value in np.quantile(
                    probabilities,
                    np.linspace(0.0, 1.0, 201),
                )
            ),
        }
    )
    evaluated: list[tuple[float, dict[str, object]]] = []
    for threshold in candidates:
        result = metrics(
            sample_predictions(
                rows,
                probabilities,
                threshold=threshold,
                positive_time_tolerance=positive_time_tolerance,
            )
        )
        evaluated.append((threshold, result))
    eligible = [
        item
        for item in evaluated
        if float(item[1]["specificity"]) >= target_specificity
    ]
    pool = eligible if eligible else evaluated
    return max(
        pool,
        key=lambda item: (
            float(item[1]["balanced_accuracy"]),
            float(item[1]["recall"]),
            float(item[1]["precision"]),
            item[0],
        ),
    )


def cross_validate(
    rows: list[CandidateRow],
    *,
    folds: int,
    seed: int,
    regularization: float,
    iterations: int,
    learning_rate: float,
    target_specificity: float,
    positive_time_tolerance: float,
    acoustic_truth_only: bool,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    assignments = assign_folds(rows, folds, seed)
    all_predictions: list[dict[str, object]] = []
    fold_rows: list[dict[str, object]] = []
    for fold in range(folds):
        train_rows_all = [
            row for row in rows if assignments[row.sample_id] != fold
        ]
        test_rows = [row for row in rows if assignments[row.sample_id] == fold]
        train_rows = [
            row
            for row in train_rows_all
            if not acoustic_truth_only or row.truth != ASSUMED_NEGATIVE
        ]
        model = fit_model(
            train_rows,
            regularization=regularization,
            iterations=iterations,
            learning_rate=learning_rate,
        )
        train_probabilities = predict(model, train_rows)
        threshold, train_metrics = tune_threshold(
            train_rows,
            train_probabilities,
            positive_time_tolerance=positive_time_tolerance,
            target_specificity=target_specificity,
        )
        test_probabilities = predict(model, test_rows)
        test_predictions = sample_predictions(
            test_rows,
            test_probabilities,
            threshold=threshold,
            positive_time_tolerance=positive_time_tolerance,
        )
        for prediction in test_predictions:
            prediction["fold"] = fold + 1
            prediction["threshold"] = round(threshold, 8)
        acoustic_test_predictions = [
            prediction
            for prediction in test_predictions
            if prediction["contact_truth"] != ASSUMED_NEGATIVE
        ]
        test_metrics = metrics(acoustic_test_predictions)
        unresolved_selected = sum(
            prediction["selected"] == "yes"
            for prediction in test_predictions
            if prediction["contact_truth"] == ASSUMED_NEGATIVE
        )
        unresolved_total = sum(
            prediction["contact_truth"] == ASSUMED_NEGATIVE
            for prediction in test_predictions
        )
        all_predictions.extend(test_predictions)
        fold_rows.append(
            {
                "fold": fold + 1,
                "train_samples": len({row.sample_id for row in train_rows}),
                "test_samples": len({row.sample_id for row in test_rows}),
                "threshold": round(threshold, 8),
                "train_specificity": round(float(train_metrics["specificity"]), 6),
                "test_tp": test_metrics["tp"],
                "test_fp": test_metrics["fp"],
                "test_fn": test_metrics["fn"],
                "test_tn": test_metrics["tn"],
                "test_precision": round(float(test_metrics["precision"]), 6),
                "test_recall": round(float(test_metrics["recall"]), 6),
                "test_specificity": round(float(test_metrics["specificity"]), 6),
                "test_balanced_accuracy": round(
                    float(test_metrics["balanced_accuracy"]), 6
                ),
                "unresolved_selected": unresolved_selected,
                "unresolved_total": unresolved_total,
            }
        )
    return sorted(all_predictions, key=lambda row: str(row["sample_id"])), fold_rows


def model_payload(model: Model, threshold: float) -> dict[str, object]:
    coefficients = {
        name: float(weight)
        for name, weight in zip(FEATURE_NAMES, model.weights[1:], strict=True)
    }
    return {
        "model_type": "standardized_logistic_audio_candidate_gate",
        "feature_names": FEATURE_NAMES,
        "feature_mean": model.mean.tolist(),
        "feature_scale": model.scale.tolist(),
        "intercept": float(model.weights[0]),
        "coefficients": coefficients,
        "threshold": threshold,
        "truth_policy": {
            "positive": POSITIVE_TRUTH,
            "acoustic_negative": EXPLICIT_NEGATIVE,
            "unresolved_video_gate": ASSUMED_NEGATIVE,
        },
    }


def write_report(
    path: Path,
    *,
    acoustic_metrics: dict[str, object],
    project_metrics: dict[str, object],
    fold_rows: list[dict[str, object]],
    final_threshold: float,
    final_train_metrics: dict[str, object],
    final_model: Model,
    target_specificity: float,
) -> None:
    coefficients = sorted(
        zip(FEATURE_NAMES, final_model.weights[1:], strict=True),
        key=lambda item: item[1],
        reverse=True,
    )
    lines = [
        "# Contact Audio Gate Calibration",
        "",
        "## Policy",
        "",
        "- Confirmed contact samples are positive.",
        "- Confirmed non-contact samples are acoustic negatives.",
        "- Unknown samples remain final project negatives, but are excluded from acoustic fitting because some contain a real contact in an unusable clip.",
        "- Unknown samples are routed to the video/context gate and remain separately identifiable.",
        "- Predictions below are out-of-fold; a sample is never evaluated by a model trained on that sample.",
        "",
        "## Cross-validated result",
        "",
        f"- TP / FP / FN / TN: {acoustic_metrics['tp']} / {acoustic_metrics['fp']} / {acoustic_metrics['fn']} / {acoustic_metrics['tn']}",
        f"- Precision: {float(acoustic_metrics['precision']):.1%}",
        f"- Recall: {float(acoustic_metrics['recall']):.1%}",
        f"- Specificity: {float(acoustic_metrics['specificity']):.1%}",
        f"- Balanced accuracy: {float(acoustic_metrics['balanced_accuracy']):.1%}",
        (
            "- Explicit non-contact false positives: "
            f"{acoustic_metrics['explicit_noncontact_fp']}/"
            f"{acoustic_metrics['explicit_noncontact_total']}"
        ),
        "",
        "## Project-negative routing",
        "",
        (
            "- Audio-only result when unknown samples are also counted as final negatives: "
            f"TP / FP / FN / TN = {project_metrics['tp']} / "
            f"{project_metrics['fp']} / {project_metrics['fn']} / "
            f"{project_metrics['tn']}."
        ),
        (
            "- Unknown samples sent forward by the audio gate: "
            f"{project_metrics['assumed_unknown_fp']}/"
            f"{project_metrics['assumed_unknown_total']}."
        ),
        "- These are not automatically accepted; the video/context gate must reject absent swings, post-contact-only clips, replay, and boundary-truncated clips.",
        "",
        "## Fold detail",
        "",
        "| Fold | Threshold | TP | FP | FN | TN | Precision | Recall | Specificity | Balanced accuracy | Unknown routed |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in fold_rows:
        lines.append(
            "| {fold} | {threshold:.3f} | {test_tp} | {test_fp} | {test_fn} | "
            "{test_tn} | {test_precision:.1%} | {test_recall:.1%} | "
            "{test_specificity:.1%} | {test_balanced_accuracy:.1%} | "
            "{unresolved_selected}/{unresolved_total} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Final fitted gate",
            "",
            f"- Target training specificity: {target_specificity:.1%}",
            f"- Selected final threshold: {final_threshold:.6f}",
            f"- In-sample specificity: {float(final_train_metrics['specificity']):.1%}",
            "- The final fitted gate is an implementation artifact, not production approval.",
            "",
            "## Strongest feature directions",
            "",
            "Features with positive coefficients raise contact probability; negative coefficients lower it.",
            "",
            "| Direction | Feature | Standardized coefficient |",
            "|---|---|---:|",
        ]
    )
    for name, coefficient in coefficients[:8]:
        lines.append(f"| Positive | {name} | {coefficient:.4f} |")
    for name, coefficient in reversed(coefficients[-8:]):
        lines.append(f"| Negative | {name} | {coefficient:.4f} |")
    lines.extend(
        [
            "",
            "## Readiness",
            "",
            "- The audio gate may rank candidates, but video still has to confirm a live swing near the selected time.",
            "- Do not use this gate as an automatic accept rule unless its held-out false-positive rate meets the project requirement.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-validate a local audio candidate gate on flyball manual truth."
    )
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--regularization", type=float, default=0.08)
    parser.add_argument("--iterations", type=int, default=1800)
    parser.add_argument("--learning-rate", type=float, default=0.025)
    parser.add_argument("--target-specificity", type=float, default=0.90)
    parser.add_argument("--candidate-label-tolerance", type=float, default=0.05)
    parser.add_argument("--positive-time-tolerance", type=float, default=0.15)
    parser.add_argument(
        "--acoustic-truth-only",
        action="store_true",
        help="Exclude unknown-derived final negatives from acoustic fitting and route them to the video gate.",
    )
    args = parser.parse_args()

    rows = load_candidate_rows(
        args.evidence,
        positive_candidate_tolerance=args.candidate_label_tolerance,
    )
    predictions, fold_rows = cross_validate(
        rows,
        folds=args.folds,
        seed=args.seed,
        regularization=args.regularization,
        iterations=args.iterations,
        learning_rate=args.learning_rate,
        target_specificity=args.target_specificity,
        positive_time_tolerance=args.positive_time_tolerance,
        acoustic_truth_only=args.acoustic_truth_only,
    )
    project_metrics = metrics(predictions)
    acoustic_predictions = [
        prediction
        for prediction in predictions
        if prediction["contact_truth"] != ASSUMED_NEGATIVE
    ]
    acoustic_metrics = metrics(acoustic_predictions)

    final_training_rows = [
        row
        for row in rows
        if not args.acoustic_truth_only or row.truth != ASSUMED_NEGATIVE
    ]
    final_model = fit_model(
        final_training_rows,
        regularization=args.regularization,
        iterations=args.iterations,
        learning_rate=args.learning_rate,
    )
    probabilities = predict(final_model, final_training_rows)
    final_threshold, final_train_metrics = tune_threshold(
        final_training_rows,
        probabilities,
        positive_time_tolerance=args.positive_time_tolerance,
        target_specificity=args.target_specificity,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "audio_gate_oof_predictions.csv", predictions)
    write_csv(args.output_dir / "audio_gate_fold_metrics.csv", fold_rows)
    (args.output_dir / "audio_gate_model.json").write_text(
        json.dumps(
            model_payload(final_model, final_threshold),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    write_report(
        args.output_dir / "audio_gate_calibration.md",
        acoustic_metrics=acoustic_metrics,
        project_metrics=project_metrics,
        fold_rows=fold_rows,
        final_threshold=final_threshold,
        final_train_metrics=final_train_metrics,
        final_model=final_model,
        target_specificity=args.target_specificity,
    )
    print(
        json.dumps(
            {
                "candidate_rows": len(rows),
                "samples": len({row.sample_id for row in rows}),
                "cross_validated_acoustic_metrics": acoustic_metrics,
                "cross_validated_project_metrics": project_metrics,
                "final_threshold": final_threshold,
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
