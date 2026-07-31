from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
VALID_TRAJECTORIES = {"fly", "pop_fly", "line_drive"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def bool_value(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def update_sample_csv(
    path: Path,
    *,
    event_start: str,
    event_end: str,
    trajectory_type: str,
) -> None:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if len(rows) != 1:
        raise ValueError(f"{path} must contain exactly one data row")
    rows[0]["event_start"] = event_start
    rows[0]["event_end"] = event_end
    if trajectory_type:
        rows[0]["trajectory_type"] = trajectory_type
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def update_source_txt(
    path: Path,
    *,
    clip_start: str,
    clip_end: str,
) -> None:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    values: dict[str, str] = {}
    order: list[str] = []
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key not in values:
            order.append(key)
        values[key] = value.strip()
    values["clip_start_time"] = clip_start
    values["clip_end_time"] = clip_end
    source_id = values.get("source_id", "source")
    values["clip_id"] = (
        f"{source_id}_reclean_{clip_start.replace('.', 'p')}_{clip_end.replace('.', 'p')}"
    )
    for required in ("clip_id", "clip_start_time", "clip_end_time"):
        if required not in order:
            order.append(required)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        "\n".join(f"{key}: {values[key]}" for key in order) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def acceptance_reason(
    row: dict[str, str],
    contact_gate: dict[str, str] | None,
    minimum_confidence: float,
) -> tuple[bool, str]:
    if row.get("binding_status") != "audio_candidate_bound":
        return False, row.get("binding_status") or "missing_qwen_result"
    required_true = [
        "contact_audible",
        "contact_visible",
        "live_play",
        "fly_ball_semantics",
        "full_play_visible",
    ]
    failed = [field for field in required_true if not bool_value(row.get(field))]
    if failed:
        return False, "failed_gate:" + ",".join(failed)
    if bool_value(row.get("replay_or_slow_motion")):
        return False, "replay_or_slow_motion"
    if row.get("trajectory_type") not in VALID_TRAJECTORIES:
        return False, "invalid_qwen_trajectory"
    if float_value(row.get("confidence")) < minimum_confidence:
        return False, "qwen_confidence_below_threshold"
    if not row.get("final_event_start") or not row.get("final_event_end"):
        return False, "missing_bound_event_interval"
    if contact_gate is None:
        return False, "missing_contact_gate_result"
    if contact_gate.get("contact_gate_status") != "contact_gate_pass":
        return False, contact_gate.get("contact_gate_status") or "contact_gate_not_passed"
    if contact_gate.get("model") == row.get("model"):
        return False, "contact_gate_not_independent"
    if (
        abs(
            float_value(contact_gate.get("selected_candidate_time"))
            - float_value(row.get("selected_candidate_time"))
        )
        > 0.030
    ):
        return False, "contact_gate_candidate_mismatch"
    if float_value(contact_gate.get("relative_audio_visual_offset"), 999.0) > 0.30:
        return False, "contact_gate_audio_visual_mismatch"
    if float_value(contact_gate.get("confidence")) < minimum_confidence:
        return False, "contact_gate_confidence_below_threshold"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize one verified fly-ball repair batch.")
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--recut-manifest", type=Path, required=True)
    parser.add_argument("--qwen-summary", type=Path, required=True)
    parser.add_argument("--contact-gate-summary", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--minimum-confidence", type=float, default=0.80)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    queue = read_csv(args.queue)
    recuts = {
        row["main_relative_path"]: row for row in read_csv(args.recut_manifest)
    }
    qwen = {
        row["main_relative_path"]: row for row in read_csv(args.qwen_summary)
    }
    contact_gate = {
        row["main_relative_path"]: row
        for row in read_csv(args.contact_gate_summary)
    }
    reconciled: list[dict[str, Any]] = []

    for row in queue:
        relative_path = row["main_relative_path"]
        sample_dir = REPO_ROOT / relative_path
        recut = recuts.get(relative_path)
        review = qwen.get(relative_path)
        gate = contact_gate.get(relative_path)
        if review is None:
            accepted, reason = False, "missing_qwen_result"
        else:
            accepted, reason = acceptance_reason(
                review,
                gate,
                args.minimum_confidence,
            )
        before_video = sample_dir / "video.mp4"
        before_audio = sample_dir / "audio.wav"
        before_video_hash = sha256(before_video) if before_video.is_file() else ""
        before_audio_hash = sha256(before_audio) if before_audio.is_file() else ""
        before_trajectory = row.get("trajectory_type", "")
        proposed_trajectory = review.get("trajectory_type", "") if review else ""
        # The contact gate verifies timing and live contact, not ball-flight
        # semantics. Preserve existing trajectory metadata unless it receives a
        # separate manual or dedicated trajectory adjudication.
        after_trajectory = before_trajectory
        if accepted and recut:
            recut_video = Path(recut["video_path"])
            recut_audio = Path(recut["audio_path"])
            if (
                recut.get("status") not in {"recut_complete", "recut_partial_context"}
                or not recut_video.is_file()
                or not recut_audio.is_file()
            ):
                accepted = False
                reason = "recut_media_not_ready"
        if accepted and args.apply:
            if recut:
                atomic_copy(Path(recut["video_path"]), before_video)
                atomic_copy(Path(recut["audio_path"]), before_audio)
                update_source_txt(
                    sample_dir / "source.txt",
                    clip_start=recut["new_clip_start"],
                    clip_end=recut["new_clip_end"],
                )
            update_sample_csv(
                sample_dir / "sample.csv",
                event_start=review["final_event_start"],
                event_end=review["final_event_end"],
                trajectory_type=after_trajectory,
            )

        if not accepted:
            action = "unchanged_unresolved"
        elif recut:
            action = "recut_and_retime"
        else:
            action = "retime_or_metadata_only"
        changed = accepted and (
            bool(recut)
            or review["final_event_start"] != row["current_event_start"]
            or review["final_event_end"] != row["current_event_end"]
            or after_trajectory != before_trajectory
        )
        after_video_hash = (
            sha256(before_video) if args.apply and accepted and before_video.is_file() else ""
        )
        after_audio_hash = (
            sha256(before_audio) if args.apply and accepted and before_audio.is_file() else ""
        )
        reconciled.append(
            {
                "repair_batch": row["repair_batch"],
                "repair_batch_index": row["repair_batch_index"],
                "collector": row["collector"],
                "sample_id": row["sample_id"],
                "main_relative_path": relative_path,
                "primary_error": row["primary_error"],
                "result": action,
                "changed": "yes" if changed else "no",
                "unresolved_reason": reason,
                "before_event_start": row["current_event_start"],
                "before_event_end": row["current_event_end"],
                "after_event_start": review.get("final_event_start", "") if accepted else "",
                "after_event_end": review.get("final_event_end", "") if accepted else "",
                "selected_candidate_time": (
                    review.get("selected_candidate_time", "") if review else ""
                ),
                "visual_contact_time": (
                    review.get("visual_contact_time", "") if review else ""
                ),
                "audio_visual_offset": (
                    review.get("audio_visual_offset", "") if review else ""
                ),
                "before_duration": row.get("video_duration", ""),
                "after_duration": recut.get("new_duration", "") if accepted and recut else row.get("video_duration", ""),
                "recut_status": recut.get("status", "") if recut else "not_required",
                "source_clip_start_before": row.get("source_clip_start", ""),
                "source_clip_start_after": recut.get("new_clip_start", "") if accepted and recut else "",
                "source_clip_end_after": recut.get("new_clip_end", "") if accepted and recut else "",
                "before_trajectory": before_trajectory,
                "after_trajectory": after_trajectory if accepted else "",
                "trajectory_changed": "no",
                "qwen_proposed_trajectory": proposed_trajectory,
                "trajectory_change_suppressed": (
                    "yes"
                    if accepted
                    and proposed_trajectory
                    and proposed_trajectory != before_trajectory
                    else "no"
                ),
                "qwen_binding_status": review.get("binding_status", "") if review else "",
                "qwen_confidence": review.get("confidence", "") if review else "",
                "qwen_model": review.get("model", "") if review else "",
                "contact_gate_status": gate.get("contact_gate_status", "") if gate else "",
                "contact_gate_decision": gate.get("decision", "") if gate else "",
                "contact_gate_contact_visible": gate.get("contact_visible", "") if gate else "",
                "contact_gate_live_pitch_and_swing_visible": (
                    gate.get("live_pitch_and_swing_visible", "") if gate else ""
                ),
                "contact_gate_candidate_sound_is_bat_contact": (
                    gate.get("candidate_sound_is_bat_contact", "") if gate else ""
                ),
                "contact_gate_replay_or_slow_motion": (
                    gate.get("replay_or_slow_motion", "") if gate else ""
                ),
                "contact_gate_confidence": gate.get("confidence", "") if gate else "",
                "contact_gate_model": gate.get("model", "") if gate else "",
                "contact_gate_visual_evidence": gate.get("visual_evidence", "") if gate else "",
                "contact_gate_audio_evidence": gate.get("audio_evidence", "") if gate else "",
                "contact_gate_failure_reason": gate.get("failure_reason", "") if gate else "",
                "before_video_sha256": before_video_hash,
                "before_audio_sha256": before_audio_hash,
                "after_video_sha256": after_video_hash,
                "after_audio_sha256": after_audio_hash,
                "apply_mode": "applied" if args.apply else "dry_run",
            }
        )

    write_csv(args.output_csv, reconciled)
    result_counts = Counter(row["result"] for row in reconciled)
    error_counts = Counter(row["primary_error"] for row in reconciled)
    changed_count = sum(row["changed"] == "yes" for row in reconciled)
    trajectory_suppressed_count = sum(
        row["trajectory_change_suppressed"] == "yes" for row in reconciled
    )
    contact_gate_pass_count = sum(
        row["contact_gate_status"] == "contact_gate_pass" for row in reconciled
    )
    contact_gate_reject_count = sum(
        row["contact_gate_status"] == "contact_gate_reject" for row in reconciled
    )
    gate_no_visual_contact = sum(
        row["contact_gate_status"] == "contact_gate_reject"
        and not bool_value(row["contact_gate_contact_visible"])
        for row in reconciled
    )
    gate_no_live_sequence = sum(
        row["contact_gate_status"] == "contact_gate_reject"
        and not bool_value(row["contact_gate_live_pitch_and_swing_visible"])
        for row in reconciled
    )
    gate_no_bat_sound = sum(
        row["contact_gate_status"] == "contact_gate_reject"
        and not bool_value(row["contact_gate_candidate_sound_is_bat_contact"])
        for row in reconciled
    )
    gate_replay = sum(
        row["contact_gate_status"] == "contact_gate_reject"
        and bool_value(row["contact_gate_replay_or_slow_motion"])
        for row in reconciled
    )
    complete_recut = sum(
        row["result"] == "recut_and_retime" and row["recut_status"] == "recut_complete"
        for row in reconciled
    )
    partial_recut = sum(
        row["result"] == "recut_and_retime"
        and row["recut_status"] == "recut_partial_context"
        for row in reconciled
    )
    lines = [
        "# Fly Ball 批次写入报告",
        "",
        f"- 模式：{'已写入' if args.apply else '仅检查'}",
        f"- 队列总数：{len(reconciled)}",
        f"- 实际修改：{changed_count}",
        f"- 重新剪辑并校时：{result_counts['recut_and_retime']}",
        f"- 仅校时或修改元数据：{result_counts['retime_or_metadata_only']}",
        f"- 保持原样、等待后续处理：{result_counts['unchanged_unresolved']}",
        f"- 完整上下文复剪通过：{complete_recut}",
        f"- 部分上下文经画面复核后通过：{partial_recut}",
        f"- 千问提出但未自动写入的球路变化：{trajectory_suppressed_count}",
        f"- 独立击球短片复核通过：{contact_gate_pass_count}",
        f"- 独立击球短片复核拒绝：{contact_gate_reject_count}",
        f"- 拒绝原因包含无可见击球：{gate_no_visual_contact}",
        f"- 拒绝原因包含无完整现场投球/挥棒：{gate_no_live_sequence}",
        f"- 拒绝原因包含无球棒击球声：{gate_no_bat_sound}",
        f"- 拒绝原因包含回放或慢动作：{gate_replay}",
        "",
        "## 原始错误分类",
        "",
        *[f"- {name}: {count}" for name, count in error_counts.most_common()],
        "",
        "## 已修改样本",
        "",
        "| 样本 | 结果 | 修改前击球区间 | 修改后击球区间 | 原时长 | 新时长 | 球路 |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in reconciled:
        if row["changed"] == "yes":
            lines.append(
                f"| {row['sample_id']} | {row['result']} | "
                f"{row['before_event_start']}-{row['before_event_end']} | "
                f"{row['after_event_start']}-{row['after_event_end']} | "
                f"{row['before_duration']} | {row['after_duration']} | "
                f"{row['before_trajectory']} -> {row['after_trajectory']} |"
            )
    lines.extend(
        [
            "",
            "## 保持原样、等待后续处理的样本",
            "",
            "| 样本 | 原始错误 | 当前原因 |",
            "| --- | --- | --- |",
        ]
    )
    for row in reconciled:
        if row["result"] == "unchanged_unresolved":
            lines.append(
                f"| {row['sample_id']} | {row['primary_error']} | {row['unresolved_reason']} |"
            )
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"mode={'apply' if args.apply else 'dry_run'} queue={len(reconciled)} "
        f"changed={changed_count} unresolved={result_counts['unchanged_unresolved']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
