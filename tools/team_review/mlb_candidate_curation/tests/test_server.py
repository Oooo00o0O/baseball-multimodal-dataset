from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path


HERE = Path(__file__).resolve()
MODULE_DIR = HERE.parents[1]
sys.path.insert(0, str(MODULE_DIR))

import server  # noqa: E402
from stores import CandidateInventoryStore  # noqa: E402


def prepared_row(root: Path) -> dict[str, object]:
    media = root / "media"
    media.mkdir(parents=True)
    (media / "video.mp4").write_bytes(b"video")
    (media / "audio_original.wav").write_bytes(b"audio")
    (media / "audio_contact_enhanced.wav").write_bytes(b"enhanced")
    return {
        "source_play_id": "mlb:1:play:test",
        "identity_method": "game_pk_play_id",
        "game_pk": "1",
        "play_id": "test",
        "game_date": "2026-07-01",
        "batter": "Test Batter",
        "play_description": "Test Batter grounds out.",
        "mlb_trajectory_raw": "ground_ball",
        "mlb_location_raw": "4",
        "media_match_confidence": "high",
        "media_status": "prepared",
        "video_relpath": "media/video.mp4",
        "audio_relpath": "media/audio_original.wav",
        "media_duration_sec": "4",
        "auto_hit_time_1": "1.2",
        "auto_hit_score_1": "1",
        "detector_version": "test-detector",
    }


class WorkbenchStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_root = server.PROJECT_ROOT

    def tearDown(self) -> None:
        server.PROJECT_ROOT = self.original_root

    def test_queue_sample_review_and_combined_export_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            server.PROJECT_ROOT = root
            inventory_path = root / "inventory.csv"
            inventory = CandidateInventoryStore(inventory_path)
            inventory.upsert(prepared_row(root))
            state = server.CurationWorkbenchState(
                inventory_path,
                root / "reviews" / "local.csv",
                "local",
                "2026-07-01",
                "2026-07-31",
            )
            self.assertEqual(len(state.queue()), 1)
            sample = state.sample("mlb:1:play:test")
            self.assertEqual(sample["contact_candidates"][0]["time_sec"], 1.2)
            self.assertTrue(sample["enhanced_audio_url"])
            saved = state.save_review(
                "mlb:1:play:test",
                {
                    "admission_status": "admitted",
                    "observed_trajectory": "ground_ball",
                    "reviewed_location": "4",
                    "reviewed_hit_time": "1.2",
                },
            )
            self.assertEqual(saved["summary"]["reviewed"], 1)
            exported = state.combined_export_bytes().decode("utf-8-sig")
            self.assertIn("Test Batter", exported)
            self.assertIn("ground_ball", exported)
            header = exported.splitlines()[0].split(",")
            self.assertEqual(header.count("mlb_location_raw"), 1)
            with zipfile.ZipFile(BytesIO(state.team_bundle_bytes())) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"manifest.json", "reviews.csv", "reviewed_inventory.csv"},
                )

    def test_media_path_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            server.PROJECT_ROOT = root
            inventory_path = root / "inventory.csv"
            row = prepared_row(root)
            row["video_relpath"] = "../outside.mp4"
            inventory = CandidateInventoryStore(inventory_path)
            inventory.upsert(row)
            state = server.CurationWorkbenchState(
                inventory_path,
                root / "reviews.csv",
                "local",
            )
            with self.assertRaises(PermissionError):
                state.media_path("mlb:1:play:test", "video")


if __name__ == "__main__":
    unittest.main()
