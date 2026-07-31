"""Atomic owner-form persistence with read-only legacy review display."""

from __future__ import annotations

import csv
import io
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from contracts import (
    CHECK_VALUES,
    CONCLUSIONS,
    ERROR_CODES,
    FORMAL_CONCLUSIONS,
    LEGACY_REVIEW_SCHEMA_VERSION,
    LEGACY_STATUSES,
    REVIEW_SCHEMA_VERSION,
)


RESULT_FIELDS = [
    "review_schema_version",
    "manifest_schema_version",
    "audit_id",
    "uid",
    "queue_position",
    "batch_number",
    "batch_position",
    "sample_id",
    "sample_relpath",
    "reviewer_id",
    "conclusion",
    "counts_toward_quota",
    "contains_contact",
    "original_time_correct",
    "event_start",
    "event_end",
    "proposed_contact_time",
    "correct_contact_time",
    "effective_contact_time",
    "contact_time_source",
    "full_process",
    "replay",
    "error_codes",
    "notes",
    "legacy_review_status",
    "legacy_reviewed_at_utc",
    "reviewed_at_utc",
]


class ReviewValidationError(ValueError):
    """Raised when a new-form review violates the owner contract."""


def optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        raise ReviewValidationError("正确击球秒必须是数值")
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as error:
        raise ReviewValidationError("正确击球秒必须是数值") from error
    if not math.isfinite(parsed):
        raise ReviewValidationError("正确击球秒必须是有限数值")
    return parsed


def format_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.9f}".rstrip("0").rstrip(".")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_codes(value: object) -> list[str]:
    if isinstance(value, str):
        candidates = value.replace(",", ";").split(";")
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(item) for item in value]
    else:
        candidates = []
    codes = {candidate.strip().upper() for candidate in candidates if candidate}
    unknown = sorted(codes - set(ERROR_CODES))
    if unknown:
        raise ReviewValidationError(f"未知错误代码：{', '.join(unknown)}")
    return [code for code in ERROR_CODES if code in codes]


