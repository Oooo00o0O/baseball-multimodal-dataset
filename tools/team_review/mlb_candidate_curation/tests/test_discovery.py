from __future__ import annotations

import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
MODULE_DIR = HERE.parents[1]
sys.path.insert(0, str(MODULE_DIR))

from discovery import (  # noqa: E402
    apply_media_match,
    build_inventory_row,
    extract_videos,
    is_target_candidate,
    match_video_for_play,
    multi_event_title_pattern,
    playback_mp4_url,
    predownload_auxiliary_diversion,
    provisional_trajectory,
    source_play_identity,
)


def game() -> dict:
    return {
        "gamePk": 123,
        "officialDate": "2026-07-01",
        "teams": {
            "away": {"team": {"name": "Away"}},
            "home": {"team": {"name": "Home"}},
        },
    }


def play(
    description: str = "Test Batter grounds out, shortstop A to first baseman B.",
    event: str = "Groundout",
    event_type: str = "field_out",
    terminal_description: str = "In play, out(s)",
    is_in_play: bool = True,
) -> dict:
    return {
        "result": {
            "event": event,
            "eventType": event_type,
            "description": description,
        },
        "about": {"atBatIndex": 7, "inning": 3, "halfInning": "top"},
        "matchup": {
            "batter": {"fullName": "Test Batter"},
            "pitcher": {"fullName": "Test Pitcher"},
        },
        "playEvents": [
            {
                "playId": "earlier-foul",
                "details": {"description": "Foul", "isInPlay": False},
            },
            {
                "playId": "terminal-contact",
                "index": 1,
                "details": {
                    "description": terminal_description,
                    "isInPlay": is_in_play,
                },
                "hitData": {"trajectory": "ground_ball", "location": "6"},
            },
        ],
    }


def video(
    video_id: str,
    title: str,
    description: str,
    duration: str = "00:00:18",
    keywords: tuple[str, ...] = ("highlight", "in-game highlight"),
) -> dict:
    return {
        "type": "video",
        "id": video_id,
        "title": title,
        "description": description,
        "duration": duration,
        "keywordsAll": [{"displayName": value} for value in keywords],
        "playbacks": [
            {
                "name": "mp4Avc",
                "url": f"https://example.invalid/{video_id}.mp4",
            }
        ],
    }


