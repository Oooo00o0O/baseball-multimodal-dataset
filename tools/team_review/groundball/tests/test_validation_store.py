from __future__ import annotations

import csv
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_DIR))

from contracts import REVIEW_SCHEMA_VERSION  # noqa: E402
from validation_store import (  # noqa: E402
    ReviewValidationError,
    ValidationStore,
)


def manifest_row(audit_id: str, position: int) -> dict[str, str]:
    return {
        "schema_version": "contact-audit-manifest-v1",
        "audit_id": audit_id,
        "uid": f"uid__{audit_id}",
        "sample_id": f"G_{position:04d}",
        "sample_relpath": f"dataset/{audit_id}",
        "event_start": "0.9",
        "event_end": "1.1",
        "auto_hit_time": "1.0",
        "audio_duration_sec": "3.0",
    }


class ValidationStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.results = root / "groundball_validation_reviews.csv"
        self.legacy = root / "contact_audit_reviews.csv"
        self.manifest = [manifest_row("A1", 1), manifest_row("A2", 2)]
        self.queue = [
            {"audit_id": "A1", "queue_position": "1"},
            {"audit_id": "A2", "queue_position": "2"},
        ]
        with self.legacy.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "review_schema_version",
                    "audit_id",
                    "review_status",
                    "material_reason",
                    "auto_hit_time",
                    "hit_time_override",
                    "effective_hit_time",
                    "effective_hit_source",
                    "notes",
                    "reviewed_at_utc",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "review_schema_version": "contact-audit-review-v1",
                    "audit_id": "A1",
                    "review_status": "no_contact",
                    "auto_hit_time": "1.0",
                    "notes": "legacy note",
                    "reviewed_at_utc": "2026-07-28T00:00:00+00:00",
                }
            )
        self.legacy_hash = hashlib.sha256(self.legacy.read_bytes()).hexdigest()
        self.store = ValidationStore(
            self.results,
            self.legacy,
            self.manifest,
            self.queue,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_legacy_row_is_viewable_and_counts_as_visited(self) -> None:
        self.assertEqual("legacy", self.store.state_for("A1"))
        self.assertEqual("no_contact", self.store.get_legacy("A1")["review_status"])
        self.assertEqual(1, self.store.summary()["visited"])
        self.assertEqual(1, self.store.summary()["remaining"])
        self.assertFalse(self.results.exists())

    def test_new_save_on_legacy_does_not_modify_old_csv(self) -> None:
        record = self.store.upsert(
            "A1",
            {
                "reviewer_id": "reviewer01",
                "conclusion": "I",
                "contains_contact": "N",
                "original_time_correct": "N",
                "full_process": "N",
                "replay": "N",
                "error_codes": ["E01"],
                "notes": "视频中没有击球事件。",
            },
        )
        self.assertEqual(REVIEW_SCHEMA_VERSION, record["review_schema_version"])
        self.assertEqual("no_contact", record["legacy_review_status"])
        self.assertEqual("current", self.store.state_for("A1"))
        self.assertEqual(
            self.legacy_hash,
            hashlib.sha256(self.legacy.read_bytes()).hexdigest(),
        )

    def test_valid_record_can_accept_proposed_time_without_manual_input(self) -> None:
        record = self.store.upsert(
            "A2",
            {
                "reviewer_id": "reviewer01",
                "conclusion": "V",
                "contains_contact": "Y",
                "original_time_correct": "Y",
                "full_process": "Y",
                "replay": "N",
            },
        )
        self.assertEqual(1.0, record["effective_contact_time"])
        self.assertEqual("accepted_proposal", record["contact_time_source"])
        self.assertTrue(record["counts_toward_quota"])

    def test_reviewer_id_is_optional_and_saved_blank(self) -> None:
        record = self.store.upsert(
            "A2",
            {
                "conclusion": "V",
                "contains_contact": "Y",
                "original_time_correct": "Y",
                "full_process": "Y",
                "replay": "N",
            },
        )
        self.assertEqual("", record["reviewer_id"])

    def test_no_contact_requires_e01_but_not_e02(self) -> None:
        with self.assertRaises(ReviewValidationError):
            self.store.upsert(
                "A2",
                {
                    "reviewer_id": "reviewer01",
                    "conclusion": "I",
                    "contains_contact": "N",
                    "original_time_correct": "N",
                    "full_process": "N",
                    "replay": "N",
                    "error_codes": ["E02"],
                    "notes": "没有击球。",
                },
            )
        saved = self.store.upsert(
            "A2",
            {
                "reviewer_id": "reviewer01",
                "conclusion": "I",
                "contains_contact": "N",
                "original_time_correct": "N",
                "full_process": "N",
                "replay": "N",
                "error_codes": ["E01"],
            },
        )
        self.assertEqual("E01", saved["error_codes"])
        self.assertEqual("", saved["notes"])

    def test_e10_also_allows_empty_notes(self) -> None:
        saved = self.store.upsert(
            "A2",
            {
                "conclusion": "I",
                "contains_contact": "Y",
                "original_time_correct": "Y",
                "full_process": "Y",
                "replay": "N",
                "error_codes": ["E10"],
            },
        )
        self.assertEqual("E10", saved["error_codes"])
        self.assertEqual("", saved["notes"])

    def test_present_contact_with_wrong_time_requires_e02_and_correct_time(self) -> None:
        payload = {
            "reviewer_id": "reviewer01",
            "conclusion": "I",
            "contains_contact": "Y",
            "original_time_correct": "N",
            "full_process": "Y",
            "replay": "N",
            "error_codes": ["E02"],
            "notes": "原时间明显偏早。",
        }
        with self.assertRaises(ReviewValidationError):
            self.store.upsert("A2", payload)
        payload["correct_contact_time"] = 1.25
        saved = self.store.upsert("A2", payload)
        self.assertEqual(1.25, saved["effective_contact_time"])
        self.assertEqual("human_correction", saved["contact_time_source"])

    def test_discard_requires_reason_and_is_excluded_from_formal_export(self) -> None:
        with self.assertRaises(ReviewValidationError):
            self.store.upsert(
                "A2",
                {"reviewer_id": "reviewer01", "conclusion": "D"},
            )
        self.store.upsert(
            "A2",
            {
                "reviewer_id": "reviewer01",
                "conclusion": "D",
                "notes": "画面太糊，无法可靠判断。",
            },
        )
        self.assertEqual(0, self.store.summary()["formal_reviewed"])
        self.assertEqual(1, self.store.summary()["discarded"])
        formal = self.store.export_bytes(formal_only=True).decode("utf-8-sig")
        audit = self.store.export_bytes(formal_only=False).decode("utf-8-sig")
        self.assertNotIn("A2", formal)
        self.assertIn("A2", audit)

    def test_overwrite_reloads_without_duplicate(self) -> None:
        payload = {
            "reviewer_id": "reviewer01",
            "conclusion": "V",
            "contains_contact": "Y",
            "original_time_correct": "Y",
            "full_process": "Y",
            "replay": "N",
        }
        self.store.upsert("A2", payload)
        payload.update(
            {
                "conclusion": "I",
                "original_time_correct": "N",
                "error_codes": ["E02"],
                "correct_contact_time": 1.2,
                "notes": "原时间偏早。",
            }
        )
        self.store.upsert("A2", payload)
        with self.results.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(1, len(rows))
        reloaded = ValidationStore(
            self.results,
            self.legacy,
            self.manifest,
            self.queue,
        )
        self.assertEqual("I", reloaded.get("A2")["conclusion"])


if __name__ == "__main__":
    unittest.main()
