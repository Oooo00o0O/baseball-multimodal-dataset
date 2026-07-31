from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from qwen_confirm_flyball_candidates import candidates_for_audio


POSITIVE_TRUTH = "confirmed_contact"
NEGATIVE_TRUTHS = {
    "confirmed_noncontact",
    "assumed_noncontact_from_unknown",
}


@dataclass(frozen=True)
class SampleEvidence:
    sample_id: str
    truth: str
    human_time: float | None
    anchor_time: float
    audio_path: Path
    candidates: list[dict[str, float]]


@dataclass(frozen=True)
class Rule:
    name: str
    select: Callable[[SampleEvidence], dict[str, float] | None]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def parse_float(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def find_sample_dirs(dataset_root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    duplicates: dict[str, list[Path]] = {}
    for audio_path in sorted(dataset_root.rglob("audio.wav")):
        sample_dir = audio_path.parent
        sample_id = sample_dir.name
        if sample_id in result:
            duplicates.setdefault(sample_id, [result[sample_id]]).append(sample_dir)
            continue
        result[sample_id] = sample_dir
    if duplicates:
        details = "; ".join(
            f"{sample_id}: {', '.join(str(path) for path in paths)}"
            for sample_id, paths in sorted(duplicates.items())
        )
        raise ValueError(f"duplicate sample directories found: {details}")
    return result


def sample_anchor(sample_dir: Path) -> float:
    rows = read_csv(sample_dir / "sample.csv")
    if len(rows) != 1:
        raise ValueError(f"{sample_dir / 'sample.csv'} must contain exactly one row")
    start = parse_float(rows[0].get("event_start"))
    end = parse_float(rows[0].get("event_end"))
    if start is None or end is None:
        raise ValueError(f"missing event_start/event_end in {sample_dir / 'sample.csv'}")
    return (start + end) / 2.0


def load_evidence(
    truth_path: Path,
    dataset_root: Path,
    *,
    candidate_limit: int,
) -> list[SampleEvidence]:
    sample_dirs = find_sample_dirs(dataset_root)
    evidence: list[SampleEvidence] = []
    for row in read_csv(truth_path):
        sample_id = row["sample_id"].strip()
        truth = row["contact_truth"].strip()
        if truth not in {POSITIVE_TRUTH, *NEGATIVE_TRUTHS}:
            raise ValueError(f"unsupported contact_truth for {sample_id}: {truth}")
        sample_dir = sample_dirs.get(sample_id)
        if sample_dir is None:
            raise FileNotFoundError(f"dataset sample not found: {sample_id}")
        anchor_time = sample_anchor(sample_dir)
        audio_path = sample_dir / "audio.wav"
        candidates = candidates_for_audio(
            audio_path,
            anchor_time=anchor_time,
            limit=candidate_limit,
        )
        evidence.append(
            SampleEvidence(
                sample_id=sample_id,
                truth=truth,
                human_time=parse_float(row.get("contact_time_seconds")),
                anchor_time=anchor_time,
                audio_path=audio_path,
                candidates=candidates,
            )
        )
    return evidence


def strongest_at_threshold(threshold: float) -> Rule:
    def select(item: SampleEvidence) -> dict[str, float] | None:
        eligible = [
            candidate
            for candidate in item.candidates
            if candidate["score"] >= threshold
        ]
        return max(eligible, key=lambda candidate: candidate["score"], default=None)

    return Rule(f"strongest_score_ge_{threshold:g}", select)


def nearest_anchor_at_threshold(threshold: float, window: float | None = None) -> Rule:
    suffix = f"_within_{window:g}s" if window is not None else ""

    def select(item: SampleEvidence) -> dict[str, float] | None:
        eligible = [
            candidate
            for candidate in item.candidates
            if candidate["score"] >= threshold
            and (
                window is None
                or abs(candidate["time"] - item.anchor_time) <= window
            )
        ]
        return min(
            eligible,
            key=lambda candidate: (
                abs(candidate["time"] - item.anchor_time),
                -candidate["score"],
            ),
            default=None,
        )

    return Rule(f"nearest_anchor_score_ge_{threshold:g}{suffix}", select)


def earliest_at_threshold(threshold: float) -> Rule:
    def select(item: SampleEvidence) -> dict[str, float] | None:
        eligible = [
            candidate
            for candidate in item.candidates
            if candidate["score"] >= threshold
        ]
        return min(eligible, key=lambda candidate: candidate["time"], default=None)

    return Rule(f"earliest_score_ge_{threshold:g}", select)


def build_rules() -> list[Rule]:
    rules: list[Rule] = []
    for threshold in (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0):
        rules.extend(
            [
                strongest_at_threshold(threshold),
                nearest_anchor_at_threshold(threshold),
                nearest_anchor_at_threshold(threshold, window=0.60),
                earliest_at_threshold(threshold),
            ]
        )
    return rules


def divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_rule(
    rule: Rule,
    evidence: list[SampleEvidence],
    *,
    tolerance: float,
) -> dict[str, object]:
    tp = fp = fn = tn = 0
    explicit_fp = explicit_total = 0
    assumed_fp = assumed_total = 0
    positive_time_errors: list[float] = []
    for item in evidence:
        selected = rule.select(item)
        if item.truth == POSITIVE_TRUTH:
            if item.human_time is None:
                raise ValueError(f"positive sample lacks human time: {item.sample_id}")
            if selected is not None:
                time_error = abs(selected["time"] - item.human_time)
                if time_error <= tolerance:
                    tp += 1
                    positive_time_errors.append(time_error)
                else:
                    fn += 1
            else:
                fn += 1
            continue

        if item.truth == "confirmed_noncontact":
            explicit_total += 1
        else:
            assumed_total += 1
        if selected is None:
            tn += 1
        else:
            fp += 1
            if item.truth == "confirmed_noncontact":
                explicit_fp += 1
            else:
                assumed_fp += 1

    precision = divide(tp, tp + fp)
    recall = divide(tp, tp + fn)
    specificity = divide(tn, tn + fp)
    f1 = divide(2 * precision * recall, precision + recall)
    return {
        "rule": rule.name,
        "tolerance_seconds": tolerance,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "specificity": round(specificity, 6),
        "false_positive_rate": round(1.0 - specificity, 6),
        "balanced_accuracy": round((recall + specificity) / 2.0, 6),
        "f1": round(f1, 6),
        "explicit_noncontact_fp": explicit_fp,
        "explicit_noncontact_total": explicit_total,
        "assumed_unknown_fp": assumed_fp,
        "assumed_unknown_total": assumed_total,
        "mean_positive_time_error": (
            round(sum(positive_time_errors) / len(positive_time_errors), 6)
            if positive_time_errors
            else ""
        ),
    }


def candidate_rows(
    evidence: list[SampleEvidence],
    *,
    tolerance: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in evidence:
        nearest = None
        nearest_distance = None
        nearest_rank = None
        if item.human_time is not None and item.candidates:
            nearest = min(
                item.candidates,
                key=lambda candidate: abs(candidate["time"] - item.human_time),
            )
            nearest_distance = abs(nearest["time"] - item.human_time)
            nearest_rank = int(nearest["index"])
        rows.append(
            {
                "sample_id": item.sample_id,
                "contact_truth": item.truth,
                "human_time": item.human_time if item.human_time is not None else "",
                "existing_anchor_time": round(item.anchor_time, 6),
                "anchor_error": (
                    round(abs(item.anchor_time - item.human_time), 6)
                    if item.human_time is not None
                    else ""
                ),
                "candidate_count": len(item.candidates),
                "human_candidate_covered": (
                    "yes"
                    if nearest_distance is not None and nearest_distance <= tolerance
                    else "no"
                    if item.human_time is not None
                    else ""
                ),
                "nearest_human_candidate_time": (
                    nearest["time"] if nearest is not None else ""
                ),
                "nearest_human_candidate_error": (
                    round(nearest_distance, 6)
                    if nearest_distance is not None
                    else ""
                ),
                "nearest_human_candidate_rank": (
                    nearest_rank if nearest_rank is not None else ""
                ),
                "nearest_human_candidate_score": (
                    nearest["score"] if nearest is not None else ""
                ),
                "max_candidate_score": (
                    max(candidate["score"] for candidate in item.candidates)
                    if item.candidates
                    else ""
                ),
                "audio_path": str(item.audio_path),
                "candidates_json": json.dumps(
                    item.candidates,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    path: Path,
    evidence: list[SampleEvidence],
    rows: list[dict[str, object]],
    rule_results: list[dict[str, object]],
    *,
    tolerance: float,
) -> None:
    positives = [item for item in evidence if item.truth == POSITIVE_TRUTH]
    explicit = [item for item in evidence if item.truth == "confirmed_noncontact"]
    assumed = [
        item
        for item in evidence
        if item.truth == "assumed_noncontact_from_unknown"
    ]
    covered = sum(row["human_candidate_covered"] == "yes" for row in rows)
    ranked = sorted(
        rule_results,
        key=lambda row: (
            float(row["balanced_accuracy"]),
            float(row["precision"]),
            float(row["recall"]),
        ),
        reverse=True,
    )
    lines = [
        "# Contact Calibration Baseline",
        "",
        "## Truth policy",
        "",
        f"- Positive: {len(positives)} confirmed-contact samples.",
        f"- Negative: {len(explicit) + len(assumed)} samples.",
        f"- Explicit non-contact: {len(explicit)}.",
        f"- Unknown treated as non-contact: {len(assumed)}.",
        "- The two negative origins stay separate in every false-positive count.",
        "",
        "## Candidate generation",
        "",
        (
            f"- Human contact covered within +/-{tolerance:.3f}s: "
            f"{covered}/{len(positives)} ({divide(covered, len(positives)):.1%})."
        ),
        "- Coverage measures candidate generation only; it is not an automatic pass.",
        "",
        "## Best baseline rules",
        "",
        "| Rule | TP | FP | FN | TN | Precision | Recall | Specificity | Balanced accuracy | Explicit FP | Unknown-derived FP |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in ranked[:10]:
        lines.append(
            "| {rule} | {tp} | {fp} | {fn} | {tn} | {precision:.1%} | "
            "{recall:.1%} | {specificity:.1%} | {balanced_accuracy:.1%} | "
            "{explicit_noncontact_fp}/{explicit_noncontact_total} | "
            "{assumed_unknown_fp}/{assumed_unknown_total} |".format(**row)
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- A selected transient in a negative sample is a false positive.",
            "- A positive is counted correct only when the selected time is within the stated tolerance of the human contact time.",
            "- This report is a calibration baseline. Production auditing must not use a rule until its false-positive behavior is acceptable.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate contact-audio candidate rules on the manual flyball calibration set."
    )
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=24)
    parser.add_argument("--tolerance", type=float, default=0.15)
    args = parser.parse_args()

    evidence = load_evidence(
        args.truth,
        args.dataset_root,
        candidate_limit=args.candidate_limit,
    )
    rows = candidate_rows(evidence, tolerance=args.tolerance)
    rule_results = [
        evaluate_rule(rule, evidence, tolerance=args.tolerance)
        for rule in build_rules()
    ]
    write_csv(args.output_dir / "contact_candidate_evidence.csv", rows)
    write_csv(args.output_dir / "contact_rule_baselines.csv", rule_results)
    write_report(
        args.output_dir / "contact_calibration_baseline.md",
        evidence,
        rows,
        rule_results,
        tolerance=args.tolerance,
    )
    print(
        json.dumps(
            {
                "samples": len(evidence),
                "positive": sum(item.truth == POSITIVE_TRUTH for item in evidence),
                "negative": sum(item.truth in NEGATIVE_TRUTHS for item in evidence),
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
