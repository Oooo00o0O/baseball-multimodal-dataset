from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
MODULE_DIR = HERE.parents[1]
sys.path.insert(0, str(MODULE_DIR))

from contracts import (  # noqa: E402
    AUXILIARY_FIELDS,
    AUXILIARY_SCHEMA_VERSION,
    INVENTORY_FIELDS,
    INVENTORY_SCHEMA_VERSION,
    MEDIA_EXCLUSION_FIELDS,
    MEDIA_EXCLUSION_SCHEMA_VERSION,
    REVIEW_FIELDS,
    REVIEW_SCHEMA_VERSION,
)
from stores import (  # noqa: E402
    BatchReviewStore,
    CandidateInventoryStore,
    PrefilteredAuxiliaryStore,
    PrefilteredMediaExclusionStore,
    StoreValidationError,
)


def inventory_row(source_play_id: str = "game-1:atbat-2") -> dict[str, object]:
    return {
        "source_play_id": source_play_id,
        "identity_method": "game_pk_at_bat",
        "game_pk": "1",
        "play_id": "play-2",
        "at_bat_index": "2",
        "game_date": "2026-07-01",
        "game_info": "Away @ Home",
        "batter": "Test Batter",
        "pitcher": "Test Pitcher",
        "mlb_event_raw": "Groundout",
        "play_description": "Test Batter grounds out.",
        "mlb_trajectory_raw": "ground_ball",
        "mlb_location_raw": "4",
        "media_match_confidence": "high",
        "media_match_score": "123",
        "media_match_reason_zh": "比赛、击球手和事件一致",
        "matcher_version": "matcher-v1",
        "media_status": "prepared",
        "video_relpath": "media/game-1/video.mp4",
        "audio_relpath": "media/game-1/audio.wav",
        "media_duration_sec": "21.5",
        "auto_hit_time_1": "4.2",
        "auto_hit_score_1": "0.94",
        "auto_hit_time_2": "8.1",
        "auto_hit_score_2": "0.72",
        "detector_version": "detector-v1",
        "detector_config": '{"bands":["full","mid_high"]}',
    }


def admitted_payload() -> dict[str, object]:
    return {
        "admission_status": "admitted",
        "observed_trajectory": "ground_ball",
        "reviewed_location": "4",
        "location_source": "accepted_official",
        "reviewed_hit_time": "4.2",
        "broken_bat": False,
        "reviewer_id": "",
        "notes": "",
    }


