#!/usr/bin/env python3
"""Local Groundball owner-validation workbench with legacy review display."""

from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlparse

import server as legacy_server
import legacy_bridge
from contracts import ERROR_CODES, REVIEW_SCHEMA_VERSION
from validation_store import (
    ReviewValidationError,
    ValidationStore,
)


ROOT = legacy_server.ROOT
HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
DEFAULT_SESSION = HERE.parent / "review_outputs/default/groundball"
DEFAULT_ADMIN_MANIFEST = DEFAULT_SESSION / "generated/audit_manifest_admin.csv"
DEFAULT_QUEUE = DEFAULT_SESSION / "generated/review_queue_blinded.csv"
DEFAULT_MANIFEST_SUMMARY = DEFAULT_SESSION / "generated/manifest_summary.json"
DEFAULT_RESULTS = DEFAULT_SESSION / "groundball_reviews.csv"
DEFAULT_LEGACY_RESULTS = DEFAULT_SESSION / "no_legacy.csv"
DEFAULT_DATASET_ROOT = ROOT / "dataset"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-manifest", type=Path, default=DEFAULT_ADMIN_MANIFEST)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument(
        "--manifest-summary",
        type=Path,
        default=DEFAULT_MANIFEST_SUMMARY,
    )
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument(
        "--legacy-results",
        type=Path,
        default=DEFAULT_LEGACY_RESULTS,
    )
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--reviewer-id", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


class DisabledVideoPreparationManager:
    """Portable sessions never download or modify source media."""

    def snapshot(self) -> dict[str, object]:
        return {
            "state": "unavailable",
            "started_at_utc": None,
            "finished_at_utc": None,
            "summary": None,
            "error": "便携版不会在线下载或修改视频；请提供包含媒体的数据目录。",
        }

    def start(self, start_audit_id: str, max_files: int) -> dict[str, object]:
        raise ReviewValidationError(
            "便携版不会在线下载或修改视频；请提供包含 video.mp4 的数据目录。"
        )


