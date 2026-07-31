#!/usr/bin/env python3
"""Local single-reviewer contact-and-timing audit workbench."""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

from review_store import ReviewStore, ReviewValidationError


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
DEFAULT_SESSION = HERE.parent / "review_outputs/default/groundball"
DEFAULT_ADMIN_MANIFEST = DEFAULT_SESSION / "generated/audit_manifest_admin.csv"
DEFAULT_QUEUE = DEFAULT_SESSION / "generated/review_queue_blinded.csv"
DEFAULT_MANIFEST_SUMMARY = DEFAULT_SESSION / "generated/manifest_summary.json"
DEFAULT_RESULTS = DEFAULT_SESSION / "groundball_reviews.csv"
RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
MAX_JSON_BODY = 64 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-manifest", type=Path, default=DEFAULT_ADMIN_MANIFEST)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument(
        "--manifest-summary", type=Path, default=DEFAULT_MANIFEST_SUMMARY
    )
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def bool_value(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


class VideoPreparationManager:
    """Compatibility shim: portable sessions never download source media."""

    def __init__(
        self,
        admin_manifest: Path,
        queue: Path,
        results: Path,
    ) -> None:
        self._status: dict[str, object] = {
            "state": "unavailable",
            "started_at_utc": None,
            "finished_at_utc": None,
            "summary": None,
            "error": (
                "Portable team-review sessions do not download or modify media; "
                "select a dataset that already contains video.mp4."
            ),
        }

    def snapshot(self) -> dict[str, object]:
        return dict(self._status)

    def start(self, start_audit_id: str, max_files: int) -> dict[str, object]:
        raise ReviewValidationError(str(self._status["error"]))


class AuditWorkbenchState:
    """Joins the blinded queue, administrative paths, media, and review store."""

    def __init__(
        self,
        admin_manifest: Path,
        queue: Path,
        manifest_summary: Path,
        results: Path,
    ) -> None:
        self.admin_manifest_path = admin_manifest.resolve()
        self.queue_path = queue.resolve()
        self.manifest_summary_path = manifest_summary.resolve()
        self.admin_rows = read_csv(self.admin_manifest_path)
        self.queue_rows = read_csv(self.queue_path)
        self.manifest_summary = json.loads(
            self.manifest_summary_path.read_text(encoding="utf-8")
        )
        self.queue_rows.sort(key=lambda row: int(row["queue_position"]))
        self.admin_by_id = {row["audit_id"]: row for row in self.admin_rows}
        self.queue_by_id = {row["audit_id"]: row for row in self.queue_rows}

        if len(self.admin_by_id) != len(self.admin_rows):
            raise RuntimeError("administrator manifest contains duplicate audit IDs")
        if len(self.queue_by_id) != len(self.queue_rows):
            raise RuntimeError("review queue contains duplicate audit IDs")
        missing = sorted(set(self.queue_by_id) - set(self.admin_by_id))
        if missing:
            raise RuntimeError(
                f"review queue contains {len(missing)} IDs absent from administrator manifest"
            )
        queue_label = str(self.manifest_summary.get("queue_label_filter", "all"))
        mislabeled = [
            audit_id
            for audit_id in self.queue_by_id
            if queue_label != "all"
            and self.admin_by_id[audit_id]["label"] != queue_label
        ]
        if mislabeled:
            raise RuntimeError(
                f"review queue contains {len(mislabeled)} samples outside {queue_label}"
            )

        self.store = ReviewStore(results, self.admin_rows, self.queue_rows)
        self.video_preparation = VideoPreparationManager(
            self.admin_manifest_path,
            self.queue_path,
            self.store.path,
        )
        self._root = ROOT.resolve()

    def resolve_repo_file(self, relative_path: str) -> Path:
        candidate = (ROOT / relative_path).resolve()
        if not candidate.is_relative_to(self._root):
            raise PermissionError("manifest path escapes repository root")
        return candidate

    def actual_video_state(self, audit_id: str) -> str:
        row = self.admin_by_id[audit_id]
        return (
            "ready_local"
            if self.resolve_repo_file(row["video_relpath"]).is_file()
            else "missing_not_prepared"
        )

    def public_queue(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for row in self.queue_rows:
            audit_id = row["audit_id"]
            review = self.store.get(audit_id)
            items.append(
                {
                    "audit_id": audit_id,
                    "position": int(row["queue_position"]),
                    "audio_available": bool_value(row["audio_available"]),
                    "video_state": self.actual_video_state(audit_id),
                    "review_status": (
                        review["review_status"] if review is not None else None
                    ),
                    "material_reason": (
                        review["material_reason"] if review is not None else ""
                    ),
                }
            )
        return items

    def workbench_payload(self) -> dict[str, object]:
        try:
            results_relpath = self.store.path.relative_to(self._root).as_posix()
        except ValueError:
            results_relpath = str(self.store.path)
        return {
            "formal_workbench": True,
            "queue_schema_version": (
                self.queue_rows[0]["schema_version"] if self.queue_rows else None
            ),
            "results_schema_version": "contact-audit-review-v1",
            "results_relpath": results_relpath,
            "queue_scope": {
                "label_filter": self.manifest_summary.get(
                    "queue_label_filter", "all"
                ),
                "label_population_count": self.manifest_summary.get(
                    "queue_label_population_count"
                ),
                "risk_adaptive_queue_count": len(self.queue_rows),
                "dataset_commit": self.manifest_summary.get("dataset_commit"),
                "verified_upstream_commit": self.manifest_summary.get(
                    "verified_upstream_commit"
                ),
                "label_subtree_sha1": self.manifest_summary.get(
                    "queue_label_subtree_sha1"
                ),
                "label_subtree_unchanged": self.manifest_summary.get(
                    "queue_label_subtree_unchanged_from_dataset_commit", False
                ),
            },
            "summary": self.store.summary(),
            "samples": self.public_queue(),
        }

    def public_sample(self, audit_id: str) -> dict[str, object]:
        queue_row = self.queue_by_id[audit_id]
        admin_row = self.admin_by_id[audit_id]
        video_state = self.actual_video_state(audit_id)
        return {
            "audit_id": audit_id,
            "position": int(queue_row["queue_position"]),
            "total": len(self.queue_rows),
            "audio_available": bool_value(admin_row["audio_available"]),
            "video_state": video_state,
            "event_start": float_or_none(admin_row["event_start"]),
            "event_end": float_or_none(admin_row["event_end"]),
            "auto_hit_time": float_or_none(admin_row["auto_hit_time"]),
            "auto_hit_source": admin_row["auto_hit_source"],
            "candidate_interval_valid": bool_value(
                admin_row["candidate_interval_valid"]
            ),
            "audio_duration_sec": float_or_none(admin_row["audio_duration_sec"]),
            "audio_url": f"/media/{audit_id}/audio",
            "video_url": (
                f"/media/{audit_id}/video" if video_state == "ready_local" else None
            ),
            "review": self.store.get(audit_id),
        }

    def troubleshooting_sample(self, audit_id: str) -> dict[str, object]:
        row = self.admin_by_id[audit_id]
        return {
            "audit_id": audit_id,
            "uid": row["uid"],
            "collector": row["collector"],
            "label": row["label"],
            "annotation_semantics": row["annotation_semantics"],
            "sample_relpath": row["sample_relpath"],
            "audio_relpath": row["audio_relpath"],
            "video_relpath": row["video_relpath"],
            "timing_status": row["timing_status"],
            "timing_reasons": row["timing_reasons"],
            "data_issues": row["data_issues"],
            "risk_reasons": row["risk_reasons"],
        }

    def media_path(self, audit_id: str, media_kind: str) -> Path:
        row = self.admin_by_id[audit_id]
        field = "audio_relpath" if media_kind == "audio" else "video_relpath"
        path = self.resolve_repo_file(row[field])
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def save_review(
        self, audit_id: str, payload: Mapping[str, object]
    ) -> dict[str, object]:
        review = self.store.upsert(audit_id, payload)
        return {"review": review, "summary": self.store.summary()}

    def remove_review(self, audit_id: str) -> dict[str, object]:
        removed = self.store.remove(audit_id)
        return {"removed": removed, "summary": self.store.summary()}


class AuditWorkbenchHandler(BaseHTTPRequestHandler):
    server_version = "ContactAuditWorkbench/1.0"
    state: AuditWorkbenchState

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[contact-audit] {self.address_string()} {format_string % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/":
                self.send_file(STATIC / "index.html", allow_range=False)
                return
            if path == "/api/health":
                self.send_json(
                    {
                        "status": "ok",
                        "formal_workbench": True,
                        "total": len(self.state.queue_rows),
                        "reviewed": self.state.store.summary()["reviewed"],
                    }
                )
                return
            if path == "/api/workbench":
                self.send_json(self.state.workbench_payload())
                return
            if path == "/api/reviews/export":
                self.send_csv_download(
                    self.state.store.export_bytes(),
                    "contact_audit_reviews.csv",
                )
                return
            if path == "/api/video-preparation":
                self.send_json(self.state.video_preparation.snapshot())
                return
            if path.startswith("/api/sample/"):
                audit_id = path.rsplit("/", 1)[-1]
                self.send_json(self.state.public_sample(audit_id))
                return
            if path.startswith("/api/troubleshooting/"):
                audit_id = path.rsplit("/", 1)[-1]
                self.send_json(self.state.troubleshooting_sample(audit_id))
                return
            if path.startswith("/media/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) != 3 or parts[2] not in {"audio", "video"}:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "unknown media route")
                    return
                self.send_file(
                    self.state.media_path(parts[1], parts[2]),
                    allow_range=True,
                )
                return
            if path.startswith("/static/"):
                relative = Path(path.removeprefix("/static/"))
                candidate = (STATIC / relative).resolve()
                if not candidate.is_relative_to(STATIC.resolve()):
                    self.send_error_json(HTTPStatus.FORBIDDEN, "forbidden static path")
                    return
                self.send_file(candidate, allow_range=False)
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "route not found")
        except KeyError:
            self.send_error_json(HTTPStatus.NOT_FOUND, "unknown audit ID")
        except FileNotFoundError:
            self.send_error_json(HTTPStatus.NOT_FOUND, "media is not prepared")
        except PermissionError:
            self.send_error_json(HTTPStatus.FORBIDDEN, "forbidden path")
        except Exception as error:
            self.send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"{type(error).__name__}: {error}",
            )

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            if path.startswith("/api/review/"):
                audit_id = path.rsplit("/", 1)[-1]
                payload = self.read_json()
                self.send_json(
                    self.state.save_review(audit_id, payload),
                    status=HTTPStatus.OK,
                )
                return
            if path == "/api/video-preparation":
                payload = self.read_json()
                start_audit_id = str(payload.get("start_audit_id", "")).strip()
                if start_audit_id not in self.state.queue_by_id:
                    raise ReviewValidationError(
                        "video preparation start ID is not in the queue"
                    )
                max_files = int(payload.get("max_files", 25))
                self.send_json(
                    self.state.video_preparation.start(
                        start_audit_id,
                        max_files,
                    ),
                    status=HTTPStatus.ACCEPTED,
                )
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "route not found")
        except KeyError:
            self.send_error_json(HTTPStatus.NOT_FOUND, "unknown audit ID")
        except ReviewValidationError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except Exception as error:
            self.send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"{type(error).__name__}: {error}",
            )

    def do_DELETE(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            if path.startswith("/api/review/"):
                audit_id = path.rsplit("/", 1)[-1]
                self.send_json(self.state.remove_review(audit_id))
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "route not found")
        except KeyError:
            self.send_error_json(HTTPStatus.NOT_FOUND, "unknown audit ID")
        except Exception as error:
            self.send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                f"{type(error).__name__}: {error}",
            )

    def do_HEAD(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path.startswith("/media/"):
            parts = [part for part in path.split("/") if part]
            try:
                media = self.state.media_path(parts[1], parts[2])
            except (IndexError, KeyError, FileNotFoundError):
                self.send_error_json(HTTPStatus.NOT_FOUND, "media is not prepared")
                return
            self.send_file(media, allow_range=True, send_body=False)
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "route not found")

    def read_json(self) -> dict[str, Any]:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ValueError("missing request body")
        length = int(content_length)
        if length <= 0 or length > MAX_JSON_BODY:
            raise ValueError("invalid request body size")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def send_json(
        self,
        payload: object,
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status=status)

    def send_csv_download(self, body: bytes, filename: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"',
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(
        self,
        path: Path,
        *,
        allow_range: bool,
        send_body: bool = True,
    ) -> None:
        if not path.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "file not found")
            return
        size = path.stat().st_size
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        partial = False

        if allow_range and (range_header := self.headers.get("Range")):
            match = RANGE_PATTERN.match(range_header.strip())
            if not match:
                self.send_error_json(
                    HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                    "invalid byte range",
                )
                return
            start_text, end_text = match.groups()
            if start_text:
                start = int(start_text)
                end = int(end_text) if end_text else size - 1
            elif end_text:
                suffix = int(end_text)
                start = max(0, size - suffix)
                end = size - 1
            if start >= size or start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
            partial = True

        length = max(0, end - start + 1)
        self.send_response(
            HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK
        )
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header(
            "Cache-Control",
            "public, max-age=31536000, immutable"
            if "/vendor/" in path.as_posix()
            else "no-store",
        )
        self.end_headers()
        if not send_body:
            return

        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def main() -> None:
    args = parse_args()
    state = AuditWorkbenchState(
        args.admin_manifest,
        args.queue,
        args.manifest_summary,
        args.results,
    )
    AuditWorkbenchHandler.state = state
    server = ThreadingHTTPServer((args.host, args.port), AuditWorkbenchHandler)
    server.daemon_threads = True
    url = f"http://{args.host}:{args.port}/"
    print("Contact audit workbench — local formal single-reviewer version.")
    print(f"Loaded {len(state.queue_rows)} queued samples.")
    print(f"Reviews save atomically to {state.store.path}")
    print(f"Open {url}")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping contact audit workbench.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
