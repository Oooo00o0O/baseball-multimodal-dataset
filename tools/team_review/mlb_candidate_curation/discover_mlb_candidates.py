"""Discover MLB target candidates without downloading media."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from dedupe import HistoricalDuplicateIndex
from discovery import (
    apply_media_match,
    build_auxiliary_row,
    build_inventory_row,
    build_media_exclusion_row,
    extract_videos,
    is_target_candidate,
    match_video_for_play,
    predownload_auxiliary_diversion,
)
from stores import (
    CandidateInventoryStore,
    PrefilteredAuxiliaryStore,
    PrefilteredMediaExclusionStore,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a metadata-only MLB candidate inventory."
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "review"
        / "mlb_candidate_curation"
        / "candidate_inventory.csv",
    )
    parser.add_argument(
        "--auxiliary",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "review"
        / "mlb_candidate_curation"
        / "prefiltered_auxiliary_events.csv",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=PROJECT_ROOT / "tmp_sources" / "mlb_candidate_curation_cache",
    )
    parser.add_argument(
        "--media-exclusions",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "review"
        / "mlb_candidate_curation"
        / "prefiltered_media_exclusions.csv",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--high-threshold", type=float, default=110.0)
    parser.add_argument("--medium-threshold", type=float, default=65.0)
    parser.add_argument("--long-duration-sec", type=float, default=45.0)
    parser.add_argument("--maximum-duration-sec", type=float, default=90.0)
    parser.add_argument(
        "--legacy-csv",
        action="append",
        type=Path,
        default=[],
        help="Additional historical candidate CSV; may be repeated.",
    )
    parser.add_argument(
        "--legacy-source-root",
        action="append",
        type=Path,
        default=[],
        help="Directory containing historical source.txt files; may be repeated.",
    )
    parser.add_argument(
        "--no-project-history",
        action="store_true",
        help="Do not scan the known project candidate CSV and dataset snapshots.",
    )
    return parser.parse_args()


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from error


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def read_or_fetch_json(url: str, cache_path: Path, sleep_seconds: float) -> dict:
    if cache_path.is_file():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "BaseballCandidateCuration/1.0"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = response.read()
    data = json.loads(payload)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(cache_path)
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    return data


def project_history_paths() -> tuple[list[Path], list[Path]]:
    csv_paths = [
        PROJECT_ROOT / "data" / "labels" / "groundball_zone3_candidate_metadata.csv"
    ]
    source_roots: list[Path] = []
    external_dataset = (
        PROJECT_ROOT / "external" / "baseball-multimodal-dataset" / "dataset"
    )
    if external_dataset.is_dir():
        source_roots.append(external_dataset)
    branch_root = PROJECT_ROOT / "data"
    if branch_root.is_dir():
        source_roots.extend(
            path
            for path in branch_root.glob(
                "branch_datasets_*/baseball-multimodal-dataset/dataset"
            )
            if path.is_dir()
        )
    return [path for path in csv_paths if path.is_file()], source_roots


def discover(args: argparse.Namespace) -> dict[str, int]:
    start = parse_date(args.start_date)
    end = parse_date(args.end_date)
    if end < start:
        raise ValueError("end date must be on or after start date")
    inventory = CandidateInventoryStore(args.inventory)
    auxiliary = PrefilteredAuxiliaryStore(args.auxiliary)
    media_exclusions = PrefilteredMediaExclusionStore(args.media_exclusions)
    legacy_csvs = list(args.legacy_csv)
    legacy_roots = list(args.legacy_source_root)
    if not args.no_project_history:
        default_csvs, default_roots = project_history_paths()
        legacy_csvs.extend(default_csvs)
        legacy_roots.extend(default_roots)
    historical = HistoricalDuplicateIndex.from_paths(legacy_csvs, legacy_roots)
    for row in inventory.all():
        historical.add_row(row)
    for row in auxiliary.all():
        historical.add_row(row)
    counts = {
        "games": 0,
        "plays": 0,
        "target_candidates": 0,
        "prefiltered_auxiliary": 0,
        "prefiltered_media": 0,
        "duplicates": 0,
        "historical_duplicates": 0,
        "high_matches": 0,
        "medium_matches": 0,
        "low_matches": 0,
    }

    for day in daterange(start, end):
        schedule = read_or_fetch_json(
            "https://statsapi.mlb.com/api/v1/schedule"
            f"?sportId=1&startDate={day.isoformat()}&endDate={day.isoformat()}",
            args.cache_dir / f"schedule_{day.isoformat()}.json",
            args.sleep,
        )
        games: list[dict[str, Any]] = []
        for block in schedule.get("dates") or []:
            games.extend(block.get("games") or [])
        for game in games:
            game_pk = str(game.get("gamePk") or "")
            if not game_pk:
                continue
            feed = read_or_fetch_json(
                f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live",
                args.cache_dir / f"game_{game_pk}_feed.json",
                args.sleep,
            )
            content = read_or_fetch_json(
                f"https://statsapi.mlb.com/api/v1/game/{game_pk}/content",
                args.cache_dir / f"game_{game_pk}_content.json",
                args.sleep,
            )
            counts["games"] += 1
            videos = extract_videos(content)
            plays = ((feed.get("liveData") or {}).get("plays") or {}).get(
                "allPlays"
            ) or []
            for play in plays:
                counts["plays"] += 1
                diversion = predownload_auxiliary_diversion(play)
                if diversion:
                    row = build_auxiliary_row(game, play, diversion)
                    source_play_id = str(row["source_play_id"])
                    if inventory.get(source_play_id) or auxiliary.get(source_play_id):
                        counts["duplicates"] += 1
                    elif historical.match(row).duplicate:
                        counts["historical_duplicates"] += 1
                    else:
                        auxiliary.upsert(row)
                        historical.add_row(row)
                        counts["prefiltered_auxiliary"] += 1
                    continue
                if not is_target_candidate(play):
                    continue
                row = build_inventory_row(game, play)
                source_play_id = str(row["source_play_id"])
                if inventory.get(source_play_id) or auxiliary.get(source_play_id):
                    counts["duplicates"] += 1
                    continue
                if historical.match(row).duplicate:
                    counts["historical_duplicates"] += 1
                    continue
                match = match_video_for_play(
                    play,
                    videos,
                    high_threshold=args.high_threshold,
                    medium_threshold=args.medium_threshold,
                    long_duration_sec=args.long_duration_sec,
                    maximum_duration_sec=args.maximum_duration_sec,
                )
                for exclusion in match.excluded_media:
                    excluded_row = build_media_exclusion_row(row, exclusion)
                    source_video_id = str(excluded_row["source_video_id"])
                    if not media_exclusions.get(source_play_id, source_video_id):
                        counts["prefiltered_media"] += 1
                    media_exclusions.upsert(excluded_row)
                if not match.video and match.excluded_media:
                    continue
                matched_row = apply_media_match(row, match)
                if historical.match(matched_row).duplicate:
                    counts["historical_duplicates"] += 1
                    continue
                inventory.upsert(matched_row)
                historical.add_row(matched_row)
                counts["target_candidates"] += 1
                counts[f"{match.confidence}_matches"] += 1
                if args.limit and counts["target_candidates"] >= args.limit:
                    return counts
    return counts


def main() -> None:
    args = parse_args()
    counts = discover(args)
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
