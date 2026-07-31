from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import wave
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def video_duration(path: Path, ffprobe: str) -> float | None:
    try:
        completed = subprocess.run(
            [
                ffprobe,
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
            timeout=60,
        )
        return as_float(completed.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None


def audio_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())
    except (OSError, wave.Error):
        return None


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a fly-ball recut manifest and generated media.")
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--max-duration-delta", type=float, default=0.08)
    args = parser.parse_args()

    queue = [
        row
        for row in read_csv(args.queue)
        if "recover_source_and_recut" in row.get("required_actions", "")
    ]
    manifest = read_csv(args.manifest)
    queue_paths = {row["main_relative_path"] for row in queue}
    manifest_paths = {row["main_relative_path"] for row in manifest}
    duplicate_count = len(manifest) - len(manifest_paths)
    missing_results = sorted(queue_paths - manifest_paths)
    unexpected_results = sorted(manifest_paths - queue_paths)
    validation_rows: list[dict[str, Any]] = []

    for row in manifest:
        errors: list[str] = []
        video_path = Path(row["video_path"]) if row.get("video_path") else Path()
        audio_path = Path(row["audio_path"]) if row.get("audio_path") else Path()
        video_exists = bool(row.get("video_path")) and video_path.is_file()
        audio_exists = bool(row.get("audio_path")) and audio_path.is_file()
        if not video_exists:
            errors.append("video_missing")
        if not audio_exists:
            errors.append("audio_missing")
        measured_video = video_duration(video_path, args.ffprobe) if video_exists else None
        measured_audio = audio_duration(audio_path) if audio_exists else None
        if video_exists and measured_video is None:
            errors.append("video_unreadable")
        if audio_exists and measured_audio is None:
            errors.append("audio_unreadable")
        duration_delta = (
            abs(measured_video - measured_audio)
            if measured_video is not None and measured_audio is not None
            else None
        )
        if duration_delta is not None and duration_delta > args.max_duration_delta:
            errors.append("audio_video_duration_mismatch")
        event_start = as_float(row.get("new_event_start"))
        event_end = as_float(row.get("new_event_end"))
        duration_limit = measured_audio if measured_audio is not None else measured_video
        if (
            event_start is None
            or event_end is None
            or event_start < 0
            or event_end <= event_start
            or duration_limit is None
            or event_end > duration_limit + 0.02
        ):
            errors.append("event_interval_out_of_bounds")
        if row.get("status") not in {"recut_complete", "recut_partial_context"}:
            errors.append("recut_status_not_reviewable")
        validation_rows.append(
            {
                "repair_batch_index": row.get("repair_batch_index", ""),
                "collector": row.get("collector", ""),
                "sample_id": row.get("sample_id", ""),
                "main_relative_path": row.get("main_relative_path", ""),
                "recut_status": row.get("status", ""),
                "video_exists": "yes" if video_exists else "no",
                "audio_exists": "yes" if audio_exists else "no",
                "video_duration": (
                    f"{measured_video:.3f}" if measured_video is not None else ""
                ),
                "audio_duration": (
                    f"{measured_audio:.3f}" if measured_audio is not None else ""
                ),
                "duration_delta": (
                    f"{duration_delta:.3f}" if duration_delta is not None else ""
                ),
                "event_start": row.get("new_event_start", ""),
                "event_end": row.get("new_event_end", ""),
                "validation_status": "pass" if not errors else "fail",
                "validation_errors": ";".join(errors),
            }
        )

    write_csv(args.output_csv, validation_rows)
    validation_counts = Counter(row["validation_status"] for row in validation_rows)
    recut_counts = Counter(row["recut_status"] for row in validation_rows)
    summary = {
        "queue_recut_rows": len(queue),
        "manifest_rows": len(manifest),
        "duplicates": duplicate_count,
        "missing_results": len(missing_results),
        "missing_result_paths": missing_results,
        "unexpected_results": len(unexpected_results),
        "unexpected_result_paths": unexpected_results,
        "validation_counts": dict(validation_counts),
        "recut_status_counts": dict(recut_counts),
    }
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if (
        duplicate_count == 0
        and not missing_results
        and not unexpected_results
        and validation_counts.get("fail", 0) == 0
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
