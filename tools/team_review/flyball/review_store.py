"""Atomic single-reviewer CSV store for Flyball manual calibration."""

from __future__ import annotations

import csv
import io
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from contracts import (
    CONCLUSIONS,
    ERROR_CODES,
    MANIFEST_SCHEMA_VERSION,
    REVIEW_SCHEMA_VERSION,
    TRAJECTORIES,
    TRI_STATE_VALUES,
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
    "original_time_correct",
    "event_start",
    "event_end",
    "proposed_contact_time",
    "contact_time",
    "contact_time_source",
    "sound",
    "picture",
    "full_process",
    "replay",
    "recorded_trajectory",
    "trajectory",
    "error_codes",
    "notes",
    "reviewed_at_utc",
]


class ReviewValidationError(ValueError):
    pass


def optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        result = float(str(value))
    except (TypeError, ValueError) as error:
        raise ReviewValidationError("正确击球秒必须是数值") from error
    if not math.isfinite(result):
        raise ReviewValidationError("正确击球秒必须是有限数值")
    return result


def format_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


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


class ReviewStore:
    def __init__(
        self,
        path: Path,
        admin_rows: list[dict[str, str]],
        queue_rows: list[dict[str, str]],
    ) -> None:
        self.path = path.resolve()
        self._lock = threading.RLock()
        self._admin = {row["audit_id"]: row for row in admin_rows}
        self._queue = {row["audit_id"]: row for row in queue_rows}
        self._records: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def get(self, audit_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(audit_id)
            return dict(record) if record else None

    def summary(self) -> dict[str, object]:
        with self._lock:
            counts = {conclusion: 0 for conclusion in CONCLUSIONS}
            for record in self._records.values():
                counts[record["conclusion"]] += 1
            total = len(self._queue)
            return {
                "total": total,
                "reviewed": len(self._records),
                "remaining": total - len(self._records),
                "conclusion_counts": counts,
            }

    def upsert(
        self,
        audit_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, Any]:
        with self._lock:
            if audit_id not in self._queue or audit_id not in self._admin:
                raise KeyError(audit_id)
            admin = self._admin[audit_id]
            queue = self._queue[audit_id]

            reviewer_id = str(payload.get("reviewer_id", "") or "").strip()
            if not reviewer_id:
                raise ReviewValidationError("请填写标注者姓名或 ID")
            if len(reviewer_id) > 100:
                raise ReviewValidationError("标注者 ID 不能超过 100 字")

            conclusion = str(payload.get("conclusion", "")).strip().upper()
            if conclusion not in CONCLUSIONS:
                raise ReviewValidationError("结论必须是 V、I 或 U")

            checks: dict[str, str] = {}
            for field, label in {
                "original_time_correct": "原时间正确",
                "sound": "声音",
                "picture": "画面",
                "full_process": "全过程",
                "replay": "回放",
            }.items():
                value = str(payload.get(field, "")).strip().upper()
                if value not in TRI_STATE_VALUES:
                    raise ReviewValidationError(f"{label}必须填写 Y、N 或 U")
                checks[field] = value

            trajectory = str(payload.get("trajectory", "")).strip().lower()
            if trajectory not in TRAJECTORIES:
                raise ReviewValidationError(
                    "轨迹必须是 fly、line_drive、pop_fly 或 unknown"
                )
            codes = normalize_codes(payload.get("error_codes"))
            notes = str(payload.get("notes", "") or "").strip()
            if len(notes) > 2000:
                raise ReviewValidationError("备注不能超过 2000 字")
            contact_time = optional_float(payload.get("contact_time"))
            duration = optional_float(admin.get("audio_duration_sec"))
            if contact_time is not None:
                if contact_time < 0:
                    raise ReviewValidationError("正确击球秒不能小于 0")
                if duration is not None and contact_time > duration:
                    raise ReviewValidationError("正确击球秒不能超过样本时长")

            if conclusion == "V":
                expected = {
                    "original_time_correct": "Y",
                    "sound": "Y",
                    "picture": "Y",
                    "full_process": "Y",
                    "replay": "N",
                }
                wrong = [
                    field
                    for field, expected_value in expected.items()
                    if checks[field] != expected_value
                ]
                if wrong:
                    raise ReviewValidationError(
                        "V 有效要求原时间/声音/画面/全过程为 Y，回放为 N"
                    )
                if trajectory == "unknown":
                    raise ReviewValidationError("V 有效不能把轨迹填为 unknown")
                if contact_time is None:
                    raise ReviewValidationError("V 有效必须填写正确击球秒")
                if codes:
                    raise ReviewValidationError("V 有效不能包含错误代码")

            if conclusion == "I" and not codes:
                raise ReviewValidationError("I 无效必须选择至少一个错误代码")
            if conclusion == "U" and not notes:
                raise ReviewValidationError("U 不确定必须在备注中写明疑点")
            if "E11" in codes and not notes:
                raise ReviewValidationError("E11 其他问题必须在备注中写清楚")

            required_code_checks = [
                (checks["sound"] == "N", "E01", "声音为 N 时必须选择 E01"),
                (
                    checks["original_time_correct"] == "N",
                    "E02",
                    "原时间为 N 时必须选择 E02",
                ),
                (checks["picture"] == "N", "E03", "画面为 N 时必须选择 E03"),
                (
                    checks["full_process"] == "N",
                    ("E04", "E05"),
                    "全过程为 N 时必须选择 E04 或 E05",
                ),
                (checks["replay"] == "Y", "E06", "回放为 Y 时必须选择 E06"),
            ]
            for condition, expected_code, message in required_code_checks:
                if not condition:
                    continue
                if isinstance(expected_code, tuple):
                    if not any(code in codes for code in expected_code):
                        raise ReviewValidationError(message)
                elif expected_code not in codes:
                    raise ReviewValidationError(message)

            if (
                checks["sound"] == "Y"
                and checks["picture"] == "Y"
                and conclusion != "U"
                and contact_time is None
            ):
                raise ReviewValidationError(
                    "声音和画面都确认有击球时必须填写正确击球秒"
                )

            proposed = optional_float(admin.get("proposed_contact_time"))
            if contact_time is None:
                contact_source = ""
            elif proposed is not None and abs(contact_time - proposed) <= 0.001:
                contact_source = "accepted_proposal"
            else:
                contact_source = "human_override"

            record: dict[str, Any] = {
                "review_schema_version": REVIEW_SCHEMA_VERSION,
                "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
                "audit_id": audit_id,
                "uid": admin["uid"],
                "queue_position": int(queue["queue_position"]),
                "batch_number": int(queue["batch_number"]),
                "batch_position": int(queue["batch_position"]),
                "sample_id": admin["sample_id"],
                "sample_relpath": admin["sample_relpath"],
                "reviewer_id": reviewer_id,
                "conclusion": conclusion,
                "original_time_correct": checks["original_time_correct"],
                "event_start": optional_float(admin.get("event_start")),
                "event_end": optional_float(admin.get("event_end")),
                "proposed_contact_time": proposed,
                "contact_time": contact_time,
                "contact_time_source": contact_source,
                "sound": checks["sound"],
                "picture": checks["picture"],
                "full_process": checks["full_process"],
                "replay": checks["replay"],
                "recorded_trajectory": admin["recorded_trajectory"],
                "trajectory": trajectory,
                "error_codes": ";".join(codes),
                "notes": notes,
                "reviewed_at_utc": utc_now(),
            }
            self._records[audit_id] = record
            self._write()
            return dict(record)

    def remove(self, audit_id: str) -> bool:
        with self._lock:
            if audit_id not in self._queue:
                raise KeyError(audit_id)
            removed = self._records.pop(audit_id, None) is not None
            if removed:
                self._write()
            return removed

    def export_bytes(self) -> bytes:
        with self._lock:
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            for record in self._ordered_records():
                writer.writerow(self._serialized(record))
            return ("\ufeff" + buffer.getvalue()).encode("utf-8")

    def _load(self) -> None:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            audit_id = row.get("audit_id", "")
            if audit_id not in self._queue:
                raise RuntimeError(f"result contains unknown audit ID: {audit_id}")
            if row.get("review_schema_version") != REVIEW_SCHEMA_VERSION:
                raise RuntimeError("result CSV uses an unsupported schema")
            if row.get("conclusion") not in CONCLUSIONS:
                raise RuntimeError(f"invalid stored conclusion for {audit_id}")
            if audit_id in self._records:
                raise RuntimeError(f"result CSV contains duplicate ID: {audit_id}")
            record: dict[str, Any] = dict(row)
            for field in {"queue_position", "batch_number", "batch_position"}:
                record[field] = int(row[field])
            for field in {
                "event_start",
                "event_end",
                "proposed_contact_time",
                "contact_time",
            }:
                record[field] = optional_float(row.get(field))
            self._records[audit_id] = record

    def _ordered_records(self) -> list[dict[str, Any]]:
        return sorted(
            self._records.values(),
            key=lambda record: int(record["queue_position"]),
        )

    def _serialized(self, record: Mapping[str, Any]) -> dict[str, object]:
        result: dict[str, object] = {}
        for field in RESULT_FIELDS:
            value = record.get(field, "")
            result[field] = (
                format_float(value)
                if field
                in {
                    "event_start",
                    "event_end",
                    "proposed_contact_time",
                    "contact_time",
                }
                else value
            )
        return result

    def _write(self) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            for record in self._ordered_records():
                writer.writerow(self._serialized(record))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
