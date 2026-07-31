from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = ("video.mp4", "audio.wav", "label.txt", "sample.csv", "source.txt")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def sample_row(path: Path) -> dict[str, str]:
    rows = read_csv(path)
    if len(rows) != 1:
        raise ValueError(f"{path} must contain exactly one row")
    return rows[0]


def source_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_changed_sample_dirs(base_ref: str = "") -> set[str]:
    command = ["git", "diff", "--name-only"]
    if base_ref:
        command.append(base_ref)
    command.extend(["--", "dataset/fly_ball"])
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    result: set[str] = set()
    for line in completed.stdout.splitlines():
        parts = line.replace("\\", "/").split("/")
        if len(parts) >= 5:
            result.add("/".join(parts[:4]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an applied fly-ball batch against its reconciliation CSV.")
    parser.add_argument("--changes", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument(
        "--base-ref",
        default="",
        help="Compare dataset changes with this Git ref instead of the current index.",
    )
    args = parser.parse_args()

    rows = read_csv(args.changes)
    accepted = [row for row in rows if row["changed"] == "yes"]
    unresolved = [row for row in rows if row["result"] == "unchanged_unresolved"]
    errors: list[dict[str, Any]] = []

    for row in accepted:
        sample_dir = REPO_ROOT / row["main_relative_path"]
        for filename in REQUIRED_FILES:
            path = sample_dir / filename
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(
                    {
                        "sample_id": row["sample_id"],
                        "error": f"missing_or_empty:{filename}",
                    }
                )
        try:
            current = sample_row(sample_dir / "sample.csv")
        except Exception as exc:
            errors.append({"sample_id": row["sample_id"], "error": str(exc)})
            continue
        if current.get("event_start") != row["after_event_start"]:
            errors.append({"sample_id": row["sample_id"], "error": "event_start_mismatch"})
        if current.get("event_end") != row["after_event_end"]:
            errors.append({"sample_id": row["sample_id"], "error": "event_end_mismatch"})
        event_start = float(row["after_event_start"])
        event_end = float(row["after_event_end"])
        candidate = float(row["selected_candidate_time"])
        if abs((event_start + event_end) / 2.0 - candidate) > 0.001:
            errors.append({"sample_id": row["sample_id"], "error": "candidate_not_at_event_midpoint"})
        if not 0.095 <= event_end - event_start <= 0.105:
            errors.append({"sample_id": row["sample_id"], "error": "event_window_not_0p1_seconds"})
        if row.get("audio_visual_offset") and float(row["audio_visual_offset"]) > 0.35:
            errors.append({"sample_id": row["sample_id"], "error": "audio_visual_offset_too_large"})
        if row["after_video_sha256"] != sha256(sample_dir / "video.mp4"):
            errors.append({"sample_id": row["sample_id"], "error": "video_hash_mismatch"})
        if row["after_audio_sha256"] != sha256(sample_dir / "audio.wav"):
            errors.append({"sample_id": row["sample_id"], "error": "audio_hash_mismatch"})
        if row["result"] == "recut_and_retime":
            source = source_values(sample_dir / "source.txt")
            if source.get("clip_start_time") != row["source_clip_start_after"]:
                errors.append({"sample_id": row["sample_id"], "error": "source_clip_start_mismatch"})
            if source.get("clip_end_time") != row["source_clip_end_after"]:
                errors.append({"sample_id": row["sample_id"], "error": "source_clip_end_mismatch"})

    changed_dirs = git_changed_sample_dirs(args.base_ref)
    accepted_dirs = {row["main_relative_path"] for row in accepted}
    unresolved_dirs = {row["main_relative_path"] for row in unresolved}
    for path in sorted(changed_dirs - accepted_dirs):
        errors.append({"sample_id": "", "error": f"unexpected_changed_sample:{path}"})
    for path in sorted(accepted_dirs - changed_dirs):
        errors.append({"sample_id": "", "error": f"accepted_sample_not_changed:{path}"})
    for path in sorted(changed_dirs & unresolved_dirs):
        errors.append({"sample_id": "", "error": f"unresolved_sample_changed:{path}"})

    summary = {
        "queue_rows": len(rows),
        "accepted_changed_rows": len(accepted),
        "unresolved_unchanged_rows": len(unresolved),
        "git_changed_sample_dirs": len(changed_dirs),
        "git_base_ref": args.base_ref or "index",
        "verification_errors": len(errors),
        "errors": errors,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
