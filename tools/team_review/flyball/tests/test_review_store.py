from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
MODULE_DIR = HERE.parents[1]
sys.path.insert(0, str(MODULE_DIR))

from review_store import ReviewStore, ReviewValidationError  # noqa: E402


def admin_row() -> dict[str, str]:
    return {
        "audit_id": "FBTEST00001",
        "uid": "fly_ball__portable_team_review__F_0001",
        "sample_id": "F_0001",
        "sample_relpath": "data/snapshot/dataset/fly_ball/F_0001",
        "event_start": "0.925",
        "event_end": "1.025",
        "proposed_contact_time": "0.981",
        "audio_duration_sec": "12.995",
        "recorded_trajectory": "fly",
    }


def queue_row() -> dict[str, str]:
    return {
        "audit_id": "FBTEST00001",
        "queue_position": "1",
        "batch_number": "1",
        "batch_position": "1",
    }


def valid_payload() -> dict[str, object]:
    return {
        "reviewer_id": "reviewer01",
        "conclusion": "V",
        "original_time_correct": "Y",
        "contact_time": 0.981,
        "sound": "Y",
        "picture": "Y",
        "full_process": "Y",
        "replay": "N",
        "trajectory": "fly",
        "error_codes": [],
        "notes": "",
    }


class ReviewStoreTests(unittest.TestCase):
    def make_store(self, directory: str) -> ReviewStore:
        return ReviewStore(
            Path(directory) / "reviews.csv",
            [admin_row()],
            [queue_row()],
        )

    def test_valid_review_saves_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            saved = store.upsert("FBTEST00001", valid_payload())
            self.assertEqual(saved["conclusion"], "V")
            self.assertEqual(saved["contact_time_source"], "accepted_proposal")
            reloaded = self.make_store(directory)
            self.assertEqual(reloaded.get("FBTEST00001")["reviewer_id"], "reviewer01")

    def test_invalid_requires_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            payload = valid_payload()
            payload.update(
                {
                    "conclusion": "I",
                    "sound": "N",
                    "contact_time": None,
                }
            )
            with self.assertRaisesRegex(ReviewValidationError, "错误代码"):
                store.upsert("FBTEST00001", payload)

    def test_no_sound_requires_e01(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            payload = valid_payload()
            payload.update(
                {
                    "conclusion": "I",
                    "sound": "N",
                    "contact_time": None,
                    "error_codes": ["E11"],
                    "notes": "只有其他噪声",
                }
            )
            with self.assertRaisesRegex(ReviewValidationError, "E01"):
                store.upsert("FBTEST00001", payload)

    def test_uncertain_requires_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            payload = valid_payload()
            payload.update(
                {
                    "conclusion": "U",
                    "original_time_correct": "U",
                    "sound": "U",
                    "picture": "U",
                    "full_process": "U",
                    "replay": "U",
                    "trajectory": "unknown",
                    "contact_time": None,
                }
            )
            with self.assertRaisesRegex(ReviewValidationError, "备注"):
                store.upsert("FBTEST00001", payload)

    def test_upsert_replaces_current_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(directory)
            store.upsert("FBTEST00001", valid_payload())
            payload = valid_payload()
            payload["contact_time"] = 1.001
            store.upsert("FBTEST00001", payload)
            with (Path(directory) / "reviews.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["contact_time"], "1.001")
            self.assertEqual(rows[0]["contact_time_source"], "human_override")


if __name__ == "__main__":
    unittest.main()
