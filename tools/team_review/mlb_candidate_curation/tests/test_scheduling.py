from __future__ import annotations

import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
MODULE_DIR = HERE.parents[1]
sys.path.insert(0, str(MODULE_DIR))

from scheduling import ScheduleConfig, select_for_preparation  # noqa: E402


def candidate(
    source_play_id: str,
    game_pk: str,
    trajectory: str,
    location: str,
    confidence: str = "high",
    status: str = "metadata_only",
) -> dict[str, object]:
    return {
        "source_play_id": source_play_id,
        "game_pk": game_pk,
        "mlb_trajectory_raw": trajectory,
        "mlb_location_raw": location,
        "media_match_confidence": confidence,
        "media_status": status,
        "source_mp4_url": f"https://example.test/{source_play_id}.mp4",
    }


class CoverageSchedulerTests(unittest.TestCase):
    def test_prefers_coverage_deficit_over_already_full_cell(self) -> None:
        inventory = [
            candidate("ground", "1", "ground_ball", "4"),
            candidate("line", "2", "line_drive", "8"),
        ]
        reviews = [
            {
                "source_play_id": f"old-{index}",
                "admission_status": "admitted",
                "observed_trajectory": "ground_ball",
                "reviewed_location": "4",
            }
            for index in range(10)
        ]
        selected = select_for_preparation(
            inventory,
            reviews,
            ScheduleConfig(
                buffer_target=1,
                per_game_cap=2,
                ground_target=1,
                air_target=10,
                line_drive_target=10,
                per_location_target=2,
            ),
        )
        self.assertEqual(selected[0].source_play_id, "line")
        self.assertIn("补齐", selected[0].reason_zh)

    def test_high_confidence_precedes_medium_at_equal_coverage(self) -> None:
        inventory = [
            candidate("medium", "1", "ground_ball", "4", confidence="medium"),
            candidate("high", "2", "ground_ball", "4", confidence="high"),
        ]
        selected = select_for_preparation(
            inventory,
            [],
            ScheduleConfig(buffer_target=1, per_game_cap=2),
        )
        self.assertEqual(selected[0].source_play_id, "high")

    def test_mlb_popup_raw_hint_counts_as_pop_fly(self) -> None:
        inventory = [
            candidate("popup", "1", "popup", "4"),
            candidate("ground", "2", "ground_ball", "4"),
        ]
        selected = select_for_preparation(
            inventory,
            [],
            ScheduleConfig(
                buffer_target=1,
                per_game_cap=2,
                ground_target=0,
                air_target=10,
                pop_fly_target=10,
                per_location_target=0,
            ),
        )
        self.assertEqual(selected[0].source_play_id, "popup")
    def test_respects_existing_buffer_and_per_game_cap(self) -> None:
        inventory = [
            candidate("ready", "1", "ground_ball", "4", status="prepared"),
            candidate("same-game", "1", "line_drive", "7"),
            candidate("other-game", "2", "fly_ball", "8"),
        ]
        selected = select_for_preparation(
            inventory,
            [],
            ScheduleConfig(buffer_target=2, per_game_cap=1),
        )
        self.assertEqual(
            [item.source_play_id for item in selected],
            ["other-game"],
        )

    def test_does_not_schedule_low_unmatched_or_reviewed_rows(self) -> None:
        inventory = [
            candidate("low", "1", "ground_ball", "4", confidence="low"),
            candidate("missing-url", "2", "fly_ball", "8"),
            candidate("reviewed", "3", "line_drive", "9"),
        ]
        inventory[1]["source_mp4_url"] = ""
        reviews = [
            {
                "source_play_id": "reviewed",
                "admission_status": "excluded",
                "exclusion_reason": "wrong_play",
            }
        ]
        self.assertEqual(select_for_preparation(inventory, reviews), [])


if __name__ == "__main__":
    unittest.main()
