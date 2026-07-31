#!/usr/bin/env python3
"""Local single-reviewer Flyball manual-calibration workbench."""

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

from contracts import ERROR_CODES, REVIEW_SCHEMA_VERSION
from review_store import ReviewStore, ReviewValidationError


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
SHARED_STATIC = HERE.parent / "groundball/static"
DEFAULT_SESSION = HERE.parent / "review_outputs/default/flyball"
DEFAULT_GENERATED = DEFAULT_SESSION / "generated"
DEFAULT_MANIFEST = DEFAULT_GENERATED / "flyball_calibration_manifest.csv"
DEFAULT_QUEUE = DEFAULT_GENERATED / "flyball_calibration_queue.csv"
DEFAULT_SUMMARY = DEFAULT_GENERATED / "manifest_summary.json"
DEFAULT_RESULTS = DEFAULT_SESSION / "flyball_reviews.csv"
DEFAULT_DATASET_ROOT = ROOT / "dataset"
RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
MAX_JSON_BODY = 64 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--reviewer-id", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def bool_value(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def float_or_none(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(str(value))


class CalibrationWorkbenchState:
    def __init__(
        self,
        manifest: Path,
        queue: Path,
        summary: Path,
        results: Path,
        dataset_root: Path,
        reviewer_id: str,
    ) -> None:
        self.manifest_path = manifest.resolve()
        self.queue_path = queue.resolve()
        self.summary_path = summary.resolve()
        self.admin_rows = read_csv(self.manifest_path)
        self.queue_rows = read_csv(self.queue_path)
        self.manifest_summary = json.loads(
            self.summary_path.read_text(encoding="utf-8")
        )
        self.queue_rows.sort(key=lambda row: int(row["queue_position"]))
        self.admin_by_id = {row["audit_id"]: row for row in self.admin_rows}
        self.queue_by_id = {row["audit_id"]: row for row in self.queue_rows}
        if len(self.admin_by_id) != len(self.admin_rows):
            raise RuntimeError("manifest contains duplicate audit IDs")
        if len(self.queue_by_id) != len(self.queue_rows):
            raise RuntimeError("queue contains duplicate audit IDs")
        missing = set(self.queue_by_id) - set(self.admin_by_id)
        if missing:
            raise RuntimeError(f"queue has {len(missing)} IDs missing from manifest")
        self.store = ReviewStore(
            results,
            self.admin_rows,
            self.queue_rows,
        )
        self._root = dataset_root.resolve()
        self.default_reviewer_id = reviewer_id.strip()

    def resolve_project_file(self, relative_path: str) -> Path:
        candidate = (self._root / relative_path).resolve()
        if not candidate.is_relative_to(self._root):
            raise PermissionError("manifest path escapes project root")
        return candidate

    def media_state(self, audit_id: str, kind: str) -> str:
        row = self.admin_by_id[audit_id]
        field = "audio_relpath" if kind == "audio" else "video_relpath"
        return (
            "ready_local"
            if self.resolve_project_file(row[field]).is_file()
            else "missing"
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
                    "batch_number": int(row["batch_number"]),
                    "batch_position": int(row["batch_position"]),
                    "sample_id": row["sample_id"],
                    "audio_state": self.media_state(audit_id, "audio"),
                    "video_state": self.media_state(audit_id, "video"),
                    "conclusion": review["conclusion"] if review else None,
                    "error_codes": review["error_codes"] if review else "",
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
            "workbench_kind": "flyball_calibration",
            "results_schema_version": REVIEW_SCHEMA_VERSION,
            "default_reviewer_id": self.default_reviewer_id,
            "results_relpath": results_relpath,
            "manifest_summary": self.manifest_summary,
            "error_codes": ERROR_CODES,
            "summary": self.store.summary(),
            "samples": self.public_queue(),
        }

    def public_sample(self, audit_id: str) -> dict[str, object]:
        admin = self.admin_by_id[audit_id]
        queue = self.queue_by_id[audit_id]
        audio_ready = self.media_state(audit_id, "audio") == "ready_local"
        video_ready = self.media_state(audit_id, "video") == "ready_local"
        return {
            "audit_id": audit_id,
            "position": int(queue["queue_position"]),
            "total": len(self.queue_rows),
            "batch_number": int(queue["batch_number"]),
            "batch_position": int(queue["batch_position"]),
            "sample_id": admin["sample_id"],
            "recorded_trajectory": admin["recorded_trajectory"],
            "landing_zone": admin["landing_zone"],
            "strength": admin["strength"],
            "event_start": float_or_none(admin["event_start"]),
            "event_end": float_or_none(admin["event_end"]),
            "candidate_interval_valid": bool_value(
                admin["candidate_interval_valid"]
            ),
            "audio_duration_sec": float_or_none(admin["audio_duration_sec"]),
            "proposed_contact_time": float_or_none(
                admin["proposed_contact_time"]
            ),
            "proposal_source": admin["proposal_source"],
            "audio_state": "ready_local" if audio_ready else "missing",
            "video_state": "ready_local" if video_ready else "missing",
            "audio_url": f"/media/{audit_id}/audio" if audio_ready else None,
            "video_url": f"/media/{audit_id}/video" if video_ready else None,
            "review": self.store.get(audit_id),
        }

    def troubleshooting_sample(self, audit_id: str) -> dict[str, object]:
        row = self.admin_by_id[audit_id]
        return {
            "audit_id": audit_id,
            "uid": row["uid"],
            "sample_id": row["sample_id"],
            "dataset_commit": row["dataset_commit"],
            "sample_relpath": row["sample_relpath"],
            "audio_relpath": row["audio_relpath"],
            "video_relpath": row["video_relpath"],
            "csv_relpath": row["csv_relpath"],
            "label_relpath": row["label_relpath"],
            "expected_audio_blob_sha1": row["expected_audio_blob_sha1"],
            "expected_video_blob_sha1": row["expected_video_blob_sha1"],
            "data_issues": row["data_issues"],
        }

    def media_path(self, audit_id: str, kind: str) -> Path:
        row = self.admin_by_id[audit_id]
        field = "audio_relpath" if kind == "audio" else "video_relpath"
        path = self.resolve_project_file(row[field])
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def save_review(
        self,
        audit_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        review = self.store.upsert(audit_id, payload)
        return {"review": review, "summary": self.store.summary()}

    def remove_review(self, audit_id: str) -> dict[str, object]:
        removed = self.store.remove(audit_id)
        return {"removed": removed, "summary": self.store.summary()}


class CalibrationHandler(BaseHTTPRequestHandler):
    server_version = "FlyballCalibrationWorkbench/1.0"
    state: CalibrationWorkbenchState

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[flyball-calibration] {self.address_string()} {format_string % args}")

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/":
                self.send_file(STATIC / "index.html", allow_range=False)
                return
            if path == "/api/health":
                self.send_json(
                    {
                        "status": "ok",
                        "workbench_kind": "flyball_calibration",
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
                    "flyball_calibration_reviews.csv",
                )
                return
            if path.startswith("/api/sample/"):
                self.send_json(self.state.public_sample(path.rsplit("/", 1)[-1]))
                return
            if path.startswith("/api/troubleshooting/"):
                self.send_json(
                    self.state.troubleshooting_sample(path.rsplit("/", 1)[-1])
                )
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
                self.send_static(STATIC, path.removeprefix("/static/"))
                return
            if path.startswith("/shared/"):
                self.send_static(SHARED_STATIC, path.removeprefix("/shared/"))
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "route not found")
        except KeyError:
            self.send_error_json(HTTPStatus.NOT_FOUND, "unknown audit ID")
        except FileNotFoundError:
            self.send_error_json(HTTPStatus.NOT_FOUND, "media is missing")
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
                self.send_json(self.state.save_review(audit_id, self.read_json()))
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "route not found")
        except KeyError:
            self.send_error_json(HTTPStatus.NOT_FOUND, "unknown audit ID")
        except (ReviewValidationError, ValueError) as error:
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
                self.send_json(
                    self.state.remove_review(path.rsplit("/", 1)[-1])
                )
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
                self.send_error_json(HTTPStatus.NOT_FOUND, "media is missing")
                return
            self.send_file(media, allow_range=True, send_body=False)
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "route not found")

    def send_static(self, root: Path, relative: str) -> None:
        candidate = (root / Path(relative)).resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise PermissionError("static path escapes root")
        self.send_file(candidate, allow_range=False)

    def read_json(self) -> dict[str, Any]:
        length_text = self.headers.get("Content-Length")
        if length_text is None:
            raise ValueError("missing request body")
        length = int(length_text)
        if length <= 0 or length > MAX_JSON_BODY:
            raise ValueError("invalid request body size")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        return payload

    def send_json(
        self,
        payload: object,
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
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
        self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
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
    state = CalibrationWorkbenchState(
        args.manifest,
        args.queue,
        args.summary,
        args.results,
        args.dataset_root,
        args.reviewer_id,
    )
    CalibrationHandler.state = state
    server = ThreadingHTTPServer((args.host, args.port), CalibrationHandler)
    server.daemon_threads = True
    url = f"http://{args.host}:{args.port}/"
    print("Flyball calibration workbench — portable assignment session.")
    print(f"Loaded {len(state.queue_rows)} candidates.")
    print(f"Reviews save atomically to {state.store.path}")
    print(f"Open {url}")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Flyball calibration workbench.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