class OwnerValidationState:
    """Joins the Groundball queue, new form, legacy display, and local media."""

    def __init__(
        self,
        admin_manifest: Path,
        queue: Path,
        manifest_summary: Path,
        results: Path,
        legacy_results: Path,
        dataset_root: Path,
        reviewer_id: str,
    ) -> None:
        self.admin_manifest_path = admin_manifest.resolve()
        self.queue_path = queue.resolve()
        self.manifest_summary_path = manifest_summary.resolve()
        self.admin_rows = legacy_server.read_csv(self.admin_manifest_path)
        self.queue_rows = legacy_server.read_csv(self.queue_path)
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
                f"review queue contains {len(missing)} IDs absent from manifest"
            )
        queue_label = str(self.manifest_summary.get("queue_label_filter", "all"))
        if queue_label != "ground_ball":
            raise RuntimeError(
                "owner-validation workbench requires a ground_ball-only queue"
            )
        mislabeled = [
            audit_id
            for audit_id in self.queue_by_id
            if self.admin_by_id[audit_id]["label"] != "ground_ball"
        ]
        if mislabeled:
            raise RuntimeError(
                f"review queue contains {len(mislabeled)} non-ground samples"
            )

        self.store = ValidationStore(
            results,
            legacy_results,
            self.admin_rows,
            self.queue_rows,
        )
        self.video_preparation = DisabledVideoPreparationManager()
        self._root = dataset_root.resolve()
        self.default_reviewer_id = reviewer_id.strip()

    def resolve_repo_file(self, relative_path: str) -> Path:
        candidate = (self._root / relative_path).resolve()
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

    def mapped_legacy_review(self, audit_id: str) -> dict[str, object] | None:
        legacy = self.store.get_legacy(audit_id)
        if legacy is None:
            return None
        return legacy_bridge.map_legacy_review(
            self.admin_by_id[audit_id],
            int(self.queue_by_id[audit_id]["queue_position"]),
            legacy,
        )

    def combined_records(self) -> list[dict[str, object]]:
        return legacy_bridge.combined_records(
            store=self.store,
            manifest_by_id=self.admin_by_id,
            queue_rows=self.queue_rows,
        )

    def summary(self) -> dict[str, object]:
        summary = self.store.summary()
        summary.update(
            legacy_bridge.combined_summary(self.combined_records())
        )
        return summary

    def public_queue(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for row in self.queue_rows:
            audit_id = row["audit_id"]
            admin = self.admin_by_id[audit_id]
            review = self.store.get(audit_id)
            legacy = self.store.get_legacy(audit_id)
            mapped_legacy = self.mapped_legacy_review(audit_id)
            position = int(row["queue_position"])
            items.append(
                {
                    "audit_id": audit_id,
                    "position": position,
                    "batch_number": ((position - 1) // 20) + 1,
                    "batch_position": ((position - 1) % 20) + 1,
                    "sample_id": admin["sample_id"],
                    "audio_available": legacy_server.bool_value(
                        row["audio_available"]
                    ),
                    "video_state": self.actual_video_state(audit_id),
                    "review_state": self.store.state_for(audit_id),
                    "conclusion": review["conclusion"] if review else None,
                    "error_codes": review["error_codes"] if review else "",
                    "legacy_status": (
                        legacy["review_status"] if legacy else None
                    ),
                    "mapped_conclusion": (
                        mapped_legacy["conclusion"]
                        if mapped_legacy else None
                    ),
                    "mapped_error_codes": (
                        mapped_legacy["error_codes"]
                        if mapped_legacy else ""
                    ),
                }
            )
        return items

    def workbench_payload(self) -> dict[str, object]:
        def relative_or_absolute(path: Path) -> str:
            try:
                return path.relative_to(self._root).as_posix()
            except ValueError:
                return str(path)

        return {
            "formal_workbench": True,
            "owner_validation": True,
            "queue_schema_version": (
                self.queue_rows[0]["schema_version"] if self.queue_rows else None
            ),
            "results_schema_version": REVIEW_SCHEMA_VERSION,
            "default_reviewer_id": self.default_reviewer_id,
            "results_relpath": relative_or_absolute(self.store.path),
            "legacy_results_relpath": relative_or_absolute(
                self.store.legacy_path
            ),
            "error_codes": ERROR_CODES,
            "requirement": {
                "formal_quota": len(self.queue_rows),
                "formal_conclusions": ["V", "I"],
                "discard_counts_toward_quota": False,
            },
            "queue_scope": {
                "label_filter": "ground_ball",
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
                    "queue_label_subtree_unchanged_from_dataset_commit",
                    False,
                ),
            },
            "summary": self.summary(),
            "samples": self.public_queue(),
        }

    def public_sample(self, audit_id: str) -> dict[str, object]:
        queue_row = self.queue_by_id[audit_id]
        admin = self.admin_by_id[audit_id]
        video_state = self.actual_video_state(audit_id)
        position = int(queue_row["queue_position"])
        return {
            "audit_id": audit_id,
            "position": position,
            "total": len(self.queue_rows),
            "batch_number": ((position - 1) // 20) + 1,
            "batch_position": ((position - 1) % 20) + 1,
            "sample_id": admin["sample_id"],
            "audio_available": legacy_server.bool_value(
                admin["audio_available"]
            ),
            "video_state": video_state,
            "event_start": legacy_server.float_or_none(admin["event_start"]),
            "event_end": legacy_server.float_or_none(admin["event_end"]),
            "auto_hit_time": legacy_server.float_or_none(
                admin["auto_hit_time"]
            ),
            "auto_hit_source": admin["auto_hit_source"],
            "candidate_interval_valid": legacy_server.bool_value(
                admin["candidate_interval_valid"]
            ),
            "audio_duration_sec": legacy_server.float_or_none(
                admin["audio_duration_sec"]
            ),
            "audio_url": f"/media/{audit_id}/audio",
            "video_url": (
                f"/media/{audit_id}/video"
                if video_state == "ready_local"
                else None
            ),
            "review": self.store.get(audit_id),
            "legacy_review": self.store.get_legacy(audit_id),
            "legacy_mapped_review": self.mapped_legacy_review(audit_id),
        }

    def troubleshooting_sample(self, audit_id: str) -> dict[str, object]:
        row = self.admin_by_id[audit_id]
        return {
            "audit_id": audit_id,
            "uid": row["uid"],
            "sample_id": row["sample_id"],
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
        self,
        audit_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        review = self.store.upsert(audit_id, payload)
        return {"review": review, "summary": self.summary()}

    def remove_review(self, audit_id: str) -> dict[str, object]:
        removed = self.store.remove(audit_id)
        return {"removed": removed, "summary": self.summary()}


class OwnerValidationHandler(legacy_server.AuditWorkbenchHandler):
    server_version = "GroundballOwnerValidation/1.0"
    state: OwnerValidationState

    def log_message(self, format_string: str, *args: object) -> None:
        print(
            f"[groundball-validation] {self.address_string()} "
            f"{format_string % args}"
        )

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/":
                self.send_file(
                    STATIC / "owner_validation.html",
                    allow_range=False,
                )
                return
            if path == "/api/health":
                summary = self.state.summary()
                self.send_json(
                    {
                        "status": "ok",
                        "formal_workbench": True,
                        "owner_validation": True,
                        "total": len(self.state.queue_rows),
                        "visited": summary["visited"],
                        "formal_reviewed": summary["formal_reviewed"],
                        "export_formal_reviewed": summary[
                            "export_formal_reviewed"
                        ],
                    }
                )
                return
            if path == "/api/reviews/export":
                self.send_csv_download(
                    legacy_bridge.export_bytes(
                        self.state.combined_records(),
                        formal_only=True,
                    ),
                    "groundball_validation_formal_with_legacy.csv",
                )
                return
            if path == "/api/reviews/export-all":
                self.send_csv_download(
                    legacy_bridge.export_bytes(
                        self.state.combined_records(),
                        formal_only=False,
                    ),
                    "groundball_validation_all_with_legacy.csv",
                )
                return
            if path == "/api/reviews/export-new":
                self.send_csv_download(
                    self.state.store.export_bytes(formal_only=False),
                    "groundball_validation_new_records_only.csv",
                )
                return
            if path == "/api/reviews/export-legacy":
                self.send_csv_download(
                    self.state.store.legacy_export_bytes(),
                    "contact_audit_reviews_legacy.csv",
                )
                return
            super().do_GET()
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
                self.send_json(
                    self.state.save_review(audit_id, self.read_json()),
                    status=HTTPStatus.OK,
                )
                return
            if path == "/api/video-preparation":
                payload = self.read_json()
                start_audit_id = str(
                    payload.get("start_audit_id", "")
                ).strip()
                if start_audit_id not in self.state.queue_by_id:
                    raise ReviewValidationError(
                        "视频准备起点不在当前队列中"
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


def main() -> None:
    args = parse_args()
    state = OwnerValidationState(
        args.admin_manifest,
        args.queue,
        args.manifest_summary,
        args.results,
        args.legacy_results,
        args.dataset_root,
        args.reviewer_id,
    )
    OwnerValidationHandler.state = state
    server = ThreadingHTTPServer(
        (args.host, args.port),
        OwnerValidationHandler,
    )
    server.daemon_threads = True
    url = f"http://{args.host}:{args.port}/"
    summary = state.summary()
    print("Groundball owner-validation workbench — portable assignment session.")
    print(
        f"Loaded {len(state.queue_rows)} samples; "
        f"{summary['legacy_total']} legacy reviews remain viewable."
    )
    print(f"New reviews save atomically to {state.store.path}")
    print(f"Legacy reviews remain unchanged at {state.store.legacy_path}")
    print(f"Open {url}")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Groundball owner-validation workbench.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
