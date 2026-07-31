from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_FIELDS = [
    "repair_batch",
    "repair_batch_index",
    "collector",
    "sample_id",
    "main_relative_path",
    "primary_error",
    "source_path",
    "source_duration",
    "source_clip_start",
    "sample_contact_time_used",
    "source_contact_time",
    "new_clip_start",
    "new_clip_end",
    "new_duration",
    "new_event_start",
    "new_event_end",
    "pre_contact_seconds",
    "post_contact_seconds",
    "video_path",
    "audio_path",
    "status",
    "notes",
]


def as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in MANIFEST_FIELDS})


def probe_duration(path: Path, ffprobe: str) -> float | None:
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


def run_extract(
    source: Path,
    start: float,
    end: float,
    video: Path,
    audio: Path,
    ffmpeg: str,
) -> None:
    output_dir = video.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    duration = end - start
    video_command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        "scale=-2:min(720\\,ih)",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "19",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        "-y",
        str(video),
    ]
    audio_command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        "-y",
        str(audio),
    ]
    subprocess.run(video_command, check=True, timeout=300)
    subprocess.run(audio_command, check=True, timeout=300)


def choose_sample_contact(row: dict[str, str]) -> float:
    assessment = row.get("event_audio_assessment", "")
    if assessment in {
        "likely_contact_timestamp_wrong",
        "annotated_audio_ambiguous",
    }:
        suggested = as_float(row.get("suggested_contact_time"))
        if suggested is not None:
            return suggested
    transient = as_float(row.get("annotated_transient_time"))
    if transient is not None:
        return transient
    start = as_float(row.get("current_event_start"))
    end = as_float(row.get("current_event_end"))
    if start is None or end is None:
        raise ValueError("sample has no usable contact time")
    return (start + end) / 2.0


def process_row(
    row: dict[str, str],
    *,
    output_root: Path,
    ffmpeg: str,
    ffprobe: str,
    pre_roll: float,
    post_roll: float,
    min_pre: float,
    min_post: float,
    overwrite: bool,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "repair_batch": row.get("repair_batch", ""),
        "repair_batch_index": row.get("repair_batch_index", ""),
        "collector": row.get("collector", ""),
        "sample_id": row.get("sample_id", ""),
        "main_relative_path": row.get("main_relative_path", ""),
        "primary_error": row.get("primary_error", ""),
        "source_path": row.get("resolved_source_path") or row.get("source_path", ""),
        "source_duration": "",
        "source_clip_start": row.get("source_clip_start", ""),
        "sample_contact_time_used": "",
        "source_contact_time": "",
        "new_clip_start": "",
        "new_clip_end": "",
        "new_duration": "",
        "new_event_start": "",
        "new_event_end": "",
        "pre_contact_seconds": "",
        "post_contact_seconds": "",
        "video_path": "",
        "audio_path": "",
        "status": "",
        "notes": "",
    }
    source = Path(base["source_path"])
    if not source.is_file():
        return {**base, "status": "source_missing", "notes": "Resolved source file is unavailable."}
    source_duration = probe_duration(source, ffprobe)
    if source_duration is None:
        return {**base, "status": "source_unreadable", "notes": "ffprobe could not read source duration."}
    try:
        sample_contact = choose_sample_contact(row)
    except ValueError as exc:
        return {**base, "status": "contact_time_missing", "notes": str(exc)}
    source_clip_start = as_float(row.get("source_clip_start")) or 0.0
    source_contact = source_clip_start + sample_contact
    clip_start = max(0.0, source_contact - pre_roll)
    clip_end = min(source_duration, source_contact + post_roll)
    pre_context = source_contact - clip_start
    post_context = clip_end - source_contact
    new_event_mid = source_contact - clip_start
    new_event_start = max(0.0, new_event_mid - 0.05)
    new_event_end = min(clip_end - clip_start, new_event_mid + 0.05)
    output_dir = output_root / row["collector"] / row["sample_id"]
    video_path = output_dir / "video.mp4"
    audio_path = output_dir / "audio.wav"
    record = {
        **base,
        "source_duration": f"{source_duration:.3f}",
        "source_clip_start": f"{source_clip_start:.3f}",
        "sample_contact_time_used": f"{sample_contact:.3f}",
        "source_contact_time": f"{source_contact:.3f}",
        "new_clip_start": f"{clip_start:.3f}",
        "new_clip_end": f"{clip_end:.3f}",
        "new_duration": f"{clip_end - clip_start:.3f}",
        "new_event_start": f"{new_event_start:.3f}",
        "new_event_end": f"{new_event_end:.3f}",
        "pre_contact_seconds": f"{pre_context:.3f}",
        "post_contact_seconds": f"{post_context:.3f}",
        "video_path": str(video_path.resolve()),
        "audio_path": str(audio_path.resolve()),
    }
    context_complete = pre_context + 0.05 >= min_pre and post_context + 0.05 >= min_post
    if video_path.is_file() and audio_path.is_file() and not overwrite:
        status = "recut_complete" if context_complete else "recut_partial_context"
        return {**record, "status": status, "notes": "Existing non-destructive recut retained."}
    try:
        run_extract(source, clip_start, clip_end, video_path, audio_path, ffmpeg)
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            **record,
            "status": "extraction_failed",
            "notes": f"{type(exc).__name__}: {exc}",
        }
    output_video_duration = probe_duration(video_path, ffprobe)
    if output_video_duration is None or not audio_path.is_file():
        return {
            **record,
            "status": "output_unreadable",
            "notes": "Generated media failed the immediate readability check.",
        }
    status = "recut_complete" if context_complete else "recut_partial_context"
    notes = (
        "Meets minimum context."
        if context_complete
        else "Source boundary prevents minimum context; review only."
    )
    return {**record, "status": status, "notes": notes}


def main() -> int:
    parser = argparse.ArgumentParser(description="Non-destructively recut one fly-ball repair batch.")
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--pre-roll", type=float, default=2.0)
    parser.add_argument("--post-roll", type=float, default=12.0)
    parser.add_argument("--min-pre", type=float, default=1.0)
    parser.add_argument("--min-post", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    rows = [
        row
        for row in read_rows(args.queue)
        if "recover_source_and_recut" in row.get("required_actions", "")
    ]
    if args.sample_id:
        requested = set(args.sample_id)
        rows = [row for row in rows if row["sample_id"] in requested]
    if args.limit:
        rows = rows[: args.limit]
    args.output_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(
                process_row,
                row,
                output_root=args.output_root,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
                pre_roll=args.pre_roll,
                post_roll=args.post_roll,
                min_pre=args.min_pre,
                min_post=args.min_post,
                overwrite=args.overwrite,
            )
            for row in rows
        ]
        for completed, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            records.append(record)
            print(
                json.dumps(
                    {
                        "completed": completed,
                        "total": len(rows),
                        "sample_id": record["sample_id"],
                        "status": record["status"],
                    }
                ),
                flush=True,
            )
    records.sort(key=lambda row: int(row["repair_batch_index"]))
    write_csv(args.manifest, records)
    counts = Counter(row["status"] for row in records)
    print(json.dumps({"samples": len(records), "status_counts": dict(counts)}))
    return 0 if not any(status.endswith("failed") for status in counts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
