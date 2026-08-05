from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve()
MODULE_DIR = HERE.parents[1]
sys.path.insert(0, str(MODULE_DIR))

from contact_detector import DetectorConfig, detect_contacts  # noqa: E402


def transient_signal(
    sample_rate: int,
    duration: float,
    events: list[tuple[float, float]],
) -> np.ndarray:
    rng = np.random.default_rng(12)
    signal = rng.normal(0.0, 0.001, round(sample_rate * duration))
    width = round(sample_rate * 0.009)
    window = np.hanning(width)
    for time_sec, amplitude in events:
        start = round(time_sec * sample_rate)
        tone = np.sin(2 * np.pi * 4200 * np.arange(width) / sample_rate)
        signal[start : start + width] += amplitude * tone * window
    return signal.astype(np.float32)


class ContactDetectorTests(unittest.TestCase):
    def test_ranks_strongest_transient_first_and_returns_at_most_three(self) -> None:
        sample_rate = 24000
        signal = transient_signal(
            sample_rate,
            4.0,
            [(0.5, 0.25), (1.5, 0.9), (2.5, 0.5), (3.4, 0.2)],
        )
        candidates = detect_contacts(signal, sample_rate)
        self.assertLessEqual(len(candidates), 3)
        self.assertAlmostEqual(candidates[0].time_sec, 1.5, delta=0.03)
        self.assertEqual([item.rank for item in candidates], [1, 2, 3])
        self.assertEqual(candidates[0].score, 1.0)

    def test_spacing_suppresses_nearby_duplicate_peaks(self) -> None:
        sample_rate = 24000
        signal = transient_signal(
            sample_rate,
            2.0,
            [(0.8, 0.8), (0.9, 0.75), (1.5, 0.6)],
        )
        candidates = detect_contacts(
            signal,
            sample_rate,
            DetectorConfig(min_spacing_ms=250.0),
        )
        near_first = [
            item for item in candidates if 0.75 <= item.time_sec <= 1.0
        ]
        self.assertEqual(len(near_first), 1)

    def test_silence_has_no_candidates(self) -> None:
        candidates = detect_contacts(np.zeros(24000), 24000)
        self.assertEqual(candidates, [])

    def test_configuration_identity_is_stable(self) -> None:
        first = DetectorConfig().identity_json()
        second = DetectorConfig().identity_json()
        self.assertEqual(first, second)
        self.assertIn('"mid_band_low_hz": 1800.0', first)


if __name__ == "__main__":
    unittest.main()
