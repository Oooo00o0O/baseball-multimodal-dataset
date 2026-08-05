"""Atomic flat-file stores for MLB candidate curation."""

from __future__ import annotations

import csv
import io
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from contracts import (
    ADMISSION_STATUSES,
    AUXILIARY_CLASSIFICATION_SOURCES,
    AUXILIARY_EVENT_TYPES,
    AUXILIARY_FIELDS,
    AUXILIARY_SCHEMA_VERSION,
    DERIVED_LABEL_BY_TRAJECTORY,
    EXCLUSION_REASONS,
    IDENTITY_VERSION,
    INVENTORY_FIELDS,
    INVENTORY_IMMUTABLE_FIELDS,
    INVENTORY_SCHEMA_VERSION,
    LOCATION_SOURCES,
    MEDIA_MATCH_CONFIDENCES,
    MEDIA_EXCLUSION_FIELDS,
    MEDIA_EXCLUSION_REASONS,
    MEDIA_EXCLUSION_SCHEMA_VERSION,
    MEDIA_STATUSES,
    MLB_LOCATIONS,
    OBSERVED_TRAJECTORIES,
    REVIEW_FIELDS,
    REVIEW_SCHEMA_VERSION,
    REVIEWED_LOCATIONS,
)


class StoreValidationError(ValueError):
    """Raised when a row cannot satisfy the curation contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: object) -> str:
    return str(value or "").strip()


def optional_float(value: object, label: str) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError) as error:
        raise StoreValidationError(f"{label}必须是数值") from error
    if not math.isfinite(result):
        raise StoreValidationError(f"{label}必须是有限数值")
    return result


def format_float(value: object) -> str:
    if value in {None, ""}:
        return ""
    number = float(value)
    return f"{number:.9f}".rstrip("0").rstrip(".")


def parse_bool(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    text = clean_text(value).lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", ""}:
        return False
    raise StoreValidationError(f"{label}必须是布尔值")


def format_bool(value: object) -> str:
    return "true" if bool(value) else "false"


def _reject_unknown_fields(
    row: Mapping[str, object],
    fields: Sequence[str],
    label: str,
) -> None:
    unknown = sorted(set(row) - set(fields))
    if unknown:
        raise StoreValidationError(f"{label}包含未知字段：{', '.join(unknown)}")


def _atomic_write_csv(
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


def _csv_bytes(
    fields: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _validate_header(
    actual: Sequence[str] | None,
    expected: Sequence[str],
    label: str,
) -> None:
    if list(actual or []) != list(expected):
        raise RuntimeError(f"{label} CSV 字段或顺序与当前 schema 不一致")


class CandidateInventoryStore:
    """One current machine-managed row per source play."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def get(self, source_play_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(source_play_id)
            return dict(record) if record else None

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._ordered_records()]

    def upsert(self, row: Mapping[str, object]) -> dict[str, Any]:
        return self.upsert_many([row])[0]

    def upsert_many(
        self,
        rows: Iterable[Mapping[str, object]],
    ) -> list[dict[str, Any]]:
        with self._lock:
            staged = dict(self._records)
            saved: list[dict[str, Any]] = []
            for row in rows:
                source_play_id = clean_text(row.get("source_play_id"))
                existing = staged.get(source_play_id)
                normalized = self._normalize(row, existing)
                staged[source_play_id] = normalized
                saved.append(dict(normalized))
            self._records = staged
            self._write()
            return saved

    def export_bytes(self) -> bytes:
        with self._lock:
            return _csv_bytes(
                INVENTORY_FIELDS,
                (self._serialized(row) for row in self._ordered_records()),
            )

    def _normalize(
        self,
        row: Mapping[str, object],
        existing: Mapping[str, object] | None,
    ) -> dict[str, Any]:
        _reject_unknown_fields(row, INVENTORY_FIELDS, "候选库存")
        result = {
            field: clean_text(existing.get(field)) if existing else ""
            for field in INVENTORY_FIELDS
        }
        for field, value in row.items():
            result[field] = clean_text(value)
        source_play_id = result["source_play_id"]
        if not source_play_id:
            raise StoreValidationError("source_play_id 不能为空")

        identity_method = result["identity_method"]
        if not identity_method:
            raise StoreValidationError("identity_method 不能为空")
        result["inventory_schema_version"] = INVENTORY_SCHEMA_VERSION
        result["identity_version"] = result["identity_version"] or IDENTITY_VERSION

        # MLB occasionally emits compound first-party values such as 78 or 89.
        # Preserve the raw value; only reviewed_location is constrained to the
        # human 1–9/unknown vocabulary.
        result["mlb_location_raw"] = result["mlb_location_raw"].lower()

        confidence = result["media_match_confidence"].lower()
        if confidence not in MEDIA_MATCH_CONFIDENCES:
            raise StoreValidationError("media_match_confidence 必须是 high/medium/low")
        result["media_match_confidence"] = confidence

        media_status = result["media_status"].lower() or "metadata_only"
        if media_status not in MEDIA_STATUSES:
            raise StoreValidationError("未知 media_status")
        result["media_status"] = media_status

        duration = optional_float(result["media_duration_sec"], "媒体时长")
        if duration is not None and duration <= 0:
            raise StoreValidationError("媒体时长必须大于 0")
        result["media_duration_sec"] = duration

        match_score = optional_float(result["media_match_score"], "媒体匹配分数")
        result["media_match_score"] = match_score

        previous_rank_present = True
        for rank in range(1, 4):
            time_field = f"auto_hit_time_{rank}"
            score_field = f"auto_hit_score_{rank}"
            hit_time = optional_float(result[time_field], f"自动候选点 {rank}")
            hit_score = optional_float(result[score_field], f"自动候选分数 {rank}")
            if hit_time is not None:
                if hit_time < 0:
                    raise StoreValidationError("自动候选点不能小于 0")
                if duration is not None and hit_time > duration:
                    raise StoreValidationError("自动候选点不能超过媒体时长")
                if not previous_rank_present:
                    raise StoreValidationError("自动候选点排名必须连续")
            if hit_score is not None and hit_time is None:
                raise StoreValidationError("自动候选分数必须对应一个候选点")
            previous_rank_present = hit_time is not None
            result[time_field] = hit_time
            result[score_field] = hit_score

        now = utc_now()
        result["discovered_at_utc"] = (
            clean_text(existing.get("discovered_at_utc"))
            if existing
            else result["discovered_at_utc"] or now
        )
        result["updated_at_utc"] = now

        if existing:
            for field in INVENTORY_IMMUTABLE_FIELDS:
                old = clean_text(existing.get(field))
                new = clean_text(result.get(field))
                if old and new and old != new:
                    raise StoreValidationError(
                        f"候选库存不可覆盖已记录的原始字段：{field}"
                    )
                if old and not new:
                    result[field] = existing[field]
        return result

    def _load(self) -> None:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            _validate_header(reader.fieldnames, INVENTORY_FIELDS, "候选库存")
            rows = list(reader)
        for row in rows:
            if row.get("inventory_schema_version") != INVENTORY_SCHEMA_VERSION:
                raise RuntimeError("候选库存使用了不支持的 schema")
            source_play_id = clean_text(row.get("source_play_id"))
            if not source_play_id:
                raise RuntimeError("候选库存包含空 source_play_id")
            if source_play_id in self._records:
                raise RuntimeError(f"候选库存包含重复 ID：{source_play_id}")
            normalized = self._normalize_loaded(row)
            self._records[source_play_id] = normalized

    def _normalize_loaded(self, row: Mapping[str, object]) -> dict[str, Any]:
        result: dict[str, Any] = dict(row)
        result["media_duration_sec"] = optional_float(
            row.get("media_duration_sec"), "媒体时长"
        )
        result["media_match_score"] = optional_float(
            row.get("media_match_score"), "媒体匹配分数"
        )
        for rank in range(1, 4):
            result[f"auto_hit_time_{rank}"] = optional_float(
                row.get(f"auto_hit_time_{rank}"), f"自动候选点 {rank}"
            )
            result[f"auto_hit_score_{rank}"] = optional_float(
                row.get(f"auto_hit_score_{rank}"), f"自动候选分数 {rank}"
            )
        return result

    def _ordered_records(self) -> list[dict[str, Any]]:
        return sorted(
            self._records.values(),
            key=lambda row: (
                clean_text(row.get("game_date")),
                clean_text(row.get("source_play_id")),
            ),
        )

    def _serialized(self, row: Mapping[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        float_fields = {
            "media_match_score",
            "media_duration_sec",
            "auto_hit_time_1",
            "auto_hit_score_1",
            "auto_hit_time_2",
            "auto_hit_score_2",
            "auto_hit_time_3",
            "auto_hit_score_3",
        }
        for field in INVENTORY_FIELDS:
            value = row.get(field, "")
            result[field] = format_float(value) if field in float_fields else value
        return result

    def _write(self) -> None:
        _atomic_write_csv(
            self.path,
            INVENTORY_FIELDS,
            (self._serialized(row) for row in self._ordered_records()),
        )


class PrefilteredAuxiliaryStore:
    """Metadata-only registry kept outside the Ground/Fly inventory."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, str]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def get(self, source_play_id: str) -> dict[str, str] | None:
        with self._lock:
            record = self._records.get(source_play_id)
            return dict(record) if record else None

    def all(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(row) for row in self._ordered_records()]

    def upsert(self, row: Mapping[str, object]) -> dict[str, str]:
        with self._lock:
            normalized = self._normalize(row)
            source_play_id = normalized["source_play_id"]
            existing = self._records.get(source_play_id)
            if existing:
                normalized["recorded_at_utc"] = existing["recorded_at_utc"]
            self._records[source_play_id] = normalized
            self._write()
            return dict(normalized)

    def export_bytes(self) -> bytes:
        with self._lock:
            return _csv_bytes(AUXILIARY_FIELDS, self._ordered_records())

    def _normalize(self, row: Mapping[str, object]) -> dict[str, str]:
        _reject_unknown_fields(row, AUXILIARY_FIELDS, "下载前分流记录")
        result = {field: clean_text(row.get(field)) for field in AUXILIARY_FIELDS}
        if not result["source_play_id"]:
            raise StoreValidationError("下载前分流记录必须有 source_play_id")
        event_type = result["auxiliary_event_type"].lower()
        if event_type not in AUXILIARY_EVENT_TYPES:
            raise StoreValidationError("未知 auxiliary_event_type")
        result["auxiliary_event_type"] = event_type
        source = result["classification_source"].lower()
        if source not in AUXILIARY_CLASSIFICATION_SOURCES:
            raise StoreValidationError(
                "classification_source 只能是 MLB 结构化字段或正式 play description"
            )
        result["classification_source"] = source
        if not result["classification_evidence"]:
            raise StoreValidationError("下载前分流必须保存明确证据")
        if not result["prefilter_version"]:
            raise StoreValidationError("下载前分流必须保存 prefilter_version")
        result["auxiliary_schema_version"] = AUXILIARY_SCHEMA_VERSION
        result["recorded_at_utc"] = result["recorded_at_utc"] or utc_now()
        return result

    def _load(self) -> None:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            _validate_header(reader.fieldnames, AUXILIARY_FIELDS, "下载前分流")
            rows = list(reader)
        for row in rows:
            if row.get("auxiliary_schema_version") != AUXILIARY_SCHEMA_VERSION:
                raise RuntimeError("下载前分流 CSV 使用了不支持的 schema")
            normalized = self._normalize(row)
            source_play_id = normalized["source_play_id"]
            if source_play_id in self._records:
                raise RuntimeError(f"下载前分流 CSV 包含重复 ID：{source_play_id}")
            self._records[source_play_id] = normalized

    def _ordered_records(self) -> list[dict[str, str]]:
        return sorted(
            self._records.values(),
            key=lambda row: (
                row.get("game_date", ""),
                row.get("source_play_id", ""),
            ),
        )

    def _write(self) -> None:
        _atomic_write_csv(self.path, AUXILIARY_FIELDS, self._ordered_records())


class PrefilteredMediaExclusionStore:
    """Rejected source-media matches kept outside the candidate inventory."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], dict[str, str]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    @staticmethod
    def _key(row: Mapping[str, object]) -> tuple[str, str]:
        return (
            clean_text(row.get("source_play_id")),
            clean_text(row.get("source_video_id")),
        )

    def all(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(row) for row in self._ordered_records()]

    def get(
        self,
        source_play_id: str,
        source_video_id: str,
    ) -> dict[str, str] | None:
        with self._lock:
            record = self._records.get(
                (clean_text(source_play_id), clean_text(source_video_id))
            )
            return dict(record) if record else None

    def upsert(self, row: Mapping[str, object]) -> dict[str, str]:
        with self._lock:
            normalized = self._normalize(row)
            key = self._key(normalized)
            existing = self._records.get(key)
            if existing:
                normalized["recorded_at_utc"] = existing["recorded_at_utc"]
            self._records[key] = normalized
            self._write()
            return dict(normalized)

    def export_bytes(self) -> bytes:
        with self._lock:
            return _csv_bytes(MEDIA_EXCLUSION_FIELDS, self._ordered_records())

    def _normalize(self, row: Mapping[str, object]) -> dict[str, str]:
        _reject_unknown_fields(row, MEDIA_EXCLUSION_FIELDS, "媒体预排除记录")
        result = {
            field: clean_text(row.get(field)) for field in MEDIA_EXCLUSION_FIELDS
        }
        if not result["source_play_id"] or not result["source_video_id"]:
            raise StoreValidationError(
                "媒体预排除记录必须有 source_play_id 和 source_video_id"
            )
        reason = result["exclusion_reason"].lower()
        if reason not in MEDIA_EXCLUSION_REASONS:
            raise StoreValidationError("未知媒体预排除原因")
        if not result["matched_pattern"]:
            raise StoreValidationError("媒体预排除必须保存命中的标题规则")
        if not result["matcher_version"]:
            raise StoreValidationError("媒体预排除必须保存 matcher_version")
        duration = optional_float(result["media_duration_sec"], "媒体时长")
        if duration is not None and duration <= 0:
            raise StoreValidationError("媒体时长必须大于 0")
        result["media_duration_sec"] = format_float(duration)
        result["exclusion_reason"] = reason
        result["media_exclusion_schema_version"] = MEDIA_EXCLUSION_SCHEMA_VERSION
        result["recorded_at_utc"] = result["recorded_at_utc"] or utc_now()
        return result

    def _load(self) -> None:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            _validate_header(
                reader.fieldnames,
                MEDIA_EXCLUSION_FIELDS,
                "媒体预排除",
            )
            rows = list(reader)
        for row in rows:
            if (
                row.get("media_exclusion_schema_version")
                != MEDIA_EXCLUSION_SCHEMA_VERSION
            ):
                raise RuntimeError("媒体预排除 CSV 使用了不支持的 schema")
            normalized = self._normalize(row)
            key = self._key(normalized)
            if key in self._records:
                raise RuntimeError("媒体预排除 CSV 包含重复 play/video 组合")
            self._records[key] = normalized

    def _ordered_records(self) -> list[dict[str, str]]:
        return sorted(
            self._records.values(),
            key=lambda row: (
                row.get("game_date", ""),
                row.get("source_play_id", ""),
                row.get("source_video_id", ""),
            ),
        )

    def _write(self) -> None:
        _atomic_write_csv(
            self.path,
            MEDIA_EXCLUSION_FIELDS,
            self._ordered_records(),
        )


class BatchReviewStore:
    """One current submitted human result per source play within a batch."""

    def __init__(
        self,
        path: Path,
        batch_id: str,
        inventory_rows: Iterable[Mapping[str, object]],
    ) -> None:
        self.path = path.resolve()
        self.batch_id = clean_text(batch_id)
        if not self.batch_id:
            raise StoreValidationError("batch_id 不能为空")
        self._lock = threading.RLock()
        self._inventory = {
            clean_text(row.get("source_play_id")): dict(row)
            for row in inventory_rows
            if clean_text(row.get("source_play_id"))
        }
        self._records: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def get(self, source_play_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(source_play_id)
            return dict(record) if record else None

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._ordered_records()]

    def summary(self) -> dict[str, int]:
        with self._lock:
            admitted = sum(
                row["admission_status"] == "admitted"
                for row in self._records.values()
            )
            excluded = len(self._records) - admitted
            return {
                "assigned": len(self._inventory),
                "reviewed": len(self._records),
                "admitted": admitted,
                "excluded": excluded,
                "remaining": len(self._inventory) - len(self._records),
            }

    def upsert(
        self,
        source_play_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, Any]:
        with self._lock:
            source_play_id = clean_text(source_play_id)
            if source_play_id not in self._inventory:
                raise KeyError(source_play_id)
            record = self._normalize(
                source_play_id,
                payload,
                reviewed_at=utc_now(),
            )
            self._records[source_play_id] = record
            self._write()
            return dict(record)

    def remove(self, source_play_id: str) -> bool:
        with self._lock:
            if source_play_id not in self._inventory:
                raise KeyError(source_play_id)
            removed = self._records.pop(source_play_id, None) is not None
            if removed:
                self._write()
            return removed

    def export_bytes(self) -> bytes:
        with self._lock:
            return _csv_bytes(
                REVIEW_FIELDS,
                (self._serialized(row) for row in self._ordered_records()),
            )

    def _normalize(
        self,
        source_play_id: str,
        payload: Mapping[str, object],
        reviewed_at: str,
    ) -> dict[str, Any]:
        _reject_unknown_fields(payload, REVIEW_FIELDS, "人工审核")
        inventory = self._inventory[source_play_id]
        admission_status = clean_text(payload.get("admission_status")).lower()
        if admission_status not in ADMISSION_STATUSES:
            raise StoreValidationError("admission_status 必须是 admitted 或 excluded")

        reviewer_id = clean_text(payload.get("reviewer_id"))
        notes = clean_text(payload.get("notes"))
        if len(reviewer_id) > 100:
            raise StoreValidationError("审核人 ID 不能超过 100 字")
        if len(notes) > 2000:
            raise StoreValidationError("备注不能超过 2000 字")

        mlb_location_raw = clean_text(inventory.get("mlb_location_raw")).lower()
        proposed_hit_time = optional_float(
            inventory.get("auto_hit_time_1"), "自动建议击球点"
        )
        duration = optional_float(inventory.get("media_duration_sec"), "媒体时长")

        result: dict[str, Any] = {
            "review_schema_version": REVIEW_SCHEMA_VERSION,
            "inventory_schema_version": INVENTORY_SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "source_play_id": source_play_id,
            "admission_status": admission_status,
            "exclusion_reason": "",
            "observed_trajectory": "",
            "derived_ground_fly_label": "",
            "mlb_location_raw": mlb_location_raw,
            "reviewed_location": "",
            "location_source": "",
            "proposed_hit_time": proposed_hit_time,
            "reviewed_hit_time": None,
            "hit_time_source": "",
            "contact_eligible": False,
            "ground_fly_eligible": False,
            "location_eligible": False,
            "broken_bat": parse_bool(payload.get("broken_bat"), "断棒标记"),
            "reviewer_id": reviewer_id,
            "notes": notes,
            "reviewed_at_utc": reviewed_at,
        }

        if admission_status == "excluded":
            reason = clean_text(payload.get("exclusion_reason")).lower()
            if reason not in EXCLUSION_REASONS:
                raise StoreValidationError("排除样本必须选择明确的 exclusion_reason")
            result["exclusion_reason"] = reason
            return result

        if clean_text(payload.get("exclusion_reason")):
            raise StoreValidationError("通过样本不能包含 exclusion_reason")

        trajectory = clean_text(payload.get("observed_trajectory")).lower()
        if trajectory not in OBSERVED_TRAJECTORIES:
            raise StoreValidationError("通过样本必须填写有效 observed_trajectory")
        result["observed_trajectory"] = trajectory
        result["derived_ground_fly_label"] = DERIVED_LABEL_BY_TRAJECTORY[trajectory]

        reviewed_hit_time = optional_float(
            payload.get("reviewed_hit_time"), "人工确认击球点"
        )
        if reviewed_hit_time is None:
            raise StoreValidationError("通过样本必须保存一个人工确认击球点")
        if reviewed_hit_time < 0:
            raise StoreValidationError("人工确认击球点不能小于 0")
        if duration is not None and reviewed_hit_time > duration:
            raise StoreValidationError("人工确认击球点不能超过媒体时长")
        result["reviewed_hit_time"] = reviewed_hit_time
        result["hit_time_source"] = (
            "accepted_proposal"
            if proposed_hit_time is not None
            and abs(reviewed_hit_time - proposed_hit_time) <= 0.001
            else "human_override"
        )

        reviewed_location = clean_text(payload.get("reviewed_location")).lower()
        if not reviewed_location:
            reviewed_location = (
                mlb_location_raw if mlb_location_raw in MLB_LOCATIONS else ""
            )
        if reviewed_location not in REVIEWED_LOCATIONS:
            raise StoreValidationError("reviewed_location 必须是 1–9 或 unknown")

        expected_location_source: str
        if reviewed_location == "unknown":
            expected_location_source = "unknown"
        elif mlb_location_raw in MLB_LOCATIONS:
            expected_location_source = (
                "accepted_official"
                if reviewed_location == mlb_location_raw
                else "human_corrected"
            )
        else:
            expected_location_source = "human_filled"

        supplied_location_source = clean_text(payload.get("location_source")).lower()
        if (
            supplied_location_source
            and supplied_location_source not in LOCATION_SOURCES
        ):
            raise StoreValidationError("未知 location_source")
        if (
            supplied_location_source
            and supplied_location_source != expected_location_source
        ):
            raise StoreValidationError(
                f"location_source 应为 {expected_location_source}"
            )
        result["reviewed_location"] = reviewed_location
        result["location_source"] = expected_location_source

        result["contact_eligible"] = True
        result["ground_fly_eligible"] = bool(
            result["derived_ground_fly_label"]
        )
        result["location_eligible"] = reviewed_location in MLB_LOCATIONS
        return result

    def _load(self) -> None:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            _validate_header(reader.fieldnames, REVIEW_FIELDS, "人工审核")
            rows = list(reader)
        for row in rows:
            source_play_id = clean_text(row.get("source_play_id"))
            if source_play_id not in self._inventory:
                raise RuntimeError(f"审核结果包含未分配 ID：{source_play_id}")
            if source_play_id in self._records:
                raise RuntimeError(f"审核结果包含重复 ID：{source_play_id}")
            if row.get("review_schema_version") != REVIEW_SCHEMA_VERSION:
                raise RuntimeError("审核结果使用了不支持的 schema")
            if row.get("batch_id") != self.batch_id:
                raise RuntimeError("审核结果 batch_id 与当前批次不一致")
            payload = dict(row)
            payload.pop("review_schema_version", None)
            payload.pop("inventory_schema_version", None)
            payload.pop("batch_id", None)
            payload.pop("source_play_id", None)
            payload.pop("derived_ground_fly_label", None)
            payload.pop("mlb_location_raw", None)
            payload.pop("proposed_hit_time", None)
            payload.pop("hit_time_source", None)
            payload.pop("contact_eligible", None)
            payload.pop("ground_fly_eligible", None)
            payload.pop("location_eligible", None)
            reviewed_at = clean_text(payload.pop("reviewed_at_utc", None))
            record = self._normalize(
                source_play_id,
                payload,
                reviewed_at=reviewed_at,
            )
            self._records[source_play_id] = record

    def _ordered_records(self) -> list[dict[str, Any]]:
        return sorted(
            self._records.values(),
            key=lambda row: row["source_play_id"],
        )

    def _serialized(self, row: Mapping[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        float_fields = {"proposed_hit_time", "reviewed_hit_time"}
        bool_fields = {
            "contact_eligible",
            "ground_fly_eligible",
            "location_eligible",
            "broken_bat",
        }
        for field in REVIEW_FIELDS:
            value = row.get(field, "")
            if field in float_fields:
                result[field] = format_float(value)
            elif field in bool_fields:
                result[field] = format_bool(value)
            else:
                result[field] = value
        return result

    def _write(self) -> None:
        _atomic_write_csv(
            self.path,
            REVIEW_FIELDS,
            (self._serialized(row) for row in self._ordered_records()),
        )