class DiscoveryTests(unittest.TestCase):
    def test_source_identity_prefers_terminal_play_id(self) -> None:
        source_id, method = source_play_identity(123, play())
        self.assertEqual(source_id, "mlb:123:play:terminal-contact")
        self.assertEqual(method, "game_pk_play_id")

    def test_prior_foul_pitch_does_not_divert_completed_groundout(self) -> None:
        candidate = play()
        self.assertIsNone(predownload_auxiliary_diversion(candidate))
        self.assertTrue(is_target_candidate(candidate))

    def test_structured_terminal_foul_tip_is_diverted(self) -> None:
        candidate = play(
            description="Test Batter foul tips the pitch.",
            event="Foul Tip",
            event_type="foul_tip",
            terminal_description="Foul Tip",
            is_in_play=False,
        )
        diversion = predownload_auxiliary_diversion(candidate)
        self.assertEqual(diversion.event_type, "foul_tip")
        self.assertEqual(diversion.classification_source, "mlb_structured")

    def test_official_bunt_description_is_diverted(self) -> None:
        candidate = play(
            description="Test Batter bunts into a force out.",
            event="Bunt Groundout",
            event_type="field_out",
        )
        diversion = predownload_auxiliary_diversion(candidate)
        self.assertEqual(diversion.event_type, "bunt")
        self.assertEqual(
            diversion.classification_source,
            "official_play_description",
        )

    def test_trajectory_is_inferred_from_official_description(self) -> None:
        candidate = play(
            description="Test Batter lines out sharply to left fielder A.",
            event="Lineout",
        )
        candidate["playEvents"][-1].pop("hitData")
        self.assertEqual(provisional_trajectory(candidate), "line_drive")

    def test_high_match_requires_short_in_game_highlight(self) -> None:
        candidate = play()
        match = match_video_for_play(
            candidate,
            [
                video(
                    "test-batter-grounds-out",
                    "Test Batter grounds out",
                    "Test Batter grounds out to shortstop in the 3rd.",
                ),
                video(
                    "condensed-game",
                    "Condensed Game",
                    "Away plays Home",
                    duration="00:08:14",
                    keywords=("condensed game",),
                ),
            ],
            high_threshold=100,
        )
        self.assertEqual(match.confidence, "high")
        self.assertEqual(match.video["id"], "test-batter-grounds-out")
        row = apply_media_match(build_inventory_row(game(), candidate), match)
        self.assertEqual(row["media_status"], "metadata_only")
        self.assertTrue(str(row["source_mp4_url"]).endswith(".mp4"))

    def test_same_batter_wrong_outcome_forces_low_confidence(self) -> None:
        candidate = play(
            description="Test Batter singles on a line drive to left fielder A.",
            event="Single",
            event_type="single",
        )
        match = match_video_for_play(
            candidate,
            [
                video(
                    "test-batter-lines-out-to-shortstop",
                    "Test Batter lines out",
                    "Test Batter lines out to shortstop in the 3rd.",
                )
            ],
        )
        self.assertEqual(match.confidence, "low")
        self.assertIn("结果", " ".join(match.conflicting_evidence))

    def test_generated_slug_for_other_pitcher_and_batter_is_rejected(self) -> None:
        candidate = play()
        match = match_video_for_play(
            candidate,
            [
                video(
                    "other-pitcher-in-play-out-s-to-other-batter",
                    "Test Batter's diving stop",
                    "Test Batter makes a diving stop in the 3rd.",
                )
            ],
        )
        self.assertEqual(match.confidence, "low")
        self.assertTrue(match.conflicting_evidence)

    def test_conflicting_trajectory_forces_low_confidence(self) -> None:
        candidate = play()
        match = match_video_for_play(
            candidate,
            [
                video(
                    "test-batter-homers",
                    "Test Batter homers on a fly ball",
                    "Test Batter hits a fly ball home run.",
                )
            ],
        )
        self.assertEqual(match.confidence, "low")
        self.assertTrue(match.conflicting_evidence)

    def test_extract_videos_deduplicates_nested_content(self) -> None:
        item = video("same-id", "Title", "Description")
        content = {"a": [item], "b": {"nested": [dict(item)]}}
        videos = extract_videos(content)
        self.assertEqual(len(videos), 1)
        self.assertTrue(playback_mp4_url(videos[0]).endswith("same-id.mp4"))

    def test_explicit_multi_hit_package_is_excluded_before_matching(self) -> None:
        candidate = play()
        package = video(
            "test-batter-four-hit-game",
            "Test Batter's four-hit game",
            "Test Batter collects four hits.",
            duration="00:01:14",
        )
        match = match_video_for_play(candidate, [package])
        self.assertIsNone(match.video)
        self.assertEqual(len(match.excluded_media), 1)
        self.assertEqual(match.excluded_media[0].reason, "multi_event_title")
        self.assertEqual(multi_event_title_pattern(package), "counted_hits")

    def test_long_single_play_is_downgraded_but_not_excluded(self) -> None:
        candidate = play()
        long_single_play = video(
            "test-batter-grounds-out",
            "Test Batter grounds out",
            "Test Batter grounds out to shortstop in the 3rd.",
            duration="00:00:55",
        )
        match = match_video_for_play(
            candidate,
            [long_single_play],
            high_threshold=100,
        )
        self.assertEqual(match.confidence, "medium")
        self.assertEqual(match.video["id"], "test-batter-grounds-out")
        self.assertEqual(match.excluded_media, ())

    def test_second_hit_single_play_title_is_not_treated_as_package(self) -> None:
        single_play = video(
            "test-batter-second-hit",
            "Test Batter's second hit of the game",
            "Test Batter singles in the 3rd.",
        )
        self.assertEqual(multi_event_title_pattern(single_play), "")


if __name__ == "__main__":
    unittest.main()
