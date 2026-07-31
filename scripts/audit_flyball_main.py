from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import wave
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit("This audit requires numpy.") from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = ("video.mp4", "audio.wav", "label.txt", "sample.csv", "source.txt")
VALID_TRAJECTORIES = {"fly", "line_drive", "pop_fly"}
REPLAY_RE = re.compile(
    r"\b(replay|slow[- ]?motion|slo[- ]?mo|super slow|highlight replay)\b",
    re.IGNORECASE,
)
EXPLICIT_FLY_RE = re.compile(
    r"flies[- ]out|fly[- ]ball|sacrifice[- ]fly|sac[- ]fly|line[- ]drive|"
    r"lines[- ]out|pop[- ]fly|pops[- ]out|home[- ]run|homers|"
    r"diving[- ]catch|running[- ]catch",
    re.IGNORECASE,
)


def sample_number(name: str) -> int:
    match = re.fullmatch(r"F_(\d+)", name)
    return int(match.group(1)) if match else 10**9


def discover_samples(dataset_root: Path) -> list[Path]:
    samples = [
        sample
        for collector in dataset_root.iterdir()
        if collector.is_dir()
        for sample in collector.iterdir()
        if sample.is_dir() and re.fullmatch(r"F_\d+", sample.name)
    ]
    collector_priority = {"Codex_Workstation": 0}
    return sorted(
        samples,
        key=lambda path: (
            collector_priority.get(path.parent.name, 1),
            sample_number(path.name),
            path.parent.name,
            path.name,
        ),
    )


def read_csv_row(path: Path) -> dict[str, str]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return next(csv.DictReader(handle))


