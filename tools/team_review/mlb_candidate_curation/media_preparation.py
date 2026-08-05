"""Bounded official-highlight preparation without altering source audio."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from contact_detector import (
    DETECTOR_VERSION,
    DetectorConfig,
    detect_contacts_from_wav,
)


@dataclass(frozen=True)
class PreparedMedia:
    video_path: Path
    audio_path: Path
    enhanced_audio_path: Path
    duration_sec: float
    inventory_update: dict[str, object]


def read_review_rows(review_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not review_dir.is_dir():
        return rows
    for path in sorted(review_dir.glob("*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows.extend(dict(row) for row in csv.DictReader(handle))
    return rows


def media_directory(media_root: Path, source_play_id: str) -> Path:
    if not source_play_id.strip():
        raise ValueError("source_play_id cannot be blank")
    digest = hashlib.sha256(source_play_id.encode("utf-8")).hexdigest()[:20]
    return media_root.resolve() / digest


def _run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _relative_to_project(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    root = project_root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("prepared media must stay inside the project root")
    return resolved.relative_to(root).as_posix()


class MediaPreparer:
    """Download one matched short highlight and derive review diagnostics."""

    def __init__(
        self,
        project_root: Path,
        media_root: Path,
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        detector_config: DetectorConfig | None = None,
        command_runner: Callable[
            [list[str]], subprocess.CompletedProcess[str]
        ] = _run_checked,
    ) -> None:
        self.project_root = project_root.resolve()
        self.media_root = media_root.resolve()
        if not self.media_root.is_relative_to(self.project_root):
            raise ValueError("media_root must be inside project_root")
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg")
        self.ffprobe = ffprobe or shutil.which("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            raise RuntimeError("FFmpeg and ffprobe are required")
        self.detector_config = detector_config or DetectorConfig()
        self.detector_config.validate()
        self.command_runner = command_runner

    def prepare(
        self,
        row: Mapping[str, object],
        *,
        force_download: bool = False,
        force_analysis: bool = False,
    ) -> PreparedMedia:
        source_play_id = str(row.get("source_play_id") or "").strip()
        source_url = str(row.get("source_mp4_url") or "").strip()
        confidence = str(row.get("media_match_confidence") or "").strip().lower()
        if confidence not in {"high", "medium"}:
            raise ValueError("only high/medium media matches may be prepared")
        if not source_url:
            raise ValueError("candidate has no source_mp4_url")

        directory = media_directory(self.media_root, source_play_id)
        directory.mkdir(parents=True, exist_ok=True)
        video_path = directory / "video.mp4"
        audio_path = directory / "audio_original.wav"
        enhanced_path = directory / "audio_contact_enhanced.wav"
        if force_download or not video_path.is_file() or video_path.stat().st_size == 0:
            self._download(source_url, video_path)
        if force_analysis or not audio_path.is_file():
            self._extract_original_audio(video_path, audio_path)
        if force_analysis or not enhanced_path.is_file():
            self._derive_enhanced_audio(audio_path, enhanced_path)

        duration = self._probe_duration(video_path)
        candidates = detect_contacts_from_wav(
            audio_path,
            self.detector_config,
        )
        update: dict[str, object] = {
            "source_play_id": source_play_id,
            "media_status": "prepared",
            "video_relpath": _relative_to_project(video_path, self.project_root),
            "audio_relpath": _relative_to_project(audio_path, self.project_root),
            "media_duration_sec": duration,
            "detector_version": DETECTOR_VERSION,
            "detector_config": self.detector_config.identity_json(),
        }
        for rank in range(1, 4):
            candidate = candidates[rank - 1] if rank <= len(candidates) else None
            update[f"auto_hit_time_{rank}"] = (
                candidate.time_sec if candidate else ""
            )
            update[f"auto_hit_score_{rank}"] = candidate.score if candidate else ""
        return PreparedMedia(
            video_path=video_path,
            audio_path=audio_path,
            enhanced_audio_path=enhanced_path,
            duration_sec=duration,
            inventory_update=update,
        )

    def _download(self, url: str, destination: Path) -> None:
        temporary = destination.with_suffix(destination.suffix + ".part")
        if temporary.exists():
            temporary.unlink()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "BaseballCandidateCuration/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                with temporary.open("wb") as handle:
                    shutil.copyfileobj(response, handle, length=1024 * 1024)
                    handle.flush()
                    os.fsync(handle.fileno())
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RuntimeError("download produced an empty file")
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _extract_original_audio(self, video_path: Path, audio_path: Path) -> None:
        temporary = audio_path.with_suffix(".tmp.wav")
        try:
            self.command_runner(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(video_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "44100",
                    "-c:a",
                    "pcm_s16le",
                    str(temporary),
                ]
            )
            os.replace(temporary, audio_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _derive_enhanced_audio(self, audio_path: Path, output_path: Path) -> None:
        temporary = output_path.with_suffix(".tmp.wav")
        filter_graph = (
            "highpass=f=1800,lowpass=f=16000,"
            "acompressor=threshold=0.06:ratio=3:attack=2:release=80,volume=2"
        )
        try:
            self.command_runner(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(audio_path),
                    "-af",
                    filter_graph,
                    "-c:a",
                    "pcm_s16le",
                    str(temporary),
                ]
            )
            os.replace(temporary, output_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _probe_duration(self, video_path: Path) -> float:
        completed = self.command_runner(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(video_path),
            ]
        )
        payload = json.loads(completed.stdout)
        duration = float(payload["format"]["duration"])
        if duration <= 0:
            raise RuntimeError("media duration is not positive")
        return round(duration, 6)