class ValidationStore:
    """One new CSV plus one read-only legacy CSV for normal browsing."""

    def __init__(
        self,
        path: Path,
        legacy_path: Path,
        manifest_rows: Iterable[Mapping[str, str]],
        queue_rows: Iterable[Mapping[str, str]],
    ) -> None:
        self.path = path.resolve()
        self.legacy_path = legacy_path.resolve()
        self._manifest = {row["audit_id"]: dict(row) for row in manifest_rows}
        self._queue_positions = {
            row["audit_id"]: int(row["queue_position"]) for row in queue_rows
        }
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._legacy: dict[str, dict[str, Any]] = {}
        self._load_new()
        self._load_legacy()

    @property
    def total(self) -> int:
        return len(self._queue_positions)

    def get(self, audit_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(audit_id)
            return dict(record) if record else None

    def get_legacy(self, audit_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._legacy.get(audit_id)
            if not record:
                return None
            return {
                "review_schema_version": record["review_schema_version"],
                "review_status": record["review_status"],
                "material_reason": record.get("material_reason", ""),
                "auto_hit_time": record.get("auto_hit_time"),
                "hit_time_override": record.get("hit_time_override"),
                "effective_hit_time": record.get("effective_hit_time"),
                "effective_hit_source": record.get("effective_hit_source", ""),
                "notes": record.get("notes", ""),
                "reviewed_at_utc": record.get("reviewed_at_utc", ""),
            }

    def state_for(self, audit_id: str) -> str:
        with self._lock:
            if audit_id in self._records:
                return "current"
            if audit_id in self._legacy:
                return "legacy"
            return "untouched"

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(record)
                for record in sorted(
                    self._records.values(),
                    key=lambda item: int(item["queue_position"]),
                )
            ]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            counts = {conclusion: 0 for conclusion in CONCLUSIONS}
            for record in self._records.values():
                counts[record["conclusion"]] += 1
            visited_ids = set(self._legacy) | set(self._records)
            legacy_without_new = set(self._legacy) - set(self._records)
            formal = sum(counts[value] for value in FORMAL_CONCLUSIONS)
            return {
                "total": self.total,
                "visited": len(visited_ids),
                "remaining": self.total - len(visited_ids),
                "new_records": len(self._records),
                "formal_reviewed": formal,
                "discarded": counts["D"],
                "legacy_total": len(self._legacy),
                "legacy_without_new": len(legacy_without_new),
                "conclusion_counts": counts,
                "results_file_exists": self.path.is_file(),
                "legacy_file_exists": self.legacy_path.is_file(),
            }

    def upsert(self, audit_id: str, payload: Mapping[str, object]) -> dict[str, Any]:
        with self._lock:
            if audit_id not in self._queue_positions or audit_id not in self._manifest:
                raise ReviewValidationError("审核 ID 不在当前 Groundball 队列中")

            manifest = self._manifest[audit_id]
            reviewer_id = str(payload.get("reviewer_id", "") or "").strip()
            if len(reviewer_id) > 100:
                raise ReviewValidationError("标注者 ID 不能超过 100 字")

            conclusion = str(payload.get("conclusion", "") or "").strip().upper()
            if conclusion not in CONCLUSIONS:
                raise ReviewValidationError("结论必须是 V、I 或舍弃")

            notes = str(payload.get("notes", "") or "").strip()
            if len(notes) > 2000:
                raise ReviewValidationError("备注不能超过 2000 字")
            codes = normalize_codes(payload.get("error_codes"))

            checks: dict[str, str] = {}
            labels = {
                "contains_contact": "包含击球点",
                "original_time_correct": "原时间正确",
                "full_process": "视频前后完整",
                "replay": "回放",
            }
            for field, label in labels.items():
                value = str(payload.get(field, "") or "").strip().upper()
                if conclusion in FORMAL_CONCLUSIONS and value not in CHECK_VALUES:
                    raise ReviewValidationError(f"{label}必须填写 Y 或 N")
                if conclusion == "D" and value not in CHECK_VALUES:
                    value = ""
                checks[field] = value

            contact_time = optional_float(payload.get("correct_contact_time"))
            duration = optional_float(manifest.get("audio_duration_sec"))
            if contact_time is not None:
                if contact_time < 0:
                    raise ReviewValidationError("正确击球秒不能小于 0")
                if duration is not None and contact_time > duration:
                    raise ReviewValidationError("正确击球秒不能超过样本时长")

            if conclusion == "D":
                if not notes:
                    raise ReviewValidationError("舍弃样本必须写明无法判断的原因")
                codes = []
                contact_time = None
            elif conclusion == "V":
                expected = {
                    "contains_contact": "Y",
                    "original_time_correct": "Y",
                    "full_process": "Y",
                    "replay": "N",
                }
                if any(checks[field] != value for field, value in expected.items()):
                    raise ReviewValidationError(
                        "V 有效要求包含击球点、原时间正确、视频前后完整为 Y，回放为 N"
                    )
                if codes:
                    raise ReviewValidationError("V 有效不能包含错误代码")
            else:
                if not codes:
                    raise ReviewValidationError("I 无效必须选择至少一个错误代码")
                if checks["contains_contact"] == "N" and "E01" not in codes:
                    raise ReviewValidationError("包含击球点为 N 时必须选择 E01")
                if (
                    checks["contains_contact"] == "Y"
                    and checks["original_time_correct"] == "N"
                ):
                    if "E02" not in codes:
                        raise ReviewValidationError("原时间错误时必须选择 E02")
                    if contact_time is None:
                        raise ReviewValidationError(
                            "有击球但原时间错误时必须填写正确击球秒"
                        )
                if (
                    checks["contains_contact"] == "Y"
                    and checks["full_process"] == "N"
                    and not any(code in codes for code in ("E04", "E05", "E07"))
                ):
                    raise ReviewValidationError(
                        "视频前后不完整时必须选择 E04、E05 或 E07"
                    )
                if checks["replay"] == "Y" and "E06" not in codes:
                    raise ReviewValidationError("回放为 Y 时必须选择 E06")

            proposed = optional_float(manifest.get("auto_hit_time"))
            if checks["contains_contact"] != "Y" or conclusion == "D":
                contact_time = None
                effective_time = None
                contact_source = ""
            elif contact_time is not None:
                effective_time = contact_time
                contact_source = (
                    "human_correction"
                    if checks["original_time_correct"] == "N"
                    else "human_marked"
                )
            else:
                effective_time = proposed
                contact_source = "accepted_proposal" if proposed is not None else ""

            position = self._queue_positions[audit_id]
            legacy = self._legacy.get(audit_id, {})
            record: dict[str, Any] = {
                "review_schema_version": REVIEW_SCHEMA_VERSION,
                "manifest_schema_version": manifest["schema_version"],
                "audit_id": audit_id,
                "uid": manifest["uid"],
                "queue_position": position,
                "batch_number": ((position - 1) // 20) + 1,
                "batch_position": ((position - 1) % 20) + 1,
                "sample_id": manifest["sample_id"],
                "sample_relpath": manifest["sample_relpath"],
                "reviewer_id": reviewer_id,
                "conclusion": conclusion,
                "counts_toward_quota": conclusion in FORMAL_CONCLUSIONS,
                "contains_contact": checks["contains_contact"],
                "original_time_correct": checks["original_time_correct"],
                "event_start": optional_float(manifest.get("event_start")),
                "event_end": optional_float(manifest.get("event_end")),
                "proposed_contact_time": proposed,
                "correct_contact_time": contact_time,
                "effective_contact_time": effective_time,
                "contact_time_source": contact_source,
                "full_process": checks["full_process"],
                "replay": checks["replay"],
                "error_codes": ";".join(codes),
                "notes": notes,
                "legacy_review_status": legacy.get("review_status", ""),
                "legacy_reviewed_at_utc": legacy.get("reviewed_at_utc", ""),
                "reviewed_at_utc": utc_now(),
            }
            self._records[audit_id] = record
            self._write_atomic()
            return dict(record)

    def remove(self, audit_id: str) -> bool:
        with self._lock:
            if audit_id not in self._queue_positions:
                raise KeyError(audit_id)
            existed = self._records.pop(audit_id, None) is not None
            if existed:
                self._write_atomic()
            return existed

    def export_bytes(self, *, formal_only: bool) -> bytes:
        with self._lock:
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            for record in self.records():
                if formal_only and record["conclusion"] not in FORMAL_CONCLUSIONS:
                    continue
                writer.writerow(self._serializable_record(record))
            return ("\ufeff" + buffer.getvalue()).encode("utf-8")

    def legacy_export_bytes(self) -> bytes:
        if not self.legacy_path.is_file():
            return b""
        return self.legacy_path.read_bytes()

    def _load_new(self) -> None:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            audit_id = row.get("audit_id", "")
            if row.get("review_schema_version") != REVIEW_SCHEMA_VERSION:
                raise ReviewValidationError("新结果 CSV 使用了不支持的 schema")
            if audit_id not in self._queue_positions or audit_id not in self._manifest:
                raise ReviewValidationError(f"新结果不在当前队列中：{audit_id}")
            if audit_id in self._records:
                raise ReviewValidationError(f"新结果包含重复 ID：{audit_id}")
            if row.get("conclusion") not in CONCLUSIONS:
                raise ReviewValidationError(f"新结果结论无效：{audit_id}")
            record: dict[str, Any] = dict(row)
            for field in ("queue_position", "batch_number", "batch_position"):
                record[field] = int(row[field])
            for field in (
                "event_start",
                "event_end",
                "proposed_contact_time",
                "correct_contact_time",
                "effective_contact_time",
            ):
                record[field] = optional_float(row.get(field))
            record["counts_toward_quota"] = (
                str(row.get("counts_toward_quota", "")).strip().lower()
                in {"true", "1", "yes"}
            )
            self._records[audit_id] = record

    def _load_legacy(self) -> None:
        if not self.legacy_path.is_file():
            return
        with self.legacy_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            if row.get("review_schema_version") != LEGACY_REVIEW_SCHEMA_VERSION:
                raise ReviewValidationError("旧结果 CSV 使用了不支持的 schema")
            audit_id = row.get("audit_id", "")
            if audit_id not in self._queue_positions:
                continue
            if audit_id in self._legacy:
                raise ReviewValidationError(f"旧结果包含重复 ID：{audit_id}")
            if row.get("review_status") not in LEGACY_STATUSES:
                raise ReviewValidationError(f"旧结果状态无效：{audit_id}")
            record: dict[str, Any] = dict(row)
            for field in (
                "auto_hit_time",
                "hit_time_override",
                "effective_hit_time",
            ):
                record[field] = optional_float(row.get(field))
            self._legacy[audit_id] = record

    def _serializable_record(self, record: Mapping[str, Any]) -> dict[str, object]:
        result: dict[str, object] = {}
        float_fields = {
            "event_start",
            "event_end",
            "proposed_contact_time",
            "correct_contact_time",
            "effective_contact_time",
        }
        for field in RESULT_FIELDS:
            value = record.get(field, "")
            if field in float_fields:
                value = format_float(value)
            elif field == "counts_toward_quota":
                value = "true" if bool(value) else "false"
            result[field] = value
        return result

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
