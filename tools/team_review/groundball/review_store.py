#!/usr/bin/env python3
"""Atomic CSV persistence for the single-reviewer contact audit workbench."""

from __future__ import annotations

import csv
import io
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


REVIEW_SCHEMA_VERSION = "contact-audit-review-v1"
REVIEW_STATUSES = {
    "pass",
    "corrected_pass",
    "no_contact",
    "material_issue",
    "uncertain",
}
MATERIAL_REASONS = {
    "video_missing_or_unplayable",
    "audio_missing_or_unplayable",
    "audio_video_different_event",
    "sync_anomaly",
    "wrong_content",
    "other",
}
RESULT_FIELDS = [
    "review_schema_version",
    "manifest_schema_version",
    "audit_id",
    "uid",
    "queue_position",
    "sample_relpath",
    "review_status",
    "material_reason",
    "auto_hit_time",
    "hit_time_override",
    "effective_hit_time",
    "effective_hit_source",
    "notes",
    "reviewed_at_utc",
]


class ReviewValidationError(ValueError):
    """Raised when a submitted or stored review violates the review contract."""


def optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ReviewValidationError("boolean is not a valid time")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ReviewValidationError(f"invalid numeric value: {value!r}") from error
    if not math.isfinite(parsed):
        raise ReviewValidationError("time must be finite")
    return parsed


def format_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.9f}".rstrip("0").rstrip(".")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReviewStore:
    """One CSV file, rewritten atomically after each explicit review decision."""

    def __init__(
        self,
        path: Path,
        manifest_rows: Iterable[Mapping[str, str]],
        queue_rows: Iterable[Mapping[str, str]],
    ) -> None:
        self.path = path.resolve()
        self._manifest = {row["audit_id"]: dict(row) for row in manifest_rows}
        self._queue_positions = {
            row["audit_id"]: int(row["queue_position"]) for row in queue_rows
        }
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    @property
    def total(self) -> int:
        return len(self._queue_positions)

    def get(self, audit_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(audit_id)
            return dict(record) if record else None

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(self._records[audit_id])
                for audit_id in sorted(
                    self._records,
                    key=lambda item: self._queue_positions[item],
                )
            ]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            status_counts = {status: 0 for status in sorted(REVIEW_STATUSES)}
            for record in self._records.values():
                status_counts[record["review_status"]] += 1
            reviewed = len(self._records)
            return {
                "total": self.total,
                "reviewed": reviewed,
                "remaining": self.total - reviewed,
                "status_counts": status_counts,
                "results_file_exists": self.path.is_file(),
            }

    def upsert(self, audit_id: str, payload: Mapping[str, object]) -> dict[str, Any]:
        with self._lock:
            if audit_id not in self._queue_positions or audit_id not in self._manifest:
                raise ReviewValidationError("audit ID is not in the review queue")

            manifest = self._manifest[audit_id]
            status = str(payload.get("review_status", "")).strip()
            if status not in REVIEW_STATUSES:
                raise ReviewValidationError("unknown review status")

            notes = str(payload.get("notes", "") or "").strip()
            if len(notes) > 1000:
                raise ReviewValidationError("notes must be 1000 characters or fewer")

            auto_hit_time = optional_float(manifest.get("auto_hit_time"))
            override = optional_float(payload.get("hit_time_override"))
            duration = optional_float(manifest.get("audio_duration_sec"))
            material_reason = str(payload.get("material_reason", "") or "").strip()

            if override is not None:
                if override < 0:
                    raise ReviewValidationError("hit-time override cannot be negative")
                if duration is not None and override > duration:
                    raise ReviewValidationError("hit-time override exceeds audio duration")

            if status == "pass":
                if auto_hit_time is None:
                    raise ReviewValidationError(
                        "pass requires an automatic hit time; set one point and use corrected pass"
                    )
                override = None
                material_reason = ""
                effective_hit_time = auto_hit_time
                effective_hit_source = "automatic"
            elif status == "corrected_pass":
                if override is None:
                    raise ReviewValidationError(
                        "corrected pass requires one hit-time override"
                    )
                material_reason = ""
                effective_hit_time = override
                effective_hit_source = "human_override"
            elif status == "material_issue":
                if material_reason not in MATERIAL_REASONS:
                    raise ReviewValidationError(
                        "material issue requires an explicit reason"
                    )
                override = None
                effective_hit_time = None
                effective_hit_source = ""
            else:
                material_reason = ""
                override = None
                effective_hit_time = None
                effective_hit_source = ""

            record: dict[str, Any] = {
                "review_schema_version": REVIEW_SCHEMA_VERSION,
                "manifest_schema_version": manifest["schema_version"],
                "audit_id": audit_id,
                "uid": manifest["uid"],
                "queue_position": self._queue_positions[audit_id],
                "sample_relpath": manifest["sample_relpath"],
                "review_status": status,
                "material_reason": material_reason,
                "auto_hit_time": auto_hit_time,
                "hit_time_override": override,
                "effective_hit_time": effective_hit_time,
                "effective_hit_source": effective_hit_source,
                "notes": notes,
                "reviewed_at_utc": utc_now(),
            }
            self._records[audit_id] = record
            self._write_atomic()
            return dict(record)

    def remove(self, audit_id: str) -> bool:
        with self._lock:
            existed = self._records.pop(audit_id, None) is not None
            if existed:
                self._write_atomic()
            return existed

    def export_bytes(self) -> bytes:
        with self._lock:
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            for record in self.records():
                writer.writerow(self._serializable_record(record))
            return ("\ufeff" + buffer.getvalue()).encode("utf-8")

    def _load(self) -> None:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        seen: set[str] = set()
        for row in rows:
            if row.get("review_schema_version") != REVIEW_SCHEMA_VERSION:
                raise ReviewValidationError("unsupported review schema version")
            audit_id = row.get("audit_id", "")
            if audit_id in seen:
                raise ReviewValidationError(f"duplicate review row: {audit_id}")
            if audit_id not in self._queue_positions or audit_id not in self._manifest:
                raise ReviewValidationError(
                    f"stored review is not in the current queue: {audit_id}"
                )
            seen.add(audit_id)
            self._records[audit_id] = {
                "review_schema_version": REVIEW_SCHEMA_VERSION,
                "manifest_schema_version": row["manifest_schema_version"],
                "audit_id": audit_id,
                "uid": row["uid"],
                "queue_position": int(row["queue_position"]),
                "sample_relpath": row["sample_relpath"],
                "review_status": row["review_status"],
                "material_reason": row["material_reason"],
                "auto_hit_time": optional_float(row["auto_hit_time"]),
                "hit_time_override": optional_float(row["hit_time_override"]),
                "effective_hit_time": optional_float(row["effective_hit_time"]),
                "effective_hit_source": row["effective_hit_source"],
                "notes": row["notes"],
                "reviewed_at_utc": row["reviewed_at_utc"],
            }
            if self._records[audit_id]["review_status"] not in REVIEW_STATUSES:
                raise ReviewValidationError(f"unknown stored status for {audit_id}")

    def _serializable_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        serialized = dict(record)
        for field in ("auto_hit_time", "hit_time_override", "effective_hit_time"):
            serialized[field] = format_float(record.get(field))
        return serialized

    def _write_atomic(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
                writer.writeheader()
                for record in self.records():
                    writer.writerow(self._serializable_record(record))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
