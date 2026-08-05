#!/usr/bin/env python3
"""Local single-reviewer MLB candidate-curation workbench."""

from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlparse

from contracts import (
    EXCLUSION_REASONS,
    OBSERVED_TRAJECTORIES,
    REVIEW_FIELDS,
)
from stores import (
    BatchReviewStore,
    CandidateInventoryStore,
    StoreValidationError,
)
from team_bundles import build_team_bundle_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
DEFAULT_DATA = PROJECT_ROOT / "data" / "review" / "mlb_candidate_curation"
RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
MAX_JSON_BODY = 64 * 1024

TRAJECTORY_LABELS_ZH = {
    "ground_ball": "滚地球",
    "fly_ball": "飞球",
    "line_drive": "平直球",
    "pop_fly": "高飞球",
    "unknown": "无法判断",
}
EXCLUSION_LABELS_ZH = {
    "no_contact": "没有击球接触",
    "audio_video_mismatch": "音画不是同一次击球",
    "trajectory_not_visible": "看不清球的初始轨迹",
    "replay_or_slow_motion": "只有回放或慢动作",
    "duplicate_play": "重复比赛事件",
    "multiple_distinct_plays": "视频包含多个不同击球事件",
    "broken_media": "音频或视频损坏",
    "wrong_play": "视频与 MLB 事件匹配错误",
    "foul_ball": "界外球或擦棒",
    "bunt_or_check_swing": "触击或明显收棒式击球",
    "other": "其他明确问题",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=DEFAULT_DATA / "candidate_inventory.csv",
    )
    parser.add_argument(
        "--reviews",
        type=Path,
        default=DEFAULT_DATA / "reviews" / "local.csv",
    )
    parser.add_argument("--batch-id", default="local")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def _float_or_none(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _csv_bytes(fields: list[str], rows: list[Mapping[str, object]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


class CurationWorkbenchState:
    def __init__(
        self,
        inventory_path: Path,
        reviews_path: Path,
        batch_id: str,
        assigned_start_date: str = "",
        assigned_end_date: str = "",
    ) -> None:
        self.inventory = CandidateInventoryStore(inventory_path)
        self.reviews = BatchReviewStore(
            reviews_path,
            batch_id,
            self.inventory.all(),
        )
        self._root = PROJECT_ROOT.resolve()
        self.assigned_start_date = assigned_start_date.strip()
        self.assigned_end_date = assigned_end_date.strip()
        self._inventory_by_id = {
            row["source_play_id"]: row for row in self.inventory.all()
        }

    def _resolve_project_file(self, relative_path: str) -> Path:
        if not relative_path.strip():
            raise FileNotFoundError("blank media path")
        candidate = (self._root / relative_path).resolve()
        if not candidate.is_relative_to(self._root):
            raise PermissionError("media path escapes the project root")
        return candidate

    def media_path(self, source_play_id: str, kind: str) -> Path:
        row = self._inventory_by_id[source_play_id]
        if kind == "video":
            path = self._resolve_project_file(str(row.get("video_relpath") or ""))
        elif kind == "audio":
            path = self._resolve_project_file(str(row.get("audio_relpath") or ""))
        elif kind == "enhanced":
            original = self._resolve_project_file(
                str(row.get("audio_relpath") or "")
            )
            path = original.with_name("audio_contact_enhanced.wav")
            if not path.is_relative_to(self._root):
                raise PermissionError("enhanced media path escapes project root")
        else:
            raise KeyError(kind)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def _media_ready(self, source_play_id: str, kind: str) -> bool:
        try:
            self.media_path(source_play_id, kind)
            return True
        except (FileNotFoundError, PermissionError):
            return False

    def queue(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for row in self.inventory.all():
            source_play_id = str(row["source_play_id"])
            review = self.reviews.get(source_play_id)
            if str(row.get("media_status") or "") != "prepared" and not review:
                continue
            items.append(
                {
                    "source_play_id": source_play_id,
                    "game_date": row.get("game_date", ""),
                    "game_pk": row.get("game_pk", ""),
                    "batter": row.get("batter", ""),
                    "trajectory_hint": row.get("mlb_trajectory_raw", ""),
                    "location_hint": row.get("mlb_location_raw", ""),
                    "media_status": row.get("media_status", ""),
                    "media_ready": self._media_ready(source_play_id, "audio")
                    and self._media_ready(source_play_id, "video"),
                    "review_status": review["admission_status"] if review else "",
                    "reviewed_trajectory": (
                        review["observed_trajectory"] if review else ""
                    ),
                }
            )
        items.sort(
            key=lambda row: (
                str(row["game_date"]),
                str(row["source_play_id"]),
            )
        )
        for index, item in enumerate(items, start=1):
            item["position"] = index
        return items

    def workbench_payload(self) -> dict[str, object]:
        return {
            "formal_workbench": True,
            "workbench_kind": "mlb_candidate_curation",
            "batch_id": self.reviews.batch_id,
            "assigned_start_date": self.assigned_start_date,
            "assigned_end_date": self.assigned_end_date,
            "results_path": str(self.reviews.path),
            "summary": self.reviews.summary(),
            "trajectory_labels_zh": TRAJECTORY_LABELS_ZH,
            "exclusion_labels_zh": EXCLUSION_LABELS_ZH,
            "samples": self.queue(),
        }

    def sample(self, source_play_id: str) -> dict[str, object]:
        row = self._inventory_by_id[source_play_id]
        candidates = [
            {
                "rank": rank,
                "time_sec": _float_or_none(row.get(f"auto_hit_time_{rank}")),
                "score": _float_or_none(row.get(f"auto_hit_score_{rank}")),
            }
            for rank in range(1, 4)
            if _float_or_none(row.get(f"auto_hit_time_{rank}")) is not None
        ]
        queue = self.queue()
        queue_item = next(
            item for item in queue if item["source_play_id"] == source_play_id
        )
        video_ready = self._media_ready(source_play_id, "video")
        audio_ready = self._media_ready(source_play_id, "audio")
        enhanced_ready = self._media_ready(source_play_id, "enhanced")
        return {
            **queue_item,
            "total": len(queue),
            "game_info": row.get("game_info", ""),
            "inning": row.get("inning", ""),
            "half_inning": row.get("half_inning", ""),
            "pitcher": row.get("pitcher", ""),
            "mlb_event_raw": row.get("mlb_event_raw", ""),
            "play_description": row.get("play_description", ""),
            "source_title": row.get("source_title", ""),
            "source_page_url": row.get("source_page_url", ""),
            "media_match_confidence": row.get("media_match_confidence", ""),
            "media_match_reason_zh": row.get("media_match_reason_zh", ""),
            "media_duration_sec": _float_or_none(row.get("media_duration_sec")),
            "mlb_trajectory_raw": row.get("mlb_trajectory_raw", ""),
            "mlb_location_raw": row.get("mlb_location_raw", ""),
            "detector_version": row.get("detector_version", ""),
            "contact_candidates": candidates,
            "video_url": (
                f"/media/video/{source_play_id}" if video_ready else None
            ),
            "audio_url": (
                f"/media/audio/{source_play_id}" if audio_ready else None
            ),
            "enhanced_audio_url": (
                f"/media/enhanced/{source_play_id}" if enhanced_ready else None
            ),
            "review": self.reviews.get(source_play_id),
        }

    def save_review(
        self,
        source_play_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        review = self.reviews.upsert(source_play_id, payload)
        return {"review": review, "summary": self.reviews.summary()}

    def remove_review(self, source_play_id: str) -> dict[str, object]:
        removed = self.reviews.remove(source_play_id)
        return {"removed": removed, "summary": self.reviews.summary()}

    def combined_export_bytes(self) -> bytes:
        review_by_id = {
            row["source_play_id"]: row for row in self.reviews.all()
        }
        fields = [
            "source_play_id",
            "game_pk",
            "play_id",
            "game_date",
            "batter",
            "pitcher",
            "play_description",
            "mlb_trajectory_raw",
            "mlb_location_raw",
            "source_page_url",
            "source_video_id",
            "source_title",
            "media_match_confidence",
            "media_status",
            "media_duration_sec",
            "auto_hit_time_1",
            "auto_hit_time_2",
            "auto_hit_time_3",
            *[
                field
                for field in REVIEW_FIELDS
                if field not in {"source_play_id", "mlb_location_raw"}
            ],
        ]
        rows: list[dict[str, object]] = []
        for inventory in self.inventory.all():
            source_play_id = inventory["source_play_id"]
            review = review_by_id.get(source_play_id)
            if not review:
                continue
            rows.append({**inventory, **review, "source_play_id": source_play_id})
        return _csv_bytes(fields, rows)

    def team_bundle_bytes(self) -> bytes:
        return build_team_bundle_bytes(
            self.inventory.all(),
            self.reviews.all(),
            self._root,
            batch_id=self.reviews.batch_id,
            assigned_start_date=self.assigned_start_date,
            assigned_end_date=self.assigned_end_date,
        )


class CurationHandler(BaseHTTPRequestHandler):
    server_version = "MLBCandidateCuration/1.0"
    state: CurationWorkbenchState

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[mlb-curation] {self.address_string()} {format_string % args}")

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/":
                self._send_file(STATIC / "index.html", allow_range=False)
            elif path == "/api/health":
                self._send_json(
                    {
                        "status": "ok",
                        "workbench_kind": "mlb_candidate_curation",
                        "queue_total": len(self.state.queue()),
                        "reviewed": self.state.reviews.summary()["reviewed"],
                    }
                )
            elif path == "/api/workbench":
                self._send_json(self.state.workbench_payload())
            elif path == "/api/reviews/export":
                self._send_download(
                    self.state.reviews.export_bytes(),
                    "mlb_candidate_reviews.csv",
                )
            elif path == "/api/audit/export":
                self._send_download(
                    self.state.combined_export_bytes(),
                    "mlb_candidate_audit_combined.csv",
                )
            elif path == "/api/team-bundle/export":
                self._send_download(
                    self.state.team_bundle_bytes(),
                    f"mlb_curation_{self.state.reviews.batch_id}.zip",
                    content_type="application/zip",
                )
            elif path.startswith("/api/sample/"):
                source_play_id = path.removeprefix("/api/sample/")
                self._send_json(self.state.sample(source_play_id))
            elif path.startswith("/media/"):
                remainder = path.removeprefix("/media/")
                kind, separator, source_play_id = remainder.partition("/")
                if not separator or kind not in {"video", "audio", "enhanced"}:
                    self._send_error_json(HTTPStatus.NOT_FOUND, "unknown media route")
                    return
                self._send_file(
                    self.state.media_path(source_play_id, kind),
                    allow_range=True,
                )
            elif path.startswith("/static/"):
                self._send_static(STATIC, path.removeprefix("/static/"))
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, "route not found")
        except KeyError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "unknown source_play_id")
        except FileNotFoundError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "media not found")
        except PermissionError as error:
            self._send_error_json(HTTPStatus.FORBIDDEN, str(error))
        except Exception as error:
            self._send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"{type(error).__name__}: {error}",
            )

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        if not path.startswith("/api/review/"):
            self._send_error_json(HTTPStatus.NOT_FOUND, "route not found")
            return
        try:
            source_play_id = path.removeprefix("/api/review/")
            payload = self._read_json()
            self._send_json(self.state.save_review(source_play_id, payload))
        except KeyError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "unknown source_play_id")
        except (StoreValidationError, ValueError) as error:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except Exception as error:
            self._send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"{type(error).__name__}: {error}",
            )

    def do_DELETE(self) -> None:
        path = unquote(urlparse(self.path).path)
        if not path.startswith("/api/review/"):
            self._send_error_json(HTTPStatus.NOT_FOUND, "route not found")
            return
        try:
            source_play_id = path.removeprefix("/api/review/")
            self._send_json(self.state.remove_review(source_play_id))
        except KeyError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "unknown source_play_id")

    def _read_json(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if length <= 0 or length > MAX_JSON_BODY:
            raise ValueError("invalid JSON body size")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status)

    def _send_download(
        self,
        body: bytes,
        filename: str,
        *,
        content_type: str = "text/csv; charset=utf-8",
    ) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"',
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, root: Path, relative_path: str) -> None:
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root.resolve()):
            self._send_error_json(HTTPStatus.FORBIDDEN, "static path escapes root")
            return
        self._send_file(candidate, allow_range=False)

    def _send_file(self, path: Path, *, allow_range: bool) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)
        file_size = path.stat().st_size
        start = 0
        end = file_size - 1
        partial = False
        range_header = self.headers.get("Range") if allow_range else None
        if range_header:
            match = RANGE_PATTERN.match(range_header.strip())
            if not match:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            first, last = match.groups()
            if first:
                start = int(first)
                end = int(last) if last else end
            elif last:
                suffix = int(last)
                start = max(0, file_size - suffix)
            if start < 0 or end >= file_size or start > end:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            partial = True
        length = end - start + 1
        self.send_response(
            HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK
        )
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def build_server(
    state: CurationWorkbenchState,
    host: str,
    port: int,
) -> ThreadingHTTPServer:
    handler = type(
        "BoundCurationHandler",
        (CurationHandler,),
        {"state": state},
    )
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    args = parse_args()
    state = CurationWorkbenchState(
        args.inventory,
        args.reviews,
        args.batch_id,
        args.start_date,
        args.end_date,
    )
    server = build_server(state, args.host, args.port)
    url = f"http://{args.host}:{server.server_address[1]}/"
    print(f"MLB candidate-curation workbench: {url}")
    print(f"Inventory: {state.inventory.path}")
    print(f"Reviews: {state.reviews.path}")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping workbench.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
