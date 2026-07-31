from __future__ import annotations

import argparse
import csv
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


OFFSETS = (-0.24, -0.16, -0.08, 0.0, 0.08, 0.16, 0.24)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_wav_excerpt(source: Path, destination: Path, center: float, radius: float) -> tuple[float, float]:
    with wave.open(str(source), "rb") as reader:
        rate = reader.getframerate()
        start = max(0.0, center - radius)
        end = min(reader.getnframes() / rate, center + radius)
        reader.setpos(round(start * rate))
        frames = reader.readframes(round((end - start) * rate))
        params = reader.getparams()
    with wave.open(str(destination), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)
    return start, end


def wav_duration(source: Path) -> float:
    with wave.open(str(source), "rb") as reader:
        return reader.getnframes() / reader.getframerate()


def extract_frame(ffmpeg: str, video: Path, time_seconds: float, output: Path) -> None:
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, time_seconds):.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(output),
        ],
        check=True,
        timeout=120,
    )


def build_sheet(frames: list[tuple[Path, float]], output: Path) -> None:
    tile_width, tile_height, label_height = 320, 180, 26
    sheet = Image.new("RGB", (tile_width * 3, (tile_height + label_height) * 3), "black")
    draw = ImageDraw.Draw(sheet)
    for index, (frame_path, time_seconds) in enumerate(frames):
        image = Image.open(frame_path).convert("RGB")
        image.thumbnail((tile_width, tile_height))
        x = (index % 3) * tile_width
        y = (index // 3) * (tile_height + label_height)
        sheet.paste(image, (x + (tile_width - image.width) // 2, y))
        draw.text((x + 5, y + tile_height + 5), f"t={time_seconds:.3f}s", fill="white")
    sheet.save(output, quality=92)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build original-media visual and audio evidence for contact candidates.")
    parser.add_argument("--input-summary", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help="Resolve video.mp4/audio.wav by sample_id for calibration prediction CSVs.",
    )
    parser.add_argument(
        "--outcome",
        action="append",
        default=[],
        help="For calibration prediction CSVs, include only these outcomes (for example fp).",
    )
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--audio-radius", type=float, default=0.8)
    args = parser.parse_args()

    requested = set(args.sample_id)
    input_rows = read_rows(args.input_summary)
    is_calibration_predictions = bool(input_rows and "outcome" in input_rows[0])
    if is_calibration_predictions:
        if not args.dataset_root:
            raise ValueError(
                "--dataset-root is required for calibration prediction CSVs"
            )
        outcomes = set(args.outcome)
        rows = [
            row
            for row in input_rows
            if row.get("selected") == "yes"
            and row.get("selected_candidate_time")
            and (not outcomes or row.get("outcome") in outcomes)
            and (not requested or row["sample_id"] in requested)
        ]
    else:
        rows = [
            row
            for row in input_rows
            if row.get("binding_status") == "audio_candidate_bound"
            and row.get("selected_candidate_time")
            and (not requested or row["sample_id"] in requested)
        ]
    if args.limit:
        rows = rows[: args.limit]

    manifest: list[dict[str, str]] = []
    for row in rows:
        sample_id = row["sample_id"]
        if is_calibration_predictions:
            matches = sorted(args.dataset_root.rglob(f"{sample_id}/audio.wav"))
            if len(matches) != 1:
                raise ValueError(
                    f"expected one dataset audio for {sample_id}, found {len(matches)}"
                )
            sample_dir = matches[0].parent
            video = sample_dir / "video.mp4"
            audio = sample_dir / "audio.wav"
        else:
            video = Path(row["media_video_path"])
            audio = Path(row["media_audio_path"])
        center = float(row["selected_candidate_time"])
        destination = args.output_root / sample_id
        frames_dir = destination / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        duration = wav_duration(audio)
        frame_items: list[tuple[Path, float]] = []
        for index, offset in enumerate(OFFSETS):
            frame_time = min(
                max(0.0, center + offset),
                max(0.0, duration - 0.15),
            )
            frame_path = frames_dir / f"{index + 1:02d}_{frame_time:.3f}.jpg"
            extract_frame(args.ffmpeg, video, frame_time, frame_path)
            frame_items.append((frame_path, frame_time))
        sheet = destination / "contact_sheet.jpg"
        build_sheet(frame_items, sheet)
        overview_frames_dir = destination / "overview_frames"
        overview_frames_dir.mkdir(parents=True, exist_ok=True)
        overview_items: list[tuple[Path, float]] = []
        for index, overview_time in enumerate(
            np.linspace(0.0, max(0.0, duration * 8.0 / 9.0), 9)
        ):
            frame_path = (
                overview_frames_dir / f"{index + 1:02d}_{overview_time:.3f}.jpg"
            )
            extract_frame(args.ffmpeg, video, float(overview_time), frame_path)
            overview_items.append((frame_path, float(overview_time)))
        overview_sheet = destination / "overview_sheet.jpg"
        build_sheet(overview_items, overview_sheet)
        wav_excerpt = destination / "audio_candidate_window.wav"
        audio_start, audio_end = write_wav_excerpt(audio, wav_excerpt, center, args.audio_radius)
        manifest.append(
            {
                "sample_id": sample_id,
                "main_relative_path": row.get("main_relative_path", ""),
                "candidate_time": f"{center:.3f}",
                "frame_offsets": ";".join(f"{value:+.2f}" for value in OFFSETS),
                "contact_sheet": str(sheet),
                "overview_sheet": str(overview_sheet),
                "audio_excerpt": str(wav_excerpt),
                "audio_start": f"{audio_start:.3f}",
                "audio_end": f"{audio_end:.3f}",
                "full_clip_model": row.get("model", ""),
                "full_clip_visual_contact": row.get("visual_contact_time", ""),
                "full_clip_evidence": row.get("visual_evidence", ""),
                "calibration_outcome": row.get("outcome", ""),
                "calibration_truth": row.get("contact_truth", ""),
            }
        )
        print(f"built {sample_id}", flush=True)

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest[0]) if manifest else ["sample_id"])
        writer.writeheader()
        writer.writerows(manifest)
    print(f"evidence_samples={len(manifest)}")


if __name__ == "__main__":
    main()
