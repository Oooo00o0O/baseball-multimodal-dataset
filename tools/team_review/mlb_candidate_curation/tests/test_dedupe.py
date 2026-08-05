from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
MODULE_DIR = HERE.parents[1]
sys.path.insert(0, str(MODULE_DIR))

from dedupe import (  # noqa: E402
    HistoricalDuplicateIndex,
    mlb_video_slug,
    normalize_url,
)


class HistoricalDuplicateIndexTests(unittest.TestCase):
    def test_url_normalization_removes_query_and_fragment(self) -> None:
        value = "HTTPS://WWW.MLB.COM/video/example-slug/?foo=1#bar"
        self.assertEqual(
            normalize_url(value),
            "https://www.mlb.com/video/example-slug",
        )
        self.assertEqual(mlb_video_slug(value), "example-slug")

    def test_source_text_slug_matches_candidate_with_different_query(self) -> None:
        index = HistoricalDuplicateIndex()
        index.add_source_text(
            "source: https://www.mlb.com/video/example-play?partnerId=web_video-playback"
        )
        match = index.match(
            {
                "source_page_url": "https://www.mlb.com/video/example-play?x=2",
            }
        )
        self.assertTrue(match.duplicate)
        self.assertEqual(match.reason, "source_page_url")

    def test_same_game_batter_description_fingerprint_matches(self) -> None:
        index = HistoricalDuplicateIndex()
        index.add_row(
            {
                "gamePk": "123",
                "batter": "Test Batter",
                "play_description": "Test Batter grounds out to shortstop.",
            }
        )
        match = index.match(
            {
                "game_pk": "123",
                "batter": "Test Batter",
                "play_description": " Test Batter grounds out to shortstop. ",
            }
        )
        self.assertTrue(match.duplicate)
        self.assertEqual(match.reason, "play_description_fingerprint")

    def test_different_game_is_not_description_duplicate(self) -> None:
        index = HistoricalDuplicateIndex()
        index.add_row(
            {
                "gamePk": "123",
                "batter": "Test Batter",
                "play_description": "Test Batter grounds out.",
            }
        )
        self.assertFalse(
            index.match(
                {
                    "game_pk": "124",
                    "batter": "Test Batter",
                    "play_description": "Test Batter grounds out.",
                }
            ).duplicate
        )

    def test_loads_csv_and_source_txt_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "legacy.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source_url"])
                writer.writeheader()
                writer.writerow(
                    {"source_url": "https://www.mlb.com/video/from-csv"}
                )
            source_dir = root / "sample"
            source_dir.mkdir()
            (source_dir / "source.txt").write_text(
                "https://www.mlb.com/video/from-source",
                encoding="utf-8",
            )
            index = HistoricalDuplicateIndex.from_paths(
                [csv_path],
                [root],
            )
            self.assertIn("from-csv", index.video_slugs)
            self.assertIn("from-source", index.video_slugs)


if __name__ == "__main__":
    unittest.main()
