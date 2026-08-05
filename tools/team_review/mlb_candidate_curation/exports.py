"""Deterministic audit and task-manifest exports from flat-file reviews."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


class ReviewConflictError(RuntimeError):
    """Raised when two batches claim different current results for one play."""


@dataclass(frozen=True)
class WindowPolicy:
    pre_contact_sec: float = 1.0
    post_contact_sec: float = 0.5
    version: str = "initial-trajectory-window-v1"

    def validate(self) -> None:
        if self.pre_contact_sec < 0 or self.post_contact_sec < 0:
            raise ValueError("window durations cannot be negative")
        if not self.version.strip():
            raise ValueError("window policy version cannot be blank")


AUDIT_FIELDS = [
    "source_play_id",
    "game_pk",
    "play_id",
    "game_date",
    "game_info",
    "batter",
    "pitcher",
    "play_description",
    "mlb_trajectory_raw",
    "mlb_location_raw",
    "source_page_url",
    "video_relpath",
    "audio_relpath",
    "media_duration_sec",
    "batch_id",
    "admission_status",
    "exclusion_reason",
    "observed_trajectory",
    "derived_ground_fly_label",
    "reviewed_location",
    "location_source",
    "proposed_hit_time",
    "reviewed_hit_time",
    "hit_time_source",
    "contact_eligible",
    "ground_fly_eligible",
    "location_eligible",
    "broken_bat",
    "reviewer_id",
    "notes",
    "reviewed_at_utc",
]

TASK_FIELDS = [
    "source_play_id",
    "game_pk",
    "game_date",
    "video_relpath",
    "audio_relpath",
    "media_duration_sec",
    "reviewed_hit_time",
    "input_window_start_sec",
    "input_window_end_sec",
    "window_policy_version",
    "target",
    "observed_trajectory",
    "reviewed_location",
    "batch_id",
]


def _text(row: Mapping[str, object], field: str) -> str:
    return str(row.get(field) or "").strip()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_review_batches(review_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not review_dir.is_dir():
        return rows
    for path in sorted(review_dir.glob("*.csv")):
        rows.extend(read_csv_rows(path))
    return merge_review_batches(rows)


def merge_review_batches(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for raw in rows:
        row = {str(key): _text(raw, str(key)) for key in raw}
        source_play_id = row.get("source_play_id", "")
        if not source_play_id:
            raise ReviewConflictError("review row has blank source_play_id")
        existing = merged.get(source_play_id)
        if existing is None:
            merged[source_play_id] = row
            continue
        comparable_fields = sorted(
            (set(existing) | set(row))
            - {"reviewed_at_utc", "reviewer_id", "batch_id"}
        )
        conflicts = [
            field
            for field in comparable_fields
            if existing.get(field, "") != row.get(field, "")
        ]
        if conflicts:
            batches = f"{existing.get('batch_id', '?')} / {row.get('batch_id', '?')}"
            raise ReviewConflictError(
                f"{source_play_id} conflicts across batches {batches}: "
                + ", ".join(conflicts)
            )
        provenance = sorted(
            {
                value
                for value in [
                    existing.get("batch_id", ""),
                    row.get("batch_id", ""),
                ]
                if value
            }
        )
        existing["batch_id"] = "+".join(provenance)
    return sorted(
        merged.values(),
        key=lambda row: (row.get("reviewed_at_utc", ""), row["source_play_id"]),
    )


def build_exports(
    inventory_rows: Iterable[Mapping[str, object]],
    review_rows: Iterable[Mapping[str, object]],
    policy: WindowPolicy | None = None,
) -> dict[str, list[dict[str, object]]]:
    policy = policy or WindowPolicy()
    policy.validate()
    inventory = {
        _text(row, "source_play_id"): dict(row)
        for row in inventory_rows
        if _text(row, "source_play_id")
    }
    reviews = merge_review_batches(review_rows)
    audit: list[dict[str, object]] = []
    contact: list[dict[str, object]] = []
    ground_fly: list[dict[str, object]] = []
    location: list[dict[str, object]] = []

    for review in reviews:
        source_play_id = review["source_play_id"]
        if source_play_id not in inventory:
            raise ReviewConflictError(
                f"review references missing inventory row: {source_play_id}"
            )
        source = inventory[source_play_id]
        combined = {**source, **review, "source_play_id": source_play_id}
        audit.append({field: combined.get(field, "") for field in AUDIT_FIELDS})
        if review.get("admission_status") != "admitted":
            continue
        try:
            hit_time = float(review["reviewed_hit_time"])
            duration = float(source["media_duration_sec"])
        except (KeyError, TypeError, ValueError) as error:
            raise ReviewConflictError(
                f"admitted row lacks valid timing: {source_play_id}"
            ) from error
        window_start = max(0.0, hit_time - policy.pre_contact_sec)
        window_end = min(duration, hit_time + policy.post_contact_sec)
        common: dict[str, object] = {
            "source_play_id": source_play_id,
            "game_pk": source.get("game_pk", ""),
            "game_date": source.get("game_date", ""),
            "video_relpath": source.get("video_relpath", ""),
            "audio_relpath": source.get("audio_relpath", ""),
            "media_duration_sec": duration,
            "reviewed_hit_time": hit_time,
            "input_window_start_sec": round(window_start, 6),
            "input_window_end_sec": round(window_end, 6),
            "window_policy_version": policy.version,
            "observed_trajectory": review.get("observed_trajectory", ""),
            "reviewed_location": review.get("reviewed_location", ""),
            "batch_id": review.get("batch_id", ""),
        }
        if review.get("contact_eligible", "").lower() == "true":
            contact.append({**common, "target": "bat_ball_contact"})
        if review.get("ground_fly_eligible", "").lower() == "true":
            ground_fly.append(
                {
                    **common,
                    "target": review.get("derived_ground_fly_label", ""),
                }
            )
        if review.get("location_eligible", "").lower() == "true":
            location.append(
                {
                    **common,
                    "target": review.get("reviewed_location", ""),
                }
            )
    return {
        "audit_combined": audit,
        "contact_manifest": contact,
        "ground_fly_manifest": ground_fly,
        "location_manifest": location,
    }


def atomic_write_csv(
    path: Path,
    fields: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fields})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_exports(output_dir: Path, exports: Mapping[str, list[dict]]) -> None:
    atomic_write_csv(
        output_dir / "audit_combined.csv",
        AUDIT_FIELDS,
        exports["audit_combined"],
    )
    for name in [
        "contact_manifest",
        "ground_fly_manifest",
        "location_manifest",
    ]:
        atomic_write_csv(output_dir / f"{name}.csv", TASK_FIELDS, exports[name])
