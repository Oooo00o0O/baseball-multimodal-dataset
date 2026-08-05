from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
MODULE_DIR = HERE.parents[1]
sys.path.insert(0, str(MODULE_DIR))

from media_preparation import media_directory, read_review_rows  # noqa: E402


class MediaPreparationTests(unittest.TestCase):
    def test_media_directory_is_stable_and_filesystem_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = media_directory(root, "mlb:123:play:abc/def")
            second = media_directory(root, "mlb:123:play:abc/def")
            self.assertEqual(first, second)
            self.assertEqual(first.parent, root.resolve())
            self.assertNotIn(":", first.name)
            self.assertNotIn("/", first.name)

    def test_reads_all_batch_review_csvs_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "batch-a.csv").write_text(
                "source_play_id,admission_status\none,admitted\n",
                encoding="utf-8",
            )
            (root / "batch-b.csv").write_text(
                "source_play_id,admission_status\ntwo,excluded\n",
                encoding="utf-8",
            )
            (root / "ignore.txt").write_text("not csv", encoding="utf-8")
            rows = read_review_rows(root)
            self.assertEqual(
                {row["source_play_id"] for row in rows},
                {"one", "two"},
            )


if __name__ == "__main__":
    unittest.main()
