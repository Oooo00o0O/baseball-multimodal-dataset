from __future__ import annotations

import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
MODULE_DIR = HERE.parents[1]
sys.path.insert(0, str(MODULE_DIR))

from exports import (  # noqa: E402
    ReviewConflictError,
    WindowPolicy,
    build_exports,
    merge_review_batches,
)


def inventory() -> dict[str, object]:
    return {
        "source_play_id": "mlb:1:play:a",
        "game_pk": "1",
        "play_id": "a",
        "game_date": "2026-07-01",
        "batter": "Batter",
        "video_relpath": "media/video.mp4",
        "audio_relpath": "media/audio.wav",
        "media_duration_sec": "5",
    }


def review(batch: str = "a") -> dict[str, object]:
    return {
        "source_play_id": "mlb:1:play:a",
        "batch_id": batch,
        "admission_status": "admitted",
        "exclusion_reason": "",
        "observed_trajectory": "line_drive",
        "derived_ground_fly_label": "fly_ball",
        "reviewed_location": "8",
        "reviewed_hit_time": "1.2",
        "contact_eligible": "true",
        "ground_fly_eligible": "true",
        "location_eligible": "true",
        "reviewed_at_utc": "2026-07-31T00:00:00+00:00",
    }


class ExportTests(unittest.TestCase):
    def test_builds_three_task_specific_manifests_with_bounded_window(self) -> None:
        exports = build_exports(
            [inventory()],
            [review()],
            WindowPolicy(pre_contact_sec=1.0, post_contact_sec=0.5),
        )
        self.assertEqual(len(exports["audit_combined"]), 1)
        self.assertEqual(exports["contact_manifest"][0]["target"], "bat_ball_contact")
        self.assertEqual(exports["ground_fly_manifest"][0]["target"], "fly_ball")
        self.assertEqual(exports["location_manifest"][0]["target"], "8")
        self.assertEqual(
            exports["ground_fly_manifest"][0]["input_window_start_sec"],
            0.2,
        )
        self.assertEqual(
            exports["ground_fly_manifest"][0]["input_window_end_sec"],
            1.7,
        )

    def test_excluded_row_stays_in_audit_but_not_task_manifests(self) -> None:
        excluded = review()
        excluded.update(
            {
                "admission_status": "excluded",
                "exclusion_reason": "no_contact",
                "reviewed_hit_time": "",
                "contact_eligible": "false",
                "ground_fly_eligible": "false",
                "location_eligible": "false",
            }
        )
        exports = build_exports([inventory()], [excluded])
        self.assertEqual(len(exports["audit_combined"]), 1)
        self.assertEqual(exports["contact_manifest"], [])
        self.assertEqual(exports["ground_fly_manifest"], [])
        self.assertEqual(exports["location_manifest"], [])

    def test_conflicting_batches_are_rejected(self) -> None:
        first = review("member-a")
        second = review("member-b")
        second["observed_trajectory"] = "ground_ball"
        with self.assertRaises(ReviewConflictError):
            merge_review_batches([first, second])

    def test_identical_batch_rows_merge_provenance(self) -> None:
        first = review("member-a")
        second = review("member-b")
        merged = merge_review_batches([first, second])
        self.assertEqual(merged[0]["batch_id"], "member-a+member-b")


if __name__ == "__main__":
    unittest.main()