class CandidateInventoryStoreTests(unittest.TestCase):
    def test_upsert_writes_and_reloads_with_stable_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate_inventory.csv"
            store = CandidateInventoryStore(path)
            saved = store.upsert(inventory_row())
            self.assertEqual(saved["inventory_schema_version"], INVENTORY_SCHEMA_VERSION)
            self.assertEqual(saved["media_duration_sec"], 21.5)
            self.assertFalse(path.with_suffix(".csv.tmp").exists())

            reloaded = CandidateInventoryStore(path)
            row = reloaded.get("game-1:atbat-2")
            self.assertEqual(row["auto_hit_time_1"], 4.2)
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, INVENTORY_FIELDS)

    def test_upsert_cannot_overwrite_nonblank_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CandidateInventoryStore(Path(directory) / "inventory.csv")
            store.upsert(inventory_row())
            changed = inventory_row()
            changed["mlb_location_raw"] = "6"
            with self.assertRaises(StoreValidationError):
                store.upsert(changed)

    def test_compound_mlb_raw_location_is_preserved_for_human_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CandidateInventoryStore(Path(directory) / "inventory.csv")
            row = inventory_row()
            row["mlb_location_raw"] = "89"
            saved = store.upsert(row)
            self.assertEqual(saved["mlb_location_raw"], "89")
    def test_partial_upsert_preserves_existing_media_and_source_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CandidateInventoryStore(Path(directory) / "inventory.csv")
            store.upsert(inventory_row())
            saved = store.upsert(
                {
                    "source_play_id": "game-1:atbat-2",
                    "media_status": "preparation_failed",
                }
            )
            self.assertEqual(saved["identity_method"], "game_pk_at_bat")
            self.assertEqual(saved["video_relpath"], "media/game-1/video.mp4")
            self.assertEqual(saved["mlb_location_raw"], "4")
            self.assertEqual(saved["media_status"], "preparation_failed")

    def test_ranked_candidates_must_be_contiguous_and_inside_media(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CandidateInventoryStore(Path(directory) / "inventory.csv")
            row = inventory_row()
            row["auto_hit_time_1"] = ""
            row["auto_hit_score_1"] = ""
            with self.assertRaises(StoreValidationError):
                store.upsert(row)


class PrefilteredAuxiliaryStoreTests(unittest.TestCase):
    def test_structured_foul_is_saved_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefiltered_auxiliary_events.csv"
            store = PrefilteredAuxiliaryStore(path)
            saved = store.upsert(
                {
                    "source_play_id": "game-2:pitch-8",
                    "game_pk": "2",
                    "play_id": "pitch-8",
                    "game_date": "2026-07-02",
                    "batter": "Test Batter",
                    "auxiliary_event_type": "foul_tip",
                    "classification_source": "mlb_structured",
                    "classification_evidence": "details.description=Foul Tip",
                    "mlb_event_raw": "Foul Tip",
                    "play_description": "Foul tip.",
                    "source_page_url": "https://www.mlb.com/video/example",
                    "prefilter_version": "prefilter-v1",
                }
            )
            self.assertEqual(saved["auxiliary_schema_version"], AUXILIARY_SCHEMA_VERSION)
            self.assertNotIn("source_mp4_url", saved)
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, AUXILIARY_FIELDS)

    def test_title_only_classification_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PrefilteredAuxiliaryStore(Path(directory) / "aux.csv")
            with self.assertRaises(StoreValidationError):
                store.upsert(
                    {
                        "source_play_id": "game-2:pitch-9",
                        "auxiliary_event_type": "bunt",
                        "classification_source": "video_title",
                        "classification_evidence": "title contains bunt",
                        "prefilter_version": "prefilter-v1",
                    }
                )


class PrefilteredMediaExclusionStoreTests(unittest.TestCase):
    def test_multi_event_media_is_keyed_by_play_and_video_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefiltered_media_exclusions.csv"
            store = PrefilteredMediaExclusionStore(path)
            saved = store.upsert(
                {
                    "source_play_id": "mlb:2:play:contact",
                    "source_video_id": "batter-four-hit-game",
                    "game_pk": "2",
                    "game_date": "2026-07-02",
                    "batter": "Test Batter",
                    "source_title": "Test Batter's four-hit game",
                    "source_page_url": (
                        "https://www.mlb.com/video/batter-four-hit-game"
                    ),
                    "source_mp4_url": "https://example.invalid/package.mp4",
                    "media_duration_sec": "74.8",
                    "exclusion_reason": "multi_event_title",
                    "matched_pattern": "counted_hits",
                    "matcher_version": "matcher-v2",
                }
            )
            self.assertEqual(
                saved["media_exclusion_schema_version"],
                MEDIA_EXCLUSION_SCHEMA_VERSION,
            )
            self.assertEqual(
                PrefilteredMediaExclusionStore(path).get(
                    "mlb:2:play:contact",
                    "batter-four-hit-game",
                )["matched_pattern"],
                "counted_hits",
            )
            with path.open("r", encoding="utf-8", newline="") as handle:
                self.assertEqual(csv.DictReader(handle).fieldnames, MEDIA_EXCLUSION_FIELDS)


