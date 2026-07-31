from __future__ import annotations

import csv
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_DIR))

from legacy_bridge import (  # noqa: E402
    combined_records,
    combined_summary,
    export_bytes,
)
from validation_store import ValidationStore  # noqa: E402


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


class LegacyBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.results = root / "groundball_validation_reviews.csv"
        self.legacy = root / "contact_audit_reviews.csv"
        self.manifest = [
            manifest_row("PASS", 1),
            manifest_row("FIXED", 2),
            manifest_row("NONE", 3),
            manifest_row("NEW", 4),
        ]
        self.manifest_by_id = {
            row["audit_id"]: row for row in self.manifest
        }
        self.queue = [
            {"audit_id": row["audit_id"], "queue_position": str(index)}
            for index, row in enumerate(self.manifest, start=1)
        ]
        with self.legacy.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
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
            writer.writerows(
                [
                    {
                        "review_schema_version": "contact-audit-review-v1",
                        "audit_id": "PASS",
                        "review_status": "pass",
                        "auto_hit_time": "1.0",
                        "effective_hit_time": "1.0",
                        "effective_hit_source": "automatic",
                        "notes": "echo",
                        "reviewed_at_utc": "2026-07-28T00:00:00+00:00",
                    },
                    {
                        "review_schema_version": "contact-audit-review-v1",
                        "audit_id": "FIXED",
                        "review_status": "corrected_pass",
                        "auto_hit_time": "1.0",
                        "hit_time_override": "1.25",
                        "effective_hit_time": "1.25",
                        "effective_hit_source": "human_override",
                        "reviewed_at_utc": "2026-07-28T00:01:00+00:00",
                    },
                    {
                        "review_schema_version": "contact-audit-review-v1",
                        "audit_id": "NONE",
                        "review_status": "no_contact",
                        "auto_hit_time": "1.0",
                        "reviewed_at_utc": "2026-07-28T00:02:00+00:00",
                    },
                ]
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

    def records(self) -> list[dict[str, object]]:
        return combined_records(
            store=self.store,
            manifest_by_id=self.manifest_by_id,
            queue_rows=self.queue,
        )

    def test_maps_all_three_legacy_statuses_to_owner_fields(self) -> None:
        records = {row["audit_id"]: row for row in self.records()}

        passed = records["PASS"]
        self.assertEqual("V", passed["conclusion"])
        self.assertEqual("Y", passed["contains_contact"])
        self.assertEqual("Y", passed["original_time_correct"])
        self.assertEqual("Y", passed["full_process"])
        self.assertEqual("N", passed["replay"])
        self.assertEqual("", passed["error_codes"])
        self.assertEqual("echo", passed["notes"])

        corrected = records["FIXED"]
        self.assertEqual("I", corrected["conclusion"])
        self.assertEqual("E02", corrected["error_codes"])
        self.assertEqual(1.25, corrected["correct_contact_time"])
        self.assertEqual("N", corrected["original_time_correct"])
        self.assertEqual("", corrected["notes"])

        absent = records["NONE"]
        self.assertEqual("I", absent["conclusion"])
        self.assertEqual("E01", absent["error_codes"])
        self.assertEqual("N", absent["contains_contact"])
        self.assertIsNone(absent["effective_contact_time"])
        self.assertEqual("", absent["notes"])

    def test_combined_export_includes_legacy_and_new_rows(self) -> None:
        self.store.upsert(
            "NEW",
            {
                "reviewer_id": "reviewer01",
                "conclusion": "V",
                "contains_contact": "Y",
                "original_time_correct": "Y",
                "full_process": "Y",
                "replay": "N",
            },
        )
        records = self.records()
        exported = export_bytes(records, formal_only=True).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(exported)))
        self.assertEqual(4, len(rows))
        self.assertEqual(
            {"PASS", "FIXED", "NONE", "NEW"},
            {row["audit_id"] for row in rows},
        )
        summary = combined_summary(records)
        self.assertEqual(4, summary["export_formal_reviewed"])
        self.assertEqual(3, summary["legacy_mapped_total"])

    def test_new_row_overrides_same_legacy_sample_in_export(self) -> None:
        self.store.upsert(
            "NONE",
            {
                "reviewer_id": "reviewer01",
                "conclusion": "V",
                "contains_contact": "Y",
                "original_time_correct": "Y",
                "full_process": "Y",
                "replay": "N",
            },
        )
        records = [row for row in self.records() if row["audit_id"] == "NONE"]
        self.assertEqual(1, len(records))
        self.assertEqual("V", records[0]["conclusion"])
        self.assertEqual("reviewer01", records[0]["reviewer_id"])
        self.assertEqual(
            self.legacy_hash,
            hashlib.sha256(self.legacy.read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
