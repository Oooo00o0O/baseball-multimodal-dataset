"""Reproducible, label-blind contact proposals from PCM WAV audio."""

from __future__ import annotations

import json
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


DETECTOR_VERSION = "mlb-contact-multiband-v1"


@dataclass(frozen=True)
class DetectorConfig:
    frame_ms: float = 10.0
    hop_ms: float = 2.5
    mid_band_low_hz: float = 1800.0
    mid_band_high_hz: float = 7000.0
    high_band_low_hz: float = 5000.0
    high_band_high_hz: float = 16000.0
    full_weight: float = 0.34
    mid_weight: float = 0.28
    high_weight: float = 0.22
    onset_weight: float = 0.16
    local_window_ms: float = 180.0
    min_spacing_ms: float = 300.0
    max_candidates: int = 3
    edge_guard_ms: float = 80.0

    def validate(self) -> None:
        if self.frame_ms <= 0 or self.hop_ms <= 0:
            raise ValueError("frame_ms and hop_ms must be positive")
        if self.max_candidates < 1 or self.max_candidates > 3:
            raise ValueError("max_candidates must be between 1 and 3")
        if self.min_spacing_ms < 0 or self.edge_guard_ms < 0:
            raise ValueError("spacing and guard durations cannot be negative")
        if self.mid_band_low_hz >= self.mid_band_high_hz:
            raise ValueError("mid-frequency band is invalid")
        if self.high_band_low_hz >= self.high_band_high_hz:
            raise ValueError("high-frequency band is invalid")

    def identity_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class ContactCandidate:
    rank: int
    time_sec: float
    score: float
    full_band: float
    mid_band: float
    high_band: float
    onset: float


def read_pcm_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read mono/stereo PCM WAV as normalized mono float32."""

    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    dtype_by_width = {1: np.uint8, 2: np.int16, 4: np.int32}
    if sample_width not in dtype_by_width:
        raise ValueError(f"unsupported PCM sample width: {sample_width}")
    data = np.frombuffer(frames, dtype=dtype_by_width[sample_width])
    if sample_width == 1:
        signal = (data.astype(np.float32) - 128.0) / 128.0
    else:
        scale = float(2 ** (sample_width * 8 - 1))
        signal = data.astype(np.float32) / scale
    if channels > 1:
        signal = signal.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(signal, dtype=np.float32), sample_rate


def _robust_positive(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    median = float(np.median(values))
    scale = float(np.percentile(values, 99.5) - median)
    if scale <= 1e-12:
        scale = float(np.std(values))
    if scale <= 1e-12:
        return np.zeros_like(values)
    scores = np.maximum((values - median) / scale, 0.0)
    return np.clip(scores, 0.0, 1.0)


def _framed(signal: np.ndarray, frame_length: int, hop_length: int) -> np.ndarray:
    if signal.size < frame_length:
        signal = np.pad(signal, (0, frame_length - signal.size))
    count = 1 + (signal.size - frame_length) // hop_length
    shape = (count, frame_length)
    strides = (signal.strides[0] * hop_length, signal.strides[0])
    return np.lib.stride_tricks.as_strided(
        signal,
        shape=shape,
        strides=strides,
        writeable=False,
    )


def detect_contacts(
    signal: np.ndarray,
    sample_rate: int,
    config: DetectorConfig | None = None,
) -> list[ContactCandidate]:
    """Return at most three ranked transient proposals on the source timeline."""

    config = config or DetectorConfig()
    config.validate()
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    signal = np.asarray(signal, dtype=np.float32).reshape(-1)
    if not signal.size:
        return []

    frame_length = max(32, round(config.frame_ms * sample_rate / 1000.0))
    hop_length = max(1, round(config.hop_ms * sample_rate / 1000.0))
    frames = _framed(signal, frame_length, hop_length)
    window = np.hanning(frame_length).astype(np.float32)
    windowed = frames * window[None, :]
    full_energy = np.sqrt(np.mean(np.square(windowed), axis=1) + 1e-12)
    spectrum = np.abs(np.fft.rfft(windowed, axis=1))
    frequencies = np.fft.rfftfreq(frame_length, d=1.0 / sample_rate)

    def band_energy(low_hz: float, high_hz: float) -> np.ndarray:
        high_hz = min(high_hz, sample_rate / 2.0)
        mask = (frequencies >= low_hz) & (frequencies <= high_hz)
        if not np.any(mask):
            return np.zeros(frames.shape[0], dtype=np.float64)
        return np.sqrt(np.mean(np.square(spectrum[:, mask]), axis=1) + 1e-12)

    mid_energy = band_energy(config.mid_band_low_hz, config.mid_band_high_hz)
    high_energy = band_energy(config.high_band_low_hz, config.high_band_high_hz)
    log_full = np.log1p(full_energy)
    log_mid = np.log1p(mid_energy)
    log_high = np.log1p(high_energy)
    onset = np.maximum(
        np.diff(log_full + 0.6 * log_mid + 0.4 * log_high, prepend=0.0),
        0.0,
    )
    full_score = _robust_positive(log_full)
    mid_score = _robust_positive(log_mid)
    high_score = _robust_positive(log_high)
    onset_score = _robust_positive(onset)
    combined = (
        config.full_weight * full_score
        + config.mid_weight * mid_score
        + config.high_weight * high_score
        + config.onset_weight * onset_score
    )

    local_radius = max(
        1,
        round(config.local_window_ms / config.hop_ms / 2.0),
    )
    local_floor = np.empty_like(combined)
    for index in range(combined.size):
        start = max(0, index - local_radius)
        end = min(combined.size, index + local_radius + 1)
        local_floor[index] = np.median(combined[start:end])
    sharpness = np.maximum(combined - local_floor, 0.0)
    combined = 0.72 * combined + 0.28 * _robust_positive(sharpness)

    times = (
        np.arange(combined.size, dtype=np.float64) * hop_length
        + frame_length / 2.0
    ) / sample_rate
    duration = signal.size / sample_rate
    guard = config.edge_guard_ms / 1000.0
    allowed = (times >= guard) & (times <= max(guard, duration - guard))
    local_maxima = np.ones(combined.size, dtype=bool)
    if combined.size > 2:
        local_maxima[1:-1] = (
            (combined[1:-1] >= combined[:-2])
            & (combined[1:-1] > combined[2:])
        )
    order = np.argsort(combined)[::-1]
    chosen: list[int] = []
    spacing = config.min_spacing_ms / 1000.0
    for index in order:
        if not allowed[index] or not local_maxima[index]:
            continue
        if combined[index] <= 0:
            continue
        if any(abs(times[index] - times[other]) < spacing for other in chosen):
            continue
        chosen.append(int(index))
        if len(chosen) >= config.max_candidates:
            break

    maximum = max((float(combined[index]) for index in chosen), default=1.0)
    results: list[ContactCandidate] = []
    for rank, index in enumerate(chosen, start=1):
        results.append(
            ContactCandidate(
                rank=rank,
                time_sec=round(float(times[index]), 6),
                score=round(float(combined[index]) / maximum, 6),
                full_band=round(float(full_score[index]), 6),
                mid_band=round(float(mid_score[index]), 6),
                high_band=round(float(high_score[index]), 6),
                onset=round(float(onset_score[index]), 6),
            )
        )
    return results


def detect_contacts_from_wav(
    path: Path,
    config: DetectorConfig | None = None,
) -> list[ContactCandidate]:
    signal, sample_rate = read_pcm_wav(path)
    return detect_contacts(signal, sample_rate, config)