class BatchReviewStoreTests(unittest.TestCase):
    def make_inventory(self, directory: str) -> CandidateInventoryStore:
        store = CandidateInventoryStore(Path(directory) / "inventory.csv")
        store.upsert(inventory_row())
        return store

    def test_admitted_review_derives_labels_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.make_inventory(directory)
            path = Path(directory) / "reviews" / "batch-a.csv"
            store = BatchReviewStore(path, "batch-a", inventory.all())
            saved = store.upsert("game-1:atbat-2", admitted_payload())
            self.assertEqual(saved["review_schema_version"], REVIEW_SCHEMA_VERSION)
            self.assertEqual(saved["derived_ground_fly_label"], "ground_ball")
            self.assertEqual(saved["hit_time_source"], "accepted_proposal")
            self.assertTrue(saved["contact_eligible"])
            self.assertTrue(saved["ground_fly_eligible"])
            self.assertTrue(saved["location_eligible"])
            self.assertEqual(saved["reviewer_id"], "")

            reloaded = BatchReviewStore(path, "batch-a", inventory.all())
            self.assertEqual(
                reloaded.get("game-1:atbat-2")["location_source"],
                "accepted_official",
            )
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, REVIEW_FIELDS)

    def test_location_provenance_is_derived_and_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.make_inventory(directory)
            store = BatchReviewStore(
                Path(directory) / "reviews.csv",
                "batch-a",
                inventory.all(),
            )
            payload = admitted_payload()
            payload["reviewed_location"] = "6"
            payload["location_source"] = "accepted_official"
            with self.assertRaises(StoreValidationError):
                store.upsert("game-1:atbat-2", payload)
            payload["location_source"] = "human_corrected"
            saved = store.upsert("game-1:atbat-2", payload)
            self.assertEqual(saved["location_source"], "human_corrected")

    def test_missing_official_location_can_be_human_filled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = CandidateInventoryStore(Path(directory) / "inventory.csv")
            row = inventory_row("game-3:atbat-4")
            row["game_pk"] = "3"
            row["play_id"] = "play-4"
            row["at_bat_index"] = "4"
            row["mlb_location_raw"] = ""
            inventory.upsert(row)
            store = BatchReviewStore(
                Path(directory) / "reviews.csv",
                "batch-a",
                inventory.all(),
            )
            payload = admitted_payload()
            payload["reviewed_location"] = "7"
            payload["location_source"] = "human_filled"
            saved = store.upsert("game-3:atbat-4", payload)
            self.assertEqual(saved["location_source"], "human_filled")
            self.assertTrue(saved["location_eligible"])

    def test_excluded_review_requires_only_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.make_inventory(directory)
            store = BatchReviewStore(
                Path(directory) / "reviews.csv",
                "batch-a",
                inventory.all(),
            )
            saved = store.upsert(
                "game-1:atbat-2",
                {
                    "admission_status": "excluded",
                    "exclusion_reason": "no_contact",
                },
            )
            self.assertEqual(saved["notes"], "")
            self.assertEqual(saved["reviewer_id"], "")
            self.assertFalse(saved["contact_eligible"])
            self.assertEqual(saved["reviewed_hit_time"], None)

    def test_upsert_replaces_one_current_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.make_inventory(directory)
            path = Path(directory) / "reviews.csv"
            store = BatchReviewStore(path, "batch-a", inventory.all())
            store.upsert(
                "game-1:atbat-2",
                {
                    "admission_status": "excluded",
                    "exclusion_reason": "no_contact",
                },
            )
            store.upsert("game-1:atbat-2", admitted_payload())
            self.assertEqual(store.summary()["reviewed"], 1)
            with path.open("r", encoding="utf-8", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)

    def test_unknown_trajectory_is_not_ground_fly_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory = self.make_inventory(directory)
            store = BatchReviewStore(
                Path(directory) / "reviews.csv",
                "batch-a",
                inventory.all(),
            )
            payload = admitted_payload()
            payload["observed_trajectory"] = "unknown"
            payload["reviewed_location"] = "unknown"
            payload["location_source"] = "unknown"
            saved = store.upsert("game-1:atbat-2", payload)
            self.assertFalse(saved["ground_fly_eligible"])
            self.assertFalse(saved["location_eligible"])
            self.assertTrue(saved["contact_eligible"])


if __name__ == "__main__":
    unittest.main()
