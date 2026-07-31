from __future__ import annotations

import argparse
import csv
import sys
import tempfile
import unittest
import wave
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT))

import launcher  # noqa: E402


def create_sample(
    dataset: Path,
    label: str,
    collector: str,
    sample_id: str,
    *,
    event_start: float = 0.25,
    event_end: float = 0.35,
) -> Path:
    sample = dataset / label / collector / sample_id
    sample.mkdir(parents=True)
    with (sample / "sample.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "label",
                "landing_zone",
                "strength",
                "trajectory_type",
                "event_start",
                "event_end",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "sample_id": sample_id,
                "label": label,
                "landing_zone": "5",
                "strength": "medium",
                "trajectory_type": "fly" if label == "fly_ball" else "ground",
                "event_start": event_start,
                "event_end": event_end,
            }
        )
    with wave.open(str(sample / "audio.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8_000)
        handle.writeframes(b"\x00\x00" * 8_000)
    (sample / "video.mp4").write_bytes(b"synthetic-test-video")
    (sample / "label.txt").write_text(label + "\n", encoding="utf-8")
    (sample / "source.txt").write_text("synthetic\n", encoding="utf-8")
    return sample


def args_for(root: Path, assignment: Path) -> argparse.Namespace:
    return argparse.Namespace(
        assignment=assignment,
        reviewer="reviewer01",
        dataset_root=root / "dataset",
        output_root=root / "outputs",
        ground_port=8765,
        fly_port=8766,
        no_browser=True,
        prepare_only=True,
    )


class AssignmentSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dataset = self.root / "dataset"
        create_sample(self.dataset, "ground_ball", "member_a", "G_0002")
        create_sample(self.dataset, "ground_ball", "member_a", "G_0001")
        create_sample(self.dataset, "fly_ball", "member_b", "F_0002")
        create_sample(self.dataset, "fly_ball", "member_b", "F_0001")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assignment(self, text: str) -> Path:
        path = self.root / "assignment.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def test_mixed_assignment_preserves_order_within_each_workflow(self) -> None:
        assignment = self.assignment(
            "# mixed\nF_0002\nG_0002\n\nF_0001\nG_0001\n"
        )
        session = launcher.prepare_session(args_for(self.root, assignment))
        generated = Path(session["generated_dir"])
        with (generated / "groundball_manifest.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            ground = list(csv.DictReader(handle))
        with (generated / "flyball_manifest.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            fly = list(csv.DictReader(handle))
        self.assertEqual([row["sample_id"] for row in ground], ["G_0002", "G_0001"])
        self.assertEqual([row["sample_id"] for row in fly], ["F_0002", "F_0001"])
        self.assertEqual(session["reviewer_id"], "reviewer01")
        self.assertEqual(session["sample_count"], 4)
        self.assertTrue(all(not Path(row["sample_relpath"]).is_absolute() for row in ground + fly))

    def test_duplicate_assignment_is_rejected_with_both_line_numbers(self) -> None:
        assignment = self.assignment("G_0001\nF_0001\nG_0001\n")
        with self.assertRaisesRegex(launcher.SessionError, "第 3 行重复 G_0001"):
            launcher.read_assignment(assignment)

    def test_missing_sample_is_rejected_before_server_launch(self) -> None:
        assignment = self.assignment("G_9999\n")
        with self.assertRaisesRegex(launcher.SessionError, "找不到样本：G_9999"):
            launcher.prepare_session(args_for(self.root, assignment))

    def test_ambiguous_sample_id_is_rejected(self) -> None:
        create_sample(self.dataset, "ground_ball", "member_c", "G_0001")
        assignment = self.assignment("G_0001\n")
        with self.assertRaisesRegex(launcher.SessionError, "样本编号不唯一：G_0001"):
            launcher.prepare_session(args_for(self.root, assignment))

    def test_repository_root_is_accepted_as_dataset_root(self) -> None:
        assignment = self.assignment("F_0001\n")
        args = args_for(self.root, assignment)
        args.dataset_root = self.root
        session = launcher.prepare_session(args)
        self.assertEqual(session["flyball_count"], 1)
        self.assertEqual(Path(session["dataset_root"]), self.dataset.resolve())

    def test_invalid_reviewer_and_store_alias_format_are_rejected(self) -> None:
        assignment = self.assignment("F_0001\n")
        args = args_for(self.root, assignment)
        args.reviewer = "bad reviewer/path"
        with self.assertRaisesRegex(launcher.SessionError, "审核人代号"):
            launcher.prepare_session(args)


if __name__ == "__main__":
    unittest.main()
