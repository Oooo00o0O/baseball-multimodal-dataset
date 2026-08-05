"""Historical source-play duplicate indexing."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

from discovery import compact_slug, compact_text


MLB_VIDEO_PATTERN = re.compile(
    r"https?://(?:www\.)?mlb\.com/(?:[^/\s]+/)*video/([^/?#\s]+)",
    re.IGNORECASE,
)


def normalize_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        split = urlsplit(text)
    except ValueError:
        return text
    if not split.scheme or not split.netloc:
        return text
    path = re.sub(r"/+", "/", split.path).rstrip("/")
    return urlunsplit((split.scheme.lower(), split.netloc.lower(), path, "", ""))


def mlb_video_slug(value: object) -> str:
    text = str(value or "").strip()
    match = MLB_VIDEO_PATTERN.search(text)
    if match:
        return compact_slug(match.group(1))
    return ""


def normalize_mp4_url(value: object) -> str:
    url = normalize_url(value)
    return url.lower() if ".mp4" in url.lower() else ""


def play_description_fingerprint(row: Mapping[str, object]) -> str:
    game_pk = str(row.get("game_pk") or row.get("gamePk") or "").strip()
    batter = compact_text(row.get("batter"))
    description = compact_text(
        row.get("play_description") or row.get("description")
    )
    if not game_pk or not description:
        return ""
    payload = f"{game_pk}|{batter}|{description}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DuplicateMatch:
    duplicate: bool
    reason: str = ""
    key: str = ""


class HistoricalDuplicateIndex:
    """Index stable IDs and legacy source evidence without date assumptions."""

    def __init__(self) -> None:
        self.source_play_ids: set[str] = set()
        self.video_slugs: set[str] = set()
        self.page_urls: set[str] = set()
        self.mp4_urls: set[str] = set()
        self.description_fingerprints: set[str] = set()

    def add_row(self, row: Mapping[str, object]) -> None:
        source_play_id = str(row.get("source_play_id") or "").strip()
        if source_play_id:
            self.source_play_ids.add(source_play_id)

        for field in ("source_page_url", "source_url", "url"):
            url = normalize_url(row.get(field))
            if url:
                self.page_urls.add(url)
            slug = mlb_video_slug(row.get(field))
            if slug:
                self.video_slugs.add(slug)

        for field in ("source_video_id", "slug"):
            slug = compact_slug(row.get(field))
            if slug:
                self.video_slugs.add(slug)

        for field in ("source_mp4_url", "mp4_url"):
            mp4 = normalize_mp4_url(row.get(field))
            if mp4:
                self.mp4_urls.add(mp4)

        fingerprint = play_description_fingerprint(row)
        if fingerprint:
            self.description_fingerprints.add(fingerprint)

    def add_source_text(self, text: str) -> None:
        for match in MLB_VIDEO_PATTERN.finditer(text):
            slug = compact_slug(match.group(1))
            if slug:
                self.video_slugs.add(slug)
            self.page_urls.add(normalize_url(match.group(0)))
        for token in re.findall(r"https?://[^\s<>'\"]+", text):
            mp4 = normalize_mp4_url(token.rstrip(".,);]"))
            if mp4:
                self.mp4_urls.add(mp4)

    def match(self, row: Mapping[str, object]) -> DuplicateMatch:
        source_play_id = str(row.get("source_play_id") or "").strip()
        if source_play_id and source_play_id in self.source_play_ids:
            return DuplicateMatch(True, "source_play_id", source_play_id)

        for field in ("source_page_url", "source_url", "url"):
            url = normalize_url(row.get(field))
            if url and url in self.page_urls:
                return DuplicateMatch(True, "source_page_url", url)
            slug = mlb_video_slug(row.get(field))
            if slug and slug in self.video_slugs:
                return DuplicateMatch(True, "mlb_video_slug", slug)

        for field in ("source_video_id", "slug"):
            slug = compact_slug(row.get(field))
            if slug and slug in self.video_slugs:
                return DuplicateMatch(True, "mlb_video_slug", slug)

        for field in ("source_mp4_url", "mp4_url"):
            mp4 = normalize_mp4_url(row.get(field))
            if mp4 and mp4 in self.mp4_urls:
                return DuplicateMatch(True, "source_mp4_url", mp4)

        fingerprint = play_description_fingerprint(row)
        if fingerprint and fingerprint in self.description_fingerprints:
            return DuplicateMatch(True, "play_description_fingerprint", fingerprint)
        return DuplicateMatch(False)

    @classmethod
    def from_paths(
        cls,
        csv_paths: Iterable[Path] = (),
        source_roots: Iterable[Path] = (),
    ) -> "HistoricalDuplicateIndex":
        index = cls()
        for csv_path in csv_paths:
            path = Path(csv_path)
            if not path.is_file():
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    index.add_row(row)
        for root in source_roots:
            path = Path(root)
            if path.is_file() and path.name.lower() == "source.txt":
                index.add_source_text(path.read_text(encoding="utf-8", errors="replace"))
                continue
            if not path.is_dir():
                continue
            for source_path in path.rglob("source.txt"):
                index.add_source_text(
                    source_path.read_text(encoding="utf-8", errors="replace")
                )
        return index

    def summary(self) -> dict[str, int]:
        return {
            "source_play_ids": len(self.source_play_ids),
            "video_slugs": len(self.video_slugs),
            "page_urls": len(self.page_urls),
            "mp4_urls": len(self.mp4_urls),
            "description_fingerprints": len(self.description_fingerprints),
        }