def read_source(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def read_wav_mono(path: Path) -> tuple[np.ndarray, int, float]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        frame_count = wav_file.getnframes()
        payload = wav_file.readframes(frame_count)
    if sample_width != 2:
        raise ValueError(f"expected 16-bit PCM, got sample_width={sample_width}")
    audio = np.frombuffer(payload, dtype="<i2").astype(np.float32)
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    audio /= 32768.0
    return audio, sample_rate, len(audio) / float(sample_rate)


def robust_ratio(values: np.ndarray) -> np.ndarray:
    positive = values[values > 1e-7]
    baseline = float(np.median(positive)) if positive.size else 1e-7
    return values / max(baseline, 1e-7)


def frame_features(
    audio: np.ndarray,
    sample_rate: int,
    frame_ms: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    frame_length = max(32, round(sample_rate * frame_ms / 1000.0))
    usable = len(audio) // frame_length * frame_length
    if usable <= 0:
        raise ValueError("audio is shorter than one analysis frame")
    frames = audio[:usable].reshape(-1, frame_length)
    times = (np.arange(frames.shape[0], dtype=np.float32) + 0.5) * frame_length / sample_rate
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    diffs = np.diff(frames, axis=1)
    diff_rms = np.sqrt(np.mean(diffs * diffs, axis=1) + 1e-12)
    rms_ratio = robust_ratio(rms)
    diff_ratio = robust_ratio(diff_rms)
    score = np.sqrt(np.maximum(rms_ratio, 1.0) * np.maximum(diff_ratio, 1.0))
    return times, rms_ratio, diff_ratio, score


def transient_candidates(
    times: np.ndarray,
    score: np.ndarray,
    *,
    minimum_score: float = 1.65,
    minimum_separation: float = 0.10,
    limit: int = 16,
) -> list[tuple[float, float, int]]:
    if score.size == 0:
        return []
    left = np.r_[score[0], score[:-1]]
    right = np.r_[score[1:], score[-1]]
    peak_indices = np.flatnonzero((score >= left) & (score >= right) & (score >= minimum_score))
    ranked = sorted(peak_indices.tolist(), key=lambda index: float(score[index]), reverse=True)
    selected: list[int] = []
    for index in ranked:
        time_value = float(times[index])
        if all(abs(time_value - float(times[chosen])) >= minimum_separation for chosen in selected):
            selected.append(index)
        if len(selected) >= limit:
            break
    return sorted(
        [(float(times[index]), float(score[index]), index) for index in selected],
        key=lambda item: item[0],
    )


def audio_metrics(
    audio_path: Path,
    event_start: float,
    event_end: float,
    frame_ms: float,
) -> dict[str, Any]:
    audio, sample_rate, duration = read_wav_mono(audio_path)
    times, rms_ratio, diff_ratio, score = frame_features(audio, sample_rate, frame_ms)
    candidates = transient_candidates(times, score)
    event_mid = (event_start + event_end) / 2.0
    event_mask = (times >= event_start - 0.035) & (times <= event_end + 0.035)
    if not np.any(event_mask):
        raise ValueError("no analysis frames overlap the annotated event")
    event_indices = np.flatnonzero(event_mask)
    event_index = int(event_indices[np.argmax(score[event_indices])])
    event_time = float(times[event_index])
    event_score = float(score[event_index])
    event_rms_ratio = float(rms_ratio[event_index])
    event_diff_ratio = float(diff_ratio[event_index])

    nearest = min(candidates, key=lambda item: abs(item[0] - event_mid), default=None)
    ranked = sorted(candidates, key=lambda item: item[1], reverse=True)
    strongest = ranked[0] if ranked else None
    event_has_transient = (
        event_score >= 2.05
        and event_diff_ratio >= 1.55
        and abs(event_time - event_mid)
        <= max(0.11, (event_end - event_start) / 2.0 + 0.045)
    )
    event_is_ambiguous = (
        not event_has_transient
        and event_score >= 1.65
        and event_diff_ratio >= 1.30
    )
    event_half_width = (event_end - event_start) / 2.0
    outside_margin = event_half_width + 0.035
    challenger_ratio = 1.15 if event_has_transient else 1.05
    alternatives = [
        item
        for item in candidates
        if abs(item[0] - event_mid) > outside_margin
        and item[1] >= 2.05
        and item[1] >= event_score * challenger_ratio
    ]
    nearby_alternatives = [
        item for item in alternatives if abs(item[0] - event_mid) <= 0.45
    ]
    alternative = min(
        nearby_alternatives if event_has_transient else alternatives,
        key=lambda item: abs(item[0] - event_mid),
        default=None,
    )
    alternative_is_strong = alternative is not None

    if alternative_is_strong:
        assessment = "likely_contact_timestamp_wrong"
        suggested_time = alternative[0]
    elif event_has_transient:
        assessment = "annotated_contact_audio_confirmed"
        suggested_time = event_time
    elif event_is_ambiguous:
        assessment = "annotated_audio_ambiguous"
        suggested_time = event_time
    else:
        assessment = "contact_audio_missing_or_masked"
        suggested_time = strongest[0] if strongest else None

    candidate_payload = [
        {
            "time": round(time_value, 3),
            "score": round(score_value, 3),
            "rms_ratio": round(float(rms_ratio[index]), 3),
            "diff_ratio": round(float(diff_ratio[index]), 3),
        }
        for time_value, score_value, index in ranked
    ]
    return {
        "audio_duration": duration,
        "sample_rate": sample_rate,
        "event_audio_assessment": assessment,
        "annotated_transient_time": event_time,
        "annotated_transient_score": event_score,
        "annotated_rms_ratio": event_rms_ratio,
        "annotated_diff_ratio": event_diff_ratio,
        "nearest_candidate_time": nearest[0] if nearest else None,
        "nearest_candidate_distance": abs(nearest[0] - event_mid) if nearest else None,
        "strongest_candidate_time": strongest[0] if strongest else None,
        "strongest_candidate_score": strongest[1] if strongest else None,
        "suggested_contact_time": suggested_time,
        "audio_candidates_json": json.dumps(candidate_payload, ensure_ascii=True),
    }


def ffprobe_duration(path: Path, ffprobe_path: str) -> float | None:
    if not path.exists():
        return None
    try:
        completed = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
        return as_float(completed.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None


def resolve_source(
    source_path_text: str,
    search_roots: list[Path],
) -> tuple[str, bool]:
    if not source_path_text:
        return "", False
    source_path = Path(source_path_text.replace("\\", "/"))
    candidates = [source_path] if source_path.is_absolute() else []
    candidates.extend(root / source_path for root in search_roots)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve()), True
    return "", False


def context_requirements(trajectory: str) -> tuple[float, float]:
    if trajectory == "line_drive":
        return 0.8, 4.0
    return 1.0, 8.0


def classify(
    sample: dict[str, str],
    source: dict[str, str],
    metrics: dict[str, Any],
    duration: float | None,
    missing_files: list[str],
) -> tuple[str, str, list[str], list[str]]:
    errors: list[str] = []
    actions: list[str] = []
    trajectory = sample.get("trajectory_type", "")
    event_start = as_float(sample.get("event_start"))
    event_end = as_float(sample.get("event_end"))
    title_text = " ".join(
        [source.get("video_title", ""), source.get("source_id", ""), source.get("clip_id", "")]
    )

    if missing_files:
        errors.append("missing_required_files")
        actions.append("recover_missing_sample_files")
    if sample.get("label") != "fly_ball":
        errors.append("wrong_label_field")
    if trajectory not in VALID_TRAJECTORIES:
        errors.append("invalid_trajectory_type")
    if event_start is None or event_end is None or event_start < 0 or event_end <= event_start:
        errors.append("invalid_event_interval")
    elif event_end - event_start > 0.20:
        errors.append("event_window_too_wide")

    assessment = metrics.get("event_audio_assessment", "audio_unreadable")
    if assessment == "audio_unreadable":
        errors.append("audio_unreadable")
        actions.append("recover_audio_and_recheck")
    elif assessment == "likely_contact_timestamp_wrong":
        errors.append("contact_timestamp_wrong")
        actions.extend(["retime_from_local_audio_candidate", "qwen_confirm_visual_contact_near_candidate"])
    elif assessment == "annotated_audio_ambiguous":
        errors.append("contact_audio_ambiguous")
        actions.extend(["review_local_audio_candidates", "qwen_confirm_visual_contact_near_candidate"])
    elif assessment == "contact_audio_missing_or_masked":
        errors.append("contact_audio_missing_or_masked")
        actions.extend(["recover_source_and_recut", "redetect_contact_audio"])

    contact_time = as_float(metrics.get("suggested_contact_time"))
    if contact_time is None and event_start is not None and event_end is not None:
        contact_time = (event_start + event_end) / 2.0
    if duration is None:
        errors.append("video_duration_unreadable")
        actions.append("recover_or_reencode_video")
    elif contact_time is not None:
        required_pre, required_post = context_requirements(trajectory)
        pre_context = contact_time
        post_context = duration - contact_time
        if pre_context < required_pre:
            errors.append("insufficient_pre_contact_context")
        if post_context < required_post:
            errors.append("insufficient_post_contact_context")
        if pre_context < required_pre or post_context < required_post:
            actions.append("recover_source_and_recut_longer")

    if REPLAY_RE.search(title_text):
        errors.append("replay_or_slow_motion_source_text")
        actions.append("qwen_or_manual_replay_review")
    if title_text and not EXPLICIT_FLY_RE.search(title_text):
        errors.append("source_not_explicit_fly")
        actions.append("qwen_confirm_flyball_semantics")

    errors = list(dict.fromkeys(errors))
    actions = list(dict.fromkeys(actions))
    if not errors:
        return "direct_use_candidate", "audio_and_context_pass", errors, ["qwen_spot_check"]

    if "missing_required_files" in errors or "audio_unreadable" in errors:
        category = "missing_or_unreadable_media"
    elif "contact_audio_missing_or_masked" in errors:
        category = "source_recovery_required"
    elif "contact_timestamp_wrong" in errors:
        category = "contact_timestamp_wrong"
    elif "replay_or_slow_motion_source_text" in errors:
        category = "replay_or_slow_motion_review"
    elif (
        "insufficient_pre_contact_context" in errors
        or "insufficient_post_contact_context" in errors
    ):
        category = "clip_too_short"
    elif "contact_audio_ambiguous" in errors:
        category = "audio_candidate_review"
    else:
        category = "semantic_or_schema_review"
    return "needs_edit", category, errors, actions


def format_float(value: Any, digits: int = 3) -> str:
    converted = as_float(value)
    return "" if converted is None else f"{converted:.{digits}f}"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audio-first audit of fly_ball data from main.")
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=REPO_ROOT / "dataset" / "fly_ball",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "reports" / "flyball_main_reclean_20260728" / "audit.csv",
    )
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--frame-ms", type=float, default=10.0)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument(
        "--source-search-root",
        action="append",
        type=Path,
        default=[],
    )
    args = parser.parse_args()

    all_samples = discover_samples(args.dataset_root)
    if args.start_index < 1:
        raise SystemExit("--start-index must be at least 1")
    start = args.start_index - 1
    selected = all_samples[start : start + args.count] if args.count else all_samples[start:]
    search_roots = [REPO_ROOT, *args.source_search_root]
    rows: list[dict[str, Any]] = []

    for local_index, sample_dir in enumerate(selected, start=1):
        global_index = start + local_index
        missing_files = [name for name in REQUIRED_FILES if not (sample_dir / name).is_file()]
        try:
            sample = read_csv_row(sample_dir / "sample.csv")
        except Exception as exc:
            sample = {}
            sample_csv_error = str(exc)
        else:
            sample_csv_error = ""
        source = read_source(sample_dir / "source.txt")
        event_start = as_float(sample.get("event_start"))
        event_end = as_float(sample.get("event_end"))
        metrics: dict[str, Any]
        if event_start is None or event_end is None or not (sample_dir / "audio.wav").is_file():
            metrics = {
                "event_audio_assessment": "audio_unreadable",
                "audio_error": "invalid event interval or missing audio.wav",
            }
        else:
            try:
                metrics = audio_metrics(
                    sample_dir / "audio.wav",
                    event_start,
                    event_end,
                    args.frame_ms,
                )
                metrics["audio_error"] = ""
            except Exception as exc:
                metrics = {
                    "event_audio_assessment": "audio_unreadable",
                    "audio_error": str(exc),
                }

        video_duration = ffprobe_duration(sample_dir / "video.mp4", args.ffprobe)
        if video_duration is None:
            video_duration = as_float(metrics.get("audio_duration"))
            duration_source = "audio_fallback" if video_duration is not None else ""
        else:
            duration_source = "ffprobe"
        resolved_source, source_available = resolve_source(
            source.get("source_path", ""),
            search_roots,
        )
        status, primary_error, errors, actions = classify(
            sample,
            source,
            metrics,
            video_duration,
            missing_files,
        )
        contact_time = as_float(metrics.get("suggested_contact_time"))
        if contact_time is None and event_start is not None and event_end is not None:
            contact_time = (event_start + event_end) / 2.0
        pre_context = contact_time if contact_time is not None else None
        post_context = (
            video_duration - contact_time
            if video_duration is not None and contact_time is not None
            else None
        )

        rows.append(
            {
                "global_index": global_index,
                "collector": sample_dir.parent.name,
                "sample_id": sample_dir.name,
                "main_relative_path": sample_dir.relative_to(REPO_ROOT).as_posix(),
                "id_digits": len(sample_dir.name.split("_", 1)[1]),
                "status": status,
                "primary_error": primary_error,
                "error_types": ";".join(errors),
                "required_actions": ";".join(actions),
                "event_audio_assessment": metrics.get("event_audio_assessment", ""),
                "current_event_start": sample.get("event_start", ""),
                "current_event_end": sample.get("event_end", ""),
                "suggested_contact_time": format_float(metrics.get("suggested_contact_time")),
                "annotated_transient_time": format_float(metrics.get("annotated_transient_time")),
                "annotated_transient_score": format_float(
                    metrics.get("annotated_transient_score")
                ),
                "annotated_rms_ratio": format_float(metrics.get("annotated_rms_ratio")),
                "annotated_diff_ratio": format_float(metrics.get("annotated_diff_ratio")),
                "nearest_candidate_time": format_float(metrics.get("nearest_candidate_time")),
                "nearest_candidate_distance": format_float(
                    metrics.get("nearest_candidate_distance")
                ),
                "strongest_candidate_time": format_float(
                    metrics.get("strongest_candidate_time")
                ),
                "strongest_candidate_score": format_float(
                    metrics.get("strongest_candidate_score")
                ),
                "audio_candidates_json": metrics.get("audio_candidates_json", "[]"),
                "video_duration": format_float(video_duration),
                "duration_source": duration_source,
                "audio_duration": format_float(metrics.get("audio_duration")),
                "pre_contact_context": format_float(pre_context),
                "post_contact_context": format_float(post_context),
                "trajectory_type": sample.get("trajectory_type", ""),
                "landing_zone": sample.get("landing_zone", ""),
                "strength": sample.get("strength", ""),
                "missing_files": ";".join(missing_files),
                "sample_csv_error": sample_csv_error,
                "audio_error": metrics.get("audio_error", ""),
                "video_title": source.get("video_title", ""),
                "video_url": source.get("video_url", ""),
                "source_id": source.get("source_id", ""),
                "source_path": source.get("source_path", ""),
                "source_clip_start": source.get("clip_start_time", ""),
                "source_clip_end": source.get("clip_end_time", ""),
                "resolved_source_path": resolved_source,
                "source_available_locally": "yes" if source_available else "no",
            }
        )

    write_csv(args.output, rows)
    status_counts = Counter(row["status"] for row in rows)
    error_counts = Counter(row["primary_error"] for row in rows)
    audio_counts = Counter(row["event_audio_assessment"] for row in rows)
    source_count = sum(row["source_available_locally"] == "yes" for row in rows)
    print(
        json.dumps(
            {
                "audited": len(rows),
                "first_global_index": rows[0]["global_index"] if rows else None,
                "last_global_index": rows[-1]["global_index"] if rows else None,
                "status_counts": dict(status_counts),
                "primary_error_counts": dict(error_counts),
                "audio_assessment_counts": dict(audio_counts),
                "source_available_locally": source_count,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
