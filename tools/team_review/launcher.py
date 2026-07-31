"""Prepare and launch portable Groundball/Flyball review sessions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import time
import wave
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


TOOL_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = TOOL_ROOT.parents[1]
DEFAULT_DATASET_ROOT = REPOSITORY_ROOT / "dataset"
DEFAULT_OUTPUT_ROOT = TOOL_ROOT / "review_outputs"
ASSIGNMENT_PATTERN = re.compile(r"^(?P<prefix>[GF])_(?P<number>\d+)$", re.IGNORECASE)
REVIEWER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

GROUND_MANIFEST_FIELDS = [
    "schema_version",
    "audit_id",
    "uid",
    "sample_id",
    "label",
    "collector",
    "annotation_semantics",
    "sample_relpath",
    "audio_relpath",
    "video_relpath",
    "csv_relpath",
    "label_relpath",
    "source_relpath",
    "audio_available",
    "audio_readable",
    "video_state",
    "csv_available",
    "label_file_available",
    "source_file_available",
    "audio_duration_sec",
    "event_start",
    "event_end",
    "candidate_interval_valid",
    "auto_hit_time",
    "auto_hit_source",
    "timing_status",
    "timing_reasons",
    "data_issues",
    "risk_reasons",
]
GROUND_QUEUE_FIELDS = [
    "schema_version",
    "audit_id",
    "queue_position",
    "audio_available",
    "video_state",
    "event_start",
    "event_end",
    "auto_hit_time",
    "auto_hit_source",
]
FLY_MANIFEST_FIELDS = [
    "schema_version",
    "dataset_commit",
    "audit_id",
    "uid",
    "queue_position",
    "batch_number",
    "batch_position",
    "sample_id",
    "label",
    "recorded_trajectory",
    "landing_zone",
    "strength",
    "sample_relpath",
    "audio_relpath",
    "video_relpath",
    "csv_relpath",
    "label_relpath",
    "source_relpath",
    "audio_available",
    "audio_readable",
    "video_state",
    "event_start",
    "event_end",
    "candidate_interval_valid",
    "audio_duration_sec",
    "proposed_contact_time",
    "proposal_source",
    "expected_audio_blob_sha1",
    "expected_video_blob_sha1",
    "expected_csv_blob_sha1",
    "expected_label_blob_sha1",
    "expected_source_blob_sha1",
    "data_issues",
]
FLY_QUEUE_FIELDS = [
    "schema_version",
    "audit_id",
    "queue_position",
    "batch_number",
    "batch_position",
    "sample_id",
    "audio_available",
    "video_state",
    "event_start",
    "event_end",
    "proposed_contact_time",
    "recorded_trajectory",
]


class SessionError(ValueError):
    """Raised when a review session cannot be prepared safely."""


@dataclass(frozen=True)
class Sample:
    sample_id: str
    label: str
    collector: str
    directory: Path
    relative_directory: Path
    metadata: Mapping[str, str]
    audio_duration: float | None
    audio_readable: bool
    event_start: float | None
    event_end: float | None

    @property
    def audio_path(self) -> Path:
        return self.directory / "audio.wav"

    @property
    def video_path(self) -> Path:
        return self.directory / "video.mp4"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignment", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--ground-port", type=int, default=8765)
    parser.add_argument("--fly-port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    return parser.parse_args(argv)


def safe_slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug[:64] or fallback


def normalize_dataset_root(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    if (candidate / "dataset").is_dir() and not (
        (candidate / "ground_ball").is_dir() or (candidate / "fly_ball").is_dir()
    ):
        candidate = (candidate / "dataset").resolve()
    if not candidate.is_dir():
        raise SessionError(f"数据目录不存在：{candidate}")
    if not (
        (candidate / "ground_ball").is_dir() or (candidate / "fly_ball").is_dir()
    ):
        raise SessionError(
            "数据目录必须包含 ground_ball 或 fly_ball；也可以传入包含 dataset/ 的仓库根目录"
        )
    return candidate


def read_assignment(path: Path) -> tuple[list[str], str]:
    assignment = path.expanduser().resolve()
    if not assignment.is_file():
        raise SessionError(f"任务 TXT 不存在：{assignment}")
    raw = assignment.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SessionError("任务 TXT 必须使用 UTF-8 编码") from error

    sample_ids: list[str] = []
    seen: dict[str, int] = {}
    errors: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        sample_id = value.upper()
        if not ASSIGNMENT_PATTERN.fullmatch(sample_id):
            errors.append(f"第 {line_number} 行不是 G_数字 或 F_数字：{value}")
            continue
        if sample_id in seen:
            errors.append(
                f"第 {line_number} 行重复 {sample_id}（首次出现在第 {seen[sample_id]} 行）"
            )
            continue
        seen[sample_id] = line_number
        sample_ids.append(sample_id)
    if errors:
        raise SessionError("\n".join(errors))
    if not sample_ids:
        raise SessionError("任务 TXT 中没有 sample ID")
    return sample_ids, hashlib.sha256(raw).hexdigest()


def read_one_csv(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise SessionError(f"{path} 必须恰好包含一条数据，实际为 {len(rows)} 条")
    return {str(key): str(value or "").strip() for key, value in rows[0].items()}


def optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def inspect_audio(path: Path) -> tuple[bool, float | None]:
    if not path.is_file():
        return False, None
    try:
        with wave.open(str(path), "rb") as handle:
            frame_rate = handle.getframerate()
            frame_count = handle.getnframes()
            if frame_rate <= 0:
                return False, None
            return True, frame_count / frame_rate
    except (OSError, EOFError, wave.Error):
        return False, None


def format_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.9f}".rstrip("0").rstrip(".")


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def stable_id(prefix: str, uid: str) -> str:
    digest = hashlib.sha1(uid.encode("utf-8")).hexdigest()[:10].upper()
    return f"{prefix}{digest}"


def index_samples(dataset_root: Path) -> dict[str, list[Sample]]:
    index: dict[str, list[Sample]] = {}
    for label, prefix in (("ground_ball", "G"), ("fly_ball", "F")):
        label_root = dataset_root / label
        if not label_root.is_dir():
            continue
        for sample_csv in label_root.rglob("sample.csv"):
            directory = sample_csv.parent.resolve()
            sample_id = directory.name.upper()
            if not sample_id.startswith(f"{prefix}_"):
                continue
            metadata = read_one_csv(sample_csv)
            declared_id = metadata.get("sample_id", "").upper()
            if declared_id and declared_id != sample_id:
                raise SessionError(
                    f"目录编号与 sample.csv 不一致：{directory}（{declared_id}）"
                )
            relative = directory.relative_to(dataset_root)
            collector_parts = relative.parts[1:-1]
            collector = "/".join(collector_parts) or "unknown"
            audio_readable, duration = inspect_audio(directory / "audio.wav")
            event_start = optional_float(metadata.get("event_start"))
            event_end = optional_float(metadata.get("event_end"))
            index.setdefault(sample_id, []).append(
                Sample(
                    sample_id=sample_id,
                    label=label,
                    collector=collector,
                    directory=directory,
                    relative_directory=relative,
                    metadata=metadata,
                    audio_duration=duration,
                    audio_readable=audio_readable,
                    event_start=event_start,
                    event_end=event_end,
                )
            )
    return index


def resolve_samples(
    sample_ids: Iterable[str], dataset_root: Path
) -> tuple[list[Sample], list[Sample]]:
    index = index_samples(dataset_root)
    ground: list[Sample] = []
    fly: list[Sample] = []
    errors: list[str] = []
    for sample_id in sample_ids:
        matches = index.get(sample_id, [])
        if not matches:
            errors.append(f"找不到样本：{sample_id}")
            continue
        if len(matches) > 1:
            locations = ", ".join(
                sample.relative_directory.as_posix() for sample in matches
            )
            errors.append(f"样本编号不唯一：{sample_id} -> {locations}")
            continue
        sample = matches[0]
        expected_label = "ground_ball" if sample_id.startswith("G_") else "fly_ball"
        if sample.label != expected_label:
            errors.append(
                f"样本前缀与目录类别不一致：{sample_id} 位于 {sample.label}"
            )
            continue
        (ground if sample.label == "ground_ball" else fly).append(sample)
    if errors:
        raise SessionError("\n".join(errors))
    return ground, fly


def proposal(sample: Sample) -> tuple[float | None, bool]:
    start, end, duration = sample.event_start, sample.event_end, sample.audio_duration
    valid = (
        start is not None
        and end is not None
        and duration is not None
        and 0 <= start < end <= duration
    )
    return ((start + end) / 2 if valid else None), valid


def relative_file(sample: Sample, filename: str) -> str:
    return (sample.relative_directory / filename).as_posix()


def ground_rows(samples: Sequence[Sample]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    manifests: list[dict[str, object]] = []
    queue: list[dict[str, object]] = []
    for position, sample in enumerate(samples, start=1):
        auto_time, interval_valid = proposal(sample)
        uid = f"ground_ball__{sample.collector}__{sample.sample_id}"
        audit_id = stable_id("GB", uid)
        audio_exists = sample.audio_path.is_file()
        video_exists = sample.video_path.is_file()
        row: dict[str, object] = {
            "schema_version": "contact-audit-manifest-v1",
            "audit_id": audit_id,
            "uid": uid,
            "sample_id": sample.sample_id,
            "label": "ground_ball",
            "collector": sample.collector,
            "annotation_semantics": "start_end",
            "sample_relpath": sample.relative_directory.as_posix(),
            "audio_relpath": relative_file(sample, "audio.wav"),
            "video_relpath": relative_file(sample, "video.mp4"),
            "csv_relpath": relative_file(sample, "sample.csv"),
            "label_relpath": relative_file(sample, "label.txt"),
            "source_relpath": relative_file(sample, "source.txt"),
            "audio_available": bool_text(audio_exists),
            "audio_readable": bool_text(sample.audio_readable),
            "video_state": "ready_local" if video_exists else "missing",
            "csv_available": "true",
            "label_file_available": bool_text((sample.directory / "label.txt").is_file()),
            "source_file_available": bool_text((sample.directory / "source.txt").is_file()),
            "audio_duration_sec": format_float(sample.audio_duration),
            "event_start": format_float(sample.event_start),
            "event_end": format_float(sample.event_end),
            "candidate_interval_valid": bool_text(interval_valid),
            "auto_hit_time": format_float(auto_time),
            "auto_hit_source": "candidate_interval_midpoint" if auto_time is not None else "",
            "timing_status": "assignment_session",
            "timing_reasons": "",
            "data_issues": "" if audio_exists else "missing_audio",
            "risk_reasons": "",
        }
        manifests.append(row)
        queue.append(
            {
                "schema_version": row["schema_version"],
                "audit_id": audit_id,
                "queue_position": position,
                "audio_available": row["audio_available"],
                "video_state": row["video_state"],
                "event_start": row["event_start"],
                "event_end": row["event_end"],
                "auto_hit_time": row["auto_hit_time"],
                "auto_hit_source": row["auto_hit_source"],
            }
        )
    return manifests, queue


def fly_rows(samples: Sequence[Sample]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    manifests: list[dict[str, object]] = []
    queue: list[dict[str, object]] = []
    for position, sample in enumerate(samples, start=1):
        proposed_time, interval_valid = proposal(sample)
        uid = f"fly_ball__{sample.collector}__{sample.sample_id}"
        audit_id = stable_id("FB", uid)
        batch_number = ((position - 1) // 20) + 1
        batch_position = ((position - 1) % 20) + 1
        audio_exists = sample.audio_path.is_file()
        video_exists = sample.video_path.is_file()
        recorded_trajectory = sample.metadata.get("trajectory_type", "").strip()
        if recorded_trajectory not in {"fly", "line_drive", "pop_fly"}:
            recorded_trajectory = "unknown"
        row: dict[str, object] = {
            "schema_version": "flyball-calibration-manifest-v1",
            "dataset_commit": "local-assignment",
            "audit_id": audit_id,
            "uid": uid,
            "queue_position": position,
            "batch_number": batch_number,
            "batch_position": batch_position,
            "sample_id": sample.sample_id,
            "label": "fly_ball",
            "recorded_trajectory": recorded_trajectory,
            "landing_zone": sample.metadata.get("landing_zone", ""),
            "strength": sample.metadata.get("strength", ""),
            "sample_relpath": sample.relative_directory.as_posix(),
            "audio_relpath": relative_file(sample, "audio.wav"),
            "video_relpath": relative_file(sample, "video.mp4"),
            "csv_relpath": relative_file(sample, "sample.csv"),
            "label_relpath": relative_file(sample, "label.txt"),
            "source_relpath": relative_file(sample, "source.txt"),
            "audio_available": bool_text(audio_exists),
            "audio_readable": bool_text(sample.audio_readable),
            "video_state": "ready_local" if video_exists else "missing",
            "event_start": format_float(sample.event_start),
            "event_end": format_float(sample.event_end),
            "candidate_interval_valid": bool_text(interval_valid),
            "audio_duration_sec": format_float(sample.audio_duration),
            "proposed_contact_time": format_float(proposed_time),
            "proposal_source": "candidate_interval_midpoint" if proposed_time is not None else "",
            "expected_audio_blob_sha1": "",
            "expected_video_blob_sha1": "",
            "expected_csv_blob_sha1": "",
            "expected_label_blob_sha1": "",
            "expected_source_blob_sha1": "",
            "data_issues": "" if audio_exists else "missing_audio",
        }
        manifests.append(row)
        queue.append(
            {
                "schema_version": row["schema_version"],
                "audit_id": audit_id,
                "queue_position": position,
                "batch_number": batch_number,
                "batch_position": batch_position,
                "sample_id": sample.sample_id,
                "audio_available": row["audio_available"],
                "video_state": row["video_state"],
                "event_start": row["event_start"],
                "event_end": row["event_end"],
                "proposed_contact_time": row["proposed_contact_time"],
                "recorded_trajectory": recorded_trajectory,
            }
        )
    return manifests, queue


def write_csv_atomic(path: Path, rows: Iterable[Mapping[str, object]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def prepare_session(args: argparse.Namespace) -> dict[str, object]:
    reviewer = args.reviewer.strip()
    if not REVIEWER_PATTERN.fullmatch(reviewer):
        raise SessionError(
            "审核人代号需为 1–64 个字母、数字、点、下划线或连字符，并以字母或数字开头"
        )
    if not 1 <= args.ground_port <= 65535 or not 1 <= args.fly_port <= 65535:
        raise SessionError("端口必须在 1–65535 之间")

    assignment_path = args.assignment.expanduser().resolve()
    sample_ids, assignment_hash = read_assignment(assignment_path)
    dataset_root = normalize_dataset_root(args.dataset_root)
    ground, fly = resolve_samples(sample_ids, dataset_root)
    if ground and fly and args.ground_port == args.fly_port:
        raise SessionError("混合任务中 Groundball 与 Flyball 端口不能相同")

    reviewer_slug = safe_slug(reviewer, "reviewer")
    assignment_slug = safe_slug(assignment_path.stem, "assignment")
    session_name = f"{assignment_slug}-{assignment_hash[:8]}"
    session_dir = args.output_root.expanduser().resolve() / reviewer_slug / session_name
    generated = session_dir / "generated"

    ground_manifest, ground_queue = ground_rows(ground)
    fly_manifest, fly_queue = fly_rows(fly)
    if ground:
        write_csv_atomic(generated / "groundball_manifest.csv", ground_manifest, GROUND_MANIFEST_FIELDS)
        write_csv_atomic(generated / "groundball_queue.csv", ground_queue, GROUND_QUEUE_FIELDS)
        write_json_atomic(
            generated / "groundball_summary.json",
            {
                "schema_version": "contact-audit-manifest-v1",
                "queue_label_filter": "ground_ball",
                "queue_label_population_count": len(ground),
                "assignment_session": True,
            },
        )
    if fly:
        write_csv_atomic(generated / "flyball_manifest.csv", fly_manifest, FLY_MANIFEST_FIELDS)
        write_csv_atomic(generated / "flyball_queue.csv", fly_queue, FLY_QUEUE_FIELDS)
        write_json_atomic(
            generated / "flyball_summary.json",
            {
                "schema_version": "flyball-calibration-manifest-v1",
                "assignment_session": True,
                "candidate_count": len(fly),
            },
        )

    normalized_assignment = session_dir / "assignment.txt"
    normalized_assignment.parent.mkdir(parents=True, exist_ok=True)
    normalized_assignment.write_text("\n".join(sample_ids) + "\n", encoding="utf-8")
    session = {
        "session_schema_version": "team-review-session-v1",
        "reviewer_id": reviewer,
        "assignment_name": assignment_path.name,
        "assignment_sha256": assignment_hash,
        "sample_count": len(sample_ids),
        "groundball_count": len(ground),
        "flyball_count": len(fly),
        "ground_port": args.ground_port if ground else None,
        "fly_port": args.fly_port if fly else None,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    write_json_atomic(session_dir / "session.json", session)
    return {
        **session,
        "session_dir": session_dir,
        "dataset_root": dataset_root,
        "generated_dir": generated,
        "has_ground": bool(ground),
        "has_fly": bool(fly),
    }


def count_csv_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def export_bundle(session: Mapping[str, object]) -> Path:
    session_dir = Path(session["session_dir"])
    summary = {
        "reviewer_id": session["reviewer_id"],
        "assignment_name": session["assignment_name"],
        "assignment_sha256": session["assignment_sha256"],
        "assigned_sample_count": session["sample_count"],
        "groundball_review_count": count_csv_rows(session_dir / "groundball_reviews.csv"),
        "flyball_review_count": count_csv_rows(session_dir / "flyball_reviews.csv"),
        "exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    write_json_atomic(session_dir / "review_summary.json", summary)
    archive = session_dir / "review_result_bundle.zip"
    temporary = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for filename in (
            "assignment.txt",
            "session.json",
            "review_summary.json",
            "groundball_reviews.csv",
            "flyball_reviews.csv",
        ):
            candidate = session_dir / filename
            if candidate.is_file():
                bundle.write(candidate, arcname=filename)
    temporary.replace(archive)
    return archive


def launch_servers(args: argparse.Namespace, session: Mapping[str, object]) -> int:
    generated = Path(session["generated_dir"])
    session_dir = Path(session["session_dir"])
    dataset_root = Path(session["dataset_root"])
    processes: list[subprocess.Popen[bytes]] = []

    if session["has_ground"]:
        command = [
            sys.executable,
            str(TOOL_ROOT / "groundball" / "owner_validation_server.py"),
            "--admin-manifest",
            str(generated / "groundball_manifest.csv"),
            "--queue",
            str(generated / "groundball_queue.csv"),
            "--manifest-summary",
            str(generated / "groundball_summary.json"),
            "--results",
            str(session_dir / "groundball_reviews.csv"),
            "--legacy-results",
            str(session_dir / "no_legacy_reviews.csv"),
            "--dataset-root",
            str(dataset_root),
            "--reviewer-id",
            str(session["reviewer_id"]),
            "--port",
            str(args.ground_port),
        ]
        if args.no_browser:
            command.append("--no-browser")
        processes.append(subprocess.Popen(command, cwd=TOOL_ROOT / "groundball"))

    if session["has_fly"]:
        command = [
            sys.executable,
            str(TOOL_ROOT / "flyball" / "server.py"),
            "--manifest",
            str(generated / "flyball_manifest.csv"),
            "--queue",
            str(generated / "flyball_queue.csv"),
            "--summary",
            str(generated / "flyball_summary.json"),
            "--results",
            str(session_dir / "flyball_reviews.csv"),
            "--dataset-root",
            str(dataset_root),
            "--reviewer-id",
            str(session["reviewer_id"]),
            "--port",
            str(args.fly_port),
        ]
        if args.no_browser:
            command.append("--no-browser")
        processes.append(subprocess.Popen(command, cwd=TOOL_ROOT / "flyball"))

    try:
        while processes:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    return return_code
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        session = prepare_session(args)
    except SessionError as error:
        print(f"任务准备失败：\n{error}", file=sys.stderr)
        return 2

    print(
        f"已准备 {session['sample_count']} 条："
        f"Groundball {session['groundball_count']}，Flyball {session['flyball_count']}"
    )
    print(f"审核结果目录：{session['session_dir']}")
    if args.prepare_only:
        archive = export_bundle(session)
        print(f"准备检查完成：{archive}")
        return 0

    return_code = launch_servers(args, session)
    archive = export_bundle(session)
    print(f"结果包已更新：{archive}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
