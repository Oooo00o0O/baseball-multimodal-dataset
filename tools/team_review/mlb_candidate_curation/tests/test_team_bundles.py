from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
MODULE_DIR = HERE.parents[1]
sys.path.insert(0, str(MODULE_DIR))

from team_bundles import (  # noqa: E402
    build_team_bundle_bytes,
    consolidate_team_bundles,
    load_team_bundle,
)


def inventory(play_id: str, video_id: str, relpath: str) -> dict[str, str]:
    return {
        "source_play_id": play_id,
        "game_pk": "1",
        "play_id": play_id.rsplit(":", 1)[-1],
        "game_date": "2026-05-01",
        "batter": "Test Batter",
        "source_video_id": video_id,
        "source_title": "Test Batter grounds out",
        "video_relpath": relpath,
    }


def review(play_id: str, batch_id: str, trajectory: str = "ground_ball") -> dict[str, str]:
    return {
        "batch_id": batch_id,
        "source_play_id": play_id,
        "admission_status": "admitted",
        "observed_trajectory": trajectory,
        "derived_ground_fly_label": (
            "ground_ball" if trajectory == "ground_ball" else "fly_ball"
        ),
        "reviewed_location": "6",
        "reviewed_hit_time": "1.2",
        "contact_eligible": "true",
        "ground_fly_eligible": "true",
        "location_eligible": "true",
        "reviewed_at_utc": "2026-08-05T00:00:00+00:00",
    }


class TeamBundleTests(unittest.TestCase):
    def _write_bundle(
        self,
        root: Path,
        batch_id: str,
        inventories: list[dict[str, str]],
        reviews: list[dict[str, str]],
    ) -> Path:
        path = root / f"{batch_id}.zip"
        path.write_bytes(
            build_team_bundle_bytes(
                inventories,
                reviews,
                root,
                batch_id=batch_id,
                assigned_start_date="2026-05-01",
                assigned_end_date="2026-05-31",
            )
        )
        return path

    def test_bundle_contains_no_media_and_keeps_date_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media" / "one.mp4"
            media.parent.mkdir(parents=True)
            media.write_bytes(b"video-one")
            bundle = self._write_bundle(
                root,
                "member-a",
                [inventory("mlb:1:play:a", "video-a", "media/one.mp4")],
                [review("mlb:1:play:a", "member-a")],
            )
            loaded = load_team_bundle(bundle)
            self.assertFalse(loaded["manifest"]["contains_media"])
            self.assertEqual(
                loaded["manifest"]["assigned_start_date"],
                "2026-05-01",
            )
            self.assertEqual(len(loaded["inventory"][0]["media_sha256"]), 64)

    def test_python_booleans_are_exported_in_canonical_lowercase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "one.mp4"
            media.write_bytes(b"video-one")
            row = review("mlb:1:play:a", "member-a")
            row["contact_eligible"] = True
            row["broken_bat"] = False
            bundle = self._write_bundle(
                root,
                "member-a",
                [inventory("mlb:1:play:a", "video-a", "one.mp4")],
                [row],
            )
            loaded = load_team_bundle(bundle)
            self.assertEqual(loaded["reviews"][0]["contact_eligible"], "true")
            self.assertEqual(loaded["reviews"][0]["broken_bat"], "false")

    def test_matching_duplicate_reviews_collapse_with_batch_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "same.mp4"
            media.write_bytes(b"same")
            item = inventory("mlb:1:play:a", "video-a", "same.mp4")
            first = self._write_bundle(root, "member-a", [item], [review(item["source_play_id"], "member-a")])
            second = self._write_bundle(root, "member-b", [item], [review(item["source_play_id"], "member-b")])
            result = consolidate_team_bundles([first, second])
            self.assertEqual(result["summary"]["merged_plays"], 1)
            self.assertEqual(result["merged_reviews"][0]["batch_id"], "member-a+member-b")

    def test_conflicting_reviews_are_reported_and_not_merged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "same.mp4"
            media.write_bytes(b"same")
            item = inventory("mlb:1:play:a", "video-a", "same.mp4")
            first = self._write_bundle(root, "member-a", [item], [review(item["source_play_id"], "member-a")])
            second = self._write_bundle(root, "member-b", [item], [review(item["source_play_id"], "member-b", "fly_ball")])
            result = consolidate_team_bundles([first, second])
            self.assertEqual(result["summary"]["merged_plays"], 0)
            self.assertIn("observed_trajectory", result["conflicts"][0]["conflict_fields"])

    def test_same_media_for_different_plays_is_held_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "package.mp4"
            media.write_bytes(b"same-package")
            first_item = inventory("mlb:1:play:a", "package-video", "package.mp4")
            second_item = inventory("mlb:1:play:b", "package-video", "package.mp4")
            first = self._write_bundle(root, "member-a", [first_item], [review(first_item["source_play_id"], "member-a")])
            second = self._write_bundle(root, "member-b", [second_item], [review(second_item["source_play_id"], "member-b")])
            result = consolidate_team_bundles([first, second])
            self.assertEqual(result["summary"]["merged_plays"], 0)
            self.assertGreaterEqual(result["summary"]["media_warnings"], 1)

    def test_same_play_with_different_source_videos_is_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_media = root / "first.mp4"
            second_media = root / "second.mp4"
            first_media.write_bytes(b"first")
            second_media.write_bytes(b"second")
            first_item = inventory("mlb:1:play:a", "video-a", "first.mp4")
            second_item = inventory("mlb:1:play:a", "video-b", "second.mp4")
            first = self._write_bundle(root, "member-a", [first_item], [review(first_item["source_play_id"], "member-a")])
            second = self._write_bundle(root, "member-b", [second_item], [review(second_item["source_play_id"], "member-b")])
            result = consolidate_team_bundles([first, second])
            self.assertEqual(result["summary"]["merged_plays"], 0)
            self.assertIn("source_video_id", result["conflicts"][0]["conflict_fields"])


if __name__ == "__main__":
    unittest.main()
