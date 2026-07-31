"""Deterministic legacy-to-owner-form mapping and combined CSV export."""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Mapping

from contracts import REVIEW_SCHEMA_VERSION
from validation_store import RESULT_FIELDS, format_float, optional_float


LEGACY_REVIEWER_ID = "legacy_mapped"


def map_legacy_review(
    manifest: Mapping[str, str],
    queue_position: int,
    legacy: Mapping[str, Any],
) -> dict[str, Any]:
    """Map fields that are knowable from the earlier three-status workflow."""

    status = str(legacy.get("review_status", "") or "")
    proposed = optional_float(manifest.get("auto_hit_time"))
    legacy_effective = optional_float(legacy.get("effective_hit_time"))
    override = optional_float(legacy.get("hit_time_override"))

    conclusion = "D"
    counts_toward_quota = False
    contains_contact = ""
    original_time_correct = ""
    full_process = ""
    replay = ""
    correct_contact_time = None
    effective_contact_time = None
    contact_time_source = ""
    error_codes = ""
    if status == "pass":
        conclusion = "V"
        counts_toward_quota = True
        contains_contact = "Y"
        original_time_correct = "Y"
        full_process = "Y"
        replay = "N"
        effective_contact_time = (
            legacy_effective if legacy_effective is not None else proposed
        )
        contact_time_source = "legacy_accepted_proposal"
    elif status == "corrected_pass":
        corrected = override if override is not None else legacy_effective
        if corrected is not None:
            conclusion = "I"
            counts_toward_quota = True
            contains_contact = "Y"
            original_time_correct = "N"
            full_process = "Y"
            replay = "N"
            correct_contact_time = corrected
            effective_contact_time = corrected
            contact_time_source = "legacy_human_correction"
            error_codes = "E02"
    elif status == "no_contact":
        conclusion = "I"
        counts_toward_quota = True
        contains_contact = "N"
        original_time_correct = "N"
        full_process = "N"
        replay = "N"
        error_codes = "E01"

    position = int(queue_position)
    return {
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "manifest_schema_version": manifest["schema_version"],
        "audit_id": manifest["audit_id"],
        "uid": manifest["uid"],
        "queue_position": position,
        "batch_number": ((position - 1) // 20) + 1,
        "batch_position": ((position - 1) % 20) + 1,
        "sample_id": manifest["sample_id"],
        "sample_relpath": manifest["sample_relpath"],
        "reviewer_id": LEGACY_REVIEWER_ID,
        "conclusion": conclusion,
        "counts_toward_quota": counts_toward_quota,
        "contains_contact": contains_contact,
        "original_time_correct": original_time_correct,
        "event_start": optional_float(manifest.get("event_start")),
        "event_end": optional_float(manifest.get("event_end")),
        "proposed_contact_time": proposed,
        "correct_contact_time": correct_contact_time,
        "effective_contact_time": effective_contact_time,
        "contact_time_source": contact_time_source,
        "full_process": full_process,
        "replay": replay,
        "error_codes": error_codes,
        "notes": str(legacy.get("notes", "") or "").strip(),
        "legacy_review_status": status,
        "legacy_reviewed_at_utc": str(
            legacy.get("reviewed_at_utc", "") or ""
        ),
        "reviewed_at_utc": str(legacy.get("reviewed_at_utc", "") or ""),
    }


def combined_records(
    *,
    store: Any,
    manifest_by_id: Mapping[str, Mapping[str, str]],
    queue_rows: Iterable[Mapping[str, str]],
) -> list[dict[str, Any]]:
    """Return one effective row per reviewed sample; a new row overrides legacy."""

    records: list[dict[str, Any]] = []
    for queue_row in sorted(
        queue_rows,
        key=lambda row: int(row["queue_position"]),
    ):
        audit_id = queue_row["audit_id"]
        current = store.get(audit_id)
        if current is not None:
            records.append(current)
            continue
        legacy = store.get_legacy(audit_id)
        if legacy is None:
            continue
        records.append(
            map_legacy_review(
                manifest_by_id[audit_id],
                int(queue_row["queue_position"]),
                legacy,
            )
        )
    return records


def combined_summary(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {"V": 0, "I": 0, "D": 0}
    total = 0
    legacy_mapped = 0
    for record in records:
        conclusion = str(record.get("conclusion", "") or "")
        if conclusion in counts:
            counts[conclusion] += 1
        total += 1
        if record.get("reviewer_id") == LEGACY_REVIEWER_ID:
            legacy_mapped += 1
    return {
        "export_record_count": total,
        "export_formal_reviewed": counts["V"] + counts["I"],
        "export_discarded": counts["D"],
        "export_conclusion_counts": counts,
        "legacy_mapped_total": legacy_mapped,
    }


def export_bytes(
    records: Iterable[Mapping[str, Any]],
    *,
    formal_only: bool,
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=RESULT_FIELDS)
    writer.writeheader()
    float_fields = {
        "event_start",
        "event_end",
        "proposed_contact_time",
        "correct_contact_time",
        "effective_contact_time",
    }
    for record in records:
        if formal_only and record.get("conclusion") not in {"V", "I"}:
            continue
        row: dict[str, object] = {}
        for field in RESULT_FIELDS:
            value = record.get(field, "")
            if field in float_fields:
                value = format_float(value)
            elif field == "counts_toward_quota":
                value = "true" if bool(value) else "false"
            row[field] = value
        writer.writerow(row)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
