"""Portable review bundles and deterministic cross-member consolidation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from contracts import REVIEW_FIELDS


BUNDLE_SCHEMA_VERSION = "mlb-curation-team-bundle-v1"
TEAM_INVENTORY_FIELDS = [
    "source_play_id",
    "game_pk",
    "play_id",
    "game_date",
    "batter",
    "pitcher",
    "play_description",
    "source_video_id",
    "source_title",
    "source_page_url",
    "source_mp4_url",
    "media_duration_sec",
    "media_sha256",
    "batch_ids",
]
CONFLICT_FIELDS = [
    "source_play_id",
    "batch_ids",
    "conflict_fields",
    "reason_zh",
    "review_rows_json",
]
MEDIA_WARNING_FIELDS = [
    "media_identity_type",
    "media_identity",
    "source_play_ids",
    "batch_ids",
    "reason_zh",
]
VOLATILE_REVIEW_FIELDS = {"reviewed_at_utc", "reviewer_id", "batch_id"}
BOOLEAN_REVIEW_FIELDS = {
    "contact_eligible",
    "ground_fly_eligible",
    "location_eligible",
    "broken_bat",
}
FLOAT_REVIEW_FIELDS = {"proposed_hit_time", "reviewed_hit_time"}


def _text(row: Mapping[str, object], field: str) -> str:
    return str(row.get(field) or "").strip()


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


def _serialized_review(row: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in REVIEW_FIELDS:
        value = row.get(field, "")
        if field in BOOLEAN_REVIEW_FIELDS and isinstance(value, bool):
            result[field] = "true" if value else "false"
        elif field in FLOAT_REVIEW_FIELDS and value not in {None, ""}:
            number = float(value)
            result[field] = f"{number:.9f}".rstrip("0").rstrip(".")
        else:
            result[field] = value
    return result


def _read_csv_bytes(payload: bytes) -> list[dict[str, str]]:
    text = payload.decode("utf-8-sig")
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_project_file(project_root: Path, relative_path: str) -> Path | None:
    if not relative_path.strip():
        return None
    root = project_root.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("media path escapes project root")
    return candidate if candidate.is_file() else None


def _validate_optional_date(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must use YYYY-MM-DD") from error
    return value


def build_team_bundle_bytes(
    inventory_rows: Iterable[Mapping[str, object]],
    review_rows: Iterable[Mapping[str, object]],
    project_root: Path,
    *,
    batch_id: str,
    assigned_start_date: str = "",
    assigned_end_date: str = "",
) -> bytes:
    batch_id = batch_id.strip()
    if not batch_id:
        raise ValueError("batch_id cannot be blank")
    start = _validate_optional_date(assigned_start_date, "assigned_start_date")
    end = _validate_optional_date(assigned_end_date, "assigned_end_date")
    if start and end and end < start:
        raise ValueError("assigned_end_date must be on or after assigned_start_date")

    inventory = {
        _text(row, "source_play_id"): dict(row)
        for row in inventory_rows
        if _text(row, "source_play_id")
    }
    reviews = [dict(row) for row in review_rows]
    reviewed_inventory: list[dict[str, object]] = []
    for review in reviews:
        source_play_id = _text(review, "source_play_id")
        if source_play_id not in inventory:
            raise ValueError(f"review references missing inventory: {source_play_id}")
        source = inventory[source_play_id]
        video_path = _safe_project_file(
            project_root,
            _text(source, "video_relpath"),
        )
        reviewed_inventory.append(
            {
                field: source.get(field, "")
                for field in TEAM_INVENTORY_FIELDS
            }
        )
        reviewed_inventory[-1]["media_sha256"] = (
            file_sha256(video_path) if video_path else ""
        )
        reviewed_inventory[-1]["batch_ids"] = batch_id

    manifest = {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "batch_id": batch_id,
        "assigned_start_date": start,
        "assigned_end_date": end,
        "review_count": len(reviews),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "contains_media": False,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        archive.writestr(
            "reviews.csv",
            _csv_bytes(REVIEW_FIELDS, (_serialized_review(row) for row in reviews)),
        )
        archive.writestr(
            "reviewed_inventory.csv",
            _csv_bytes(TEAM_INVENTORY_FIELDS, reviewed_inventory),
        )
    return output.getvalue()


def load_team_bundle(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path, "r") as archive:
        names = set(archive.namelist())
        required = {"manifest.json", "reviews.csv", "reviewed_inventory.csv"}
        if not required.issubset(names):
            raise ValueError(f"bundle is missing files: {sorted(required - names)}")
        manifest = json.loads(archive.read("manifest.json"))
        reviews = _read_csv_bytes(archive.read("reviews.csv"))
        inventory = _read_csv_bytes(archive.read("reviewed_inventory.csv"))
    if manifest.get("bundle_schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported team bundle schema")
    batch_id = str(manifest.get("batch_id") or "").strip()
    if not batch_id:
        raise ValueError("bundle manifest has blank batch_id")
    if int(manifest.get("review_count", -1)) != len(reviews):
        raise ValueError("bundle review_count does not match reviews.csv")
    for row in reviews:
        if _text(row, "batch_id") != batch_id:
            raise ValueError("review batch_id does not match bundle manifest")
    review_ids = {_text(row, "source_play_id") for row in reviews}
    inventory_ids = {_text(row, "source_play_id") for row in inventory}
    if review_ids != inventory_ids:
        raise ValueError("bundle reviews and reviewed inventory do not match")
    return {"manifest": manifest, "reviews": reviews, "inventory": inventory}


def _review_conflict_fields(
    first: Mapping[str, object],
    second: Mapping[str, object],
) -> list[str]:
    fields = sorted((set(first) | set(second)) - VOLATILE_REVIEW_FIELDS)
    return [field for field in fields if _text(first, field) != _text(second, field)]


def consolidate_team_bundles(paths: Iterable[Path]) -> dict[str, object]:
    bundles = [load_team_bundle(Path(path)) for path in paths]
    reviews_by_play: dict[str, list[dict[str, str]]] = defaultdict(list)
    inventory_by_play: dict[str, list[dict[str, str]]] = defaultdict(list)
    for bundle in bundles:
        for row in bundle["reviews"]:
            reviews_by_play[_text(row, "source_play_id")].append(row)
        for row in bundle["inventory"]:
            inventory_by_play[_text(row, "source_play_id")].append(row)

    merged_reviews: list[dict[str, str]] = []
    merged_inventory: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    conflict_play_ids: set[str] = set()

    for source_play_id in sorted(reviews_by_play):
        rows = reviews_by_play[source_play_id]
        first = dict(rows[0])
        differing = sorted(
            {
                field
                for row in rows[1:]
                for field in _review_conflict_fields(first, row)
            }
        )
        batch_ids = sorted({_text(row, "batch_id") for row in rows if _text(row, "batch_id")})
        if differing:
            conflict_play_ids.add(source_play_id)
            conflicts.append(
                {
                    "source_play_id": source_play_id,
                    "batch_ids": "+".join(batch_ids),
                    "conflict_fields": ";".join(differing),
                    "reason_zh": "不同批次对同一击球事件给出了不一致结论",
                    "review_rows_json": json.dumps(rows, ensure_ascii=False),
                }
            )
            continue
        first["batch_id"] = "+".join(batch_ids)
        merged_reviews.append(first)

        inventory_rows = inventory_by_play.get(source_play_id, [])
        if not inventory_rows:
            conflict_play_ids.add(source_play_id)
            conflicts.append(
                {
                    "source_play_id": source_play_id,
                    "batch_ids": "+".join(batch_ids),
                    "conflict_fields": "reviewed_inventory",
                    "reason_zh": "审核记录缺少对应的来源媒体元数据",
                    "review_rows_json": json.dumps(rows, ensure_ascii=False),
                }
            )
            merged_reviews.pop()
            continue
        source_video_ids = {
            _text(row, "source_video_id")
            for row in inventory_rows
            if _text(row, "source_video_id")
        }
        media_hashes = {
            _text(row, "media_sha256")
            for row in inventory_rows
            if _text(row, "media_sha256")
        }
        media_conflict = len(source_video_ids) > 1 or (
            not source_video_ids and len(media_hashes) > 1
        )
        if media_conflict:
            conflict_play_ids.add(source_play_id)
            conflicts.append(
                {
                    "source_play_id": source_play_id,
                    "batch_ids": "+".join(batch_ids),
                    "conflict_fields": "source_video_id;media_sha256",
                    "reason_zh": "同一击球事件在不同批次使用了不同来源视频",
                    "review_rows_json": json.dumps(rows, ensure_ascii=False),
                }
            )
            merged_reviews.pop()
            continue
        source = dict(inventory_rows[0])
        source["batch_ids"] = "+".join(batch_ids)
        merged_inventory.append(source)

    media_index: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: {"plays": set(), "batches": set()}
    )
    for row in merged_inventory:
        source_play_id = _text(row, "source_play_id")
        batch_ids = set(filter(None, _text(row, "batch_ids").split("+")))
        for identity_type, field in (
            ("source_video_id", "source_video_id"),
            ("media_sha256", "media_sha256"),
        ):
            identity = _text(row, field)
            if not identity:
                continue
            entry = media_index[(identity_type, identity)]
            entry["plays"].add(source_play_id)
            entry["batches"].update(batch_ids)

    media_warnings: list[dict[str, str]] = []
    held_play_ids: set[str] = set()
    for (identity_type, identity), entry in sorted(media_index.items()):
        if len(entry["plays"]) <= 1:
            continue
        held_play_ids.update(entry["plays"])
        media_warnings.append(
            {
                "media_identity_type": identity_type,
                "media_identity": identity,
                "source_play_ids": ";".join(sorted(entry["plays"])),
                "batch_ids": "+".join(sorted(entry["batches"])),
                "reason_zh": "同一视频关联了多个击球事件，疑似合集或错误匹配，已暂缓合并",
            }
        )

    if held_play_ids:
        merged_reviews = [
            row
            for row in merged_reviews
            if _text(row, "source_play_id") not in held_play_ids
        ]
        merged_inventory = [
            row
            for row in merged_inventory
            if _text(row, "source_play_id") not in held_play_ids
        ]

    return {
        "merged_reviews": merged_reviews,
        "merged_inventory": merged_inventory,
        "conflicts": conflicts,
        "media_warnings": media_warnings,
        "summary": {
            "bundle_count": len(bundles),
            "unique_reviewed_plays": len(reviews_by_play),
            "merged_plays": len(merged_reviews),
            "conflicting_plays": len(conflict_play_ids),
            "held_media_plays": len(held_play_ids),
            "media_warnings": len(media_warnings),
        },
    }


def atomic_write_csv(
    path: Path,
    fields: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(_csv_bytes(fields, rows))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_consolidation(output_dir: Path, result: Mapping[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_csv(output_dir / "merged_reviews.csv", REVIEW_FIELDS, result["merged_reviews"])
    atomic_write_csv(
        output_dir / "merged_reviewed_inventory.csv",
        TEAM_INVENTORY_FIELDS,
        result["merged_inventory"],
    )
    atomic_write_csv(output_dir / "conflicts.csv", CONFLICT_FIELDS, result["conflicts"])
    atomic_write_csv(
        output_dir / "media_warnings.csv",
        MEDIA_WARNING_FIELDS,
        result["media_warnings"],
    )
    temporary = output_dir / "summary.json.tmp"
    final = output_dir / "summary.json"
    try:
        temporary.write_text(
            json.dumps(result["summary"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, final)
    finally:
        if temporary.exists():
            temporary.unlink()
