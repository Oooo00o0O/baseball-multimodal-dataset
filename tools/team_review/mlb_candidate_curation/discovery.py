"""Pure MLB discovery, diversion, and short-highlight matching logic."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from contracts import IDENTITY_VERSION


DISCOVERY_VERSION = "mlb-play-discovery-v1"
PREFILTER_VERSION = "mlb-high-precision-prefilter-v1"
MATCHER_VERSION = "mlb-short-highlight-matcher-v2"

MULTI_EVENT_TITLE_PATTERNS = (
    (
        "counted_hits",
        re.compile(
            r"\b(?:two|three|four|five|six|seven|eight|nine|\d+)"
            r"(?:[- ]hits\b|[- ]hit[- ](?:game|night|performance)\b)"
        ),
    ),
    (
        "counted_homers",
        re.compile(
            r"\b(?:two|three|four|five|six|seven|eight|nine|\d+)"
            r"[- ](?:homer|home run)s?\b"
        ),
    ),
    ("multi_hit", re.compile(r"\bmulti[- ](?:hit|homer)\b")),
    (
        "highlight_package",
        re.compile(
            r"\b(?:player highlights|game highlights|highlights from|"
            r"game recap|condensed game|top plays|best moments)\b"
        ),
    ),
)

TRAJECTORY_ALIASES = {
    "ground_ball": "ground_ball",
    "groundball": "ground_ball",
    "fly_ball": "fly_ball",
    "flyball": "fly_ball",
    "line_drive": "line_drive",
    "linedrive": "line_drive",
    "popup": "pop_fly",
    "pop_up": "pop_fly",
    "pop_fly": "pop_fly",
}


@dataclass(frozen=True)
class AuxiliaryDiversion:
    event_type: str
    classification_source: str
    evidence: str


@dataclass(frozen=True)
class MediaMatch:
    confidence: str
    score: float
    reason_zh: str
    video: dict[str, Any] | None
    conflicting_evidence: tuple[str, ...] = ()
    excluded_media: tuple["MediaExclusion", ...] = ()


@dataclass(frozen=True)
class MediaExclusion:
    reason: str
    matched_pattern: str
    video: dict[str, Any]


def compact_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def compact_slug(value: object) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", compact_text(value))).strip(
        "-"
    )


def official_video_title(video: Mapping[str, Any]) -> str:
    return compact_text(video.get("title") or video.get("headline") or "")


def multi_event_title_pattern(video: Mapping[str, Any]) -> str:
    """Return a high-precision package pattern found in the official title."""

    title = official_video_title(video)
    for name, pattern in MULTI_EVENT_TITLE_PATTERNS:
        if pattern.search(title):
            return name
    return ""


def parse_duration_seconds(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        return float(text)
    except ValueError:
        return 0.0


def in_play_hit_data(play: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(play.get("hitData"), dict):
        return dict(play["hitData"])
    for event in reversed(play.get("playEvents") or []):
        hit_data = event.get("hitData")
        if isinstance(hit_data, dict) and hit_data:
            return dict(hit_data)
    return {}


def terminal_play_event(play: Mapping[str, Any]) -> dict[str, Any]:
    events = [event for event in play.get("playEvents") or [] if isinstance(event, dict)]
    for event in reversed(events):
        details = event.get("details") or {}
        if details.get("isInPlay") is True or event.get("hitData"):
            return dict(event)
    return dict(events[-1]) if events else {}


def source_play_identity(
    game_pk: object,
    play: Mapping[str, Any],
) -> tuple[str, str]:
    """Return a stable identity and the method that produced it."""

    game = str(game_pk or "").strip()
    if not game:
        raise ValueError("game_pk is required")
    terminal = terminal_play_event(play)
    play_id = str(terminal.get("playId") or "").strip()
    if play_id:
        return f"mlb:{game}:play:{play_id}", "game_pk_play_id"
    about = play.get("about") or {}
    at_bat_index = about.get("atBatIndex")
    if at_bat_index is not None and str(at_bat_index).strip() != "":
        return f"mlb:{game}:atbat:{at_bat_index}", "game_pk_at_bat_index"
    description = compact_text((play.get("result") or {}).get("description"))
    digest = hashlib.sha256(description.encode("utf-8")).hexdigest()[:20]
    return f"mlb:{game}:description:{digest}", "game_pk_description_fingerprint"


def predownload_auxiliary_diversion(
    play: Mapping[str, Any],
) -> AuxiliaryDiversion | None:
    """Conservatively identify a completed play that is outside target scope.

    Earlier foul pitches inside an at-bat are deliberately ignored. Only the
    completed result and terminal event can divert the candidate.
    """

    result = play.get("result") or {}
    event = compact_text(result.get("event"))
    event_type = compact_text(result.get("eventType"))
    description = compact_text(result.get("description"))
    terminal = terminal_play_event(play)
    terminal_details = terminal.get("details") or {}
    terminal_description = compact_text(terminal_details.get("description"))
    terminal_event_type = compact_text(terminal_details.get("eventType"))
    terminal_is_in_play = terminal_details.get("isInPlay")

    structured = " | ".join(
        part for part in (event, event_type, terminal_event_type, terminal_description) if part
    )
    if terminal_is_in_play is not True:
        if terminal_description == "foul tip" or terminal_event_type == "foul_tip":
            return AuxiliaryDiversion(
                "foul_tip",
                "mlb_structured",
                f"terminal event={structured}",
            )
        if terminal_description in {"foul", "foul bunt"} or terminal_event_type in {
            "foul",
            "foul_bunt",
        }:
            return AuxiliaryDiversion(
                "foul_ball",
                "mlb_structured",
                f"terminal event={structured}",
            )

    if event_type in {"foul", "foul_tip"} or event in {"foul", "foul tip"}:
        return AuxiliaryDiversion(
            "foul_tip" if "tip" in f"{event} {event_type}" else "foul_ball",
            "mlb_structured",
            f"result event={event or event_type}",
        )

    if event_type in {"sac_bunt", "bunt_groundout", "bunt_pop_out"}:
        return AuxiliaryDiversion(
            "bunt",
            "mlb_structured",
            f"result eventType={event_type}",
        )

    if re.search(r"\b(bunts?|bunted|sacrifice bunt)\b", description):
        return AuxiliaryDiversion(
            "bunt",
            "official_play_description",
            f"play description={result.get('description', '')}",
        )

    if re.search(r"\b(checks? his swing|checked swing)\b", description):
        return AuxiliaryDiversion(
            "checked_swing_contact",
            "official_play_description",
            f"play description={result.get('description', '')}",
        )
    return None


def provisional_trajectory(play: Mapping[str, Any]) -> str:
    hit_data = in_play_hit_data(play)
    raw = compact_slug(hit_data.get("trajectory")).replace("-", "_")
    if raw in TRAJECTORY_ALIASES:
        return TRAJECTORY_ALIASES[raw]

    result = play.get("result") or {}
    text = compact_text(
        " ".join(
            str(value or "")
            for value in (
                result.get("event"),
                result.get("eventType"),
                result.get("description"),
            )
        )
    )
    if re.search(r"\b(line drive|lines? out|lineout)\b", text):
        return "line_drive"
    if re.search(r"\b(pop fly|pops? out|popup|popout)\b", text):
        return "pop_fly"
    if re.search(r"\b(ground ball|grounds? out|groundout|grounded)\b", text):
        return "ground_ball"
    if re.search(r"\b(fly ball|flies? out|flyout|homers?.*fly)\b", text):
        return "fly_ball"
    return ""


def is_target_candidate(play: Mapping[str, Any]) -> bool:
    if predownload_auxiliary_diversion(play):
        return False
    if not provisional_trajectory(play):
        return False
    terminal = terminal_play_event(play)
    terminal_details = terminal.get("details") or {}
    if terminal_details.get("isInPlay") is True:
        return True
    result_type = compact_text((play.get("result") or {}).get("eventType"))
    return result_type in {
        "field_out",
        "force_out",
        "grounded_into_double_play",
        "double_play",
        "field_error",
        "single",
        "double",
        "triple",
        "home_run",
        "sac_fly",
    }


def build_inventory_row(
    game: Mapping[str, Any],
    play: Mapping[str, Any],
) -> dict[str, object]:
    game_pk = str(game.get("gamePk") or "").strip()
    source_play_id, identity_method = source_play_identity(game_pk, play)
    about = play.get("about") or {}
    matchup = play.get("matchup") or {}
    result = play.get("result") or {}
    hit_data = in_play_hit_data(play)
    terminal = terminal_play_event(play)
    away = (
        ((game.get("teams") or {}).get("away") or {}).get("team") or {}
    ).get("name", "")
    home = (
        ((game.get("teams") or {}).get("home") or {}).get("team") or {}
    ).get("name", "")
    return {
        "source_play_id": source_play_id,
        "identity_method": identity_method,
        "identity_version": IDENTITY_VERSION,
        "game_pk": game_pk,
        "play_id": str(terminal.get("playId") or ""),
        "at_bat_index": str(about.get("atBatIndex", "")),
        "play_event_index": str(terminal.get("index", "")),
        "game_date": str(game.get("officialDate") or ""),
        "game_info": f"{away} @ {home}".strip(" @"),
        "inning": str(about.get("inning", "")),
        "half_inning": str(about.get("halfInning", "")),
        "batter": str((matchup.get("batter") or {}).get("fullName") or ""),
        "pitcher": str((matchup.get("pitcher") or {}).get("fullName") or ""),
        "mlb_event_raw": str(result.get("event") or result.get("eventType") or ""),
        "play_description": str(result.get("description") or ""),
        "mlb_trajectory_raw": str(hit_data.get("trajectory") or ""),
        "mlb_location_raw": str(hit_data.get("location") or ""),
        "media_status": "match_pending",
        "matcher_version": MATCHER_VERSION,
    }


def build_auxiliary_row(
    game: Mapping[str, Any],
    play: Mapping[str, Any],
    diversion: AuxiliaryDiversion,
) -> dict[str, object]:
    game_pk = str(game.get("gamePk") or "").strip()
    source_play_id, _ = source_play_identity(game_pk, play)
    about = play.get("about") or {}
    matchup = play.get("matchup") or {}
    result = play.get("result") or {}
    away = (
        ((game.get("teams") or {}).get("away") or {}).get("team") or {}
    ).get("name", "")
    home = (
        ((game.get("teams") or {}).get("home") or {}).get("team") or {}
    ).get("name", "")
    return {
        "source_play_id": source_play_id,
        "game_pk": game_pk,
        "play_id": terminal_play_event(play).get("playId", ""),
        "game_date": str(game.get("officialDate") or ""),
        "game_info": f"{away} @ {home}".strip(" @"),
        "inning": str(about.get("inning", "")),
        "half_inning": str(about.get("halfInning", "")),
        "batter": str((matchup.get("batter") or {}).get("fullName") or ""),
        "auxiliary_event_type": diversion.event_type,
        "classification_source": diversion.classification_source,
        "classification_evidence": diversion.evidence,
        "mlb_event_raw": str(result.get("event") or result.get("eventType") or ""),
        "play_description": str(result.get("description") or ""),
        "prefilter_version": PREFILTER_VERSION,
    }


def build_media_exclusion_row(
    inventory_row: Mapping[str, object],
    exclusion: MediaExclusion,
) -> dict[str, object]:
    video = exclusion.video
    video_id = str(video.get("id") or video.get("slug") or "")
    return {
        "source_play_id": inventory_row.get("source_play_id", ""),
        "source_video_id": video_id,
        "game_pk": inventory_row.get("game_pk", ""),
        "game_date": inventory_row.get("game_date", ""),
        "batter": inventory_row.get("batter", ""),
        "source_title": str(video.get("title") or video.get("headline") or ""),
        "source_description": str(
            video.get("description") or video.get("blurb") or ""
        ),
        "source_page_url": (
            f"https://www.mlb.com/video/{video_id}" if video_id else ""
        ),
        "source_mp4_url": playback_mp4_url(video),
        "media_duration_sec": parse_duration_seconds(video.get("duration")),
        "exclusion_reason": exclusion.reason,
        "matched_pattern": exclusion.matched_pattern,
        "matcher_version": MATCHER_VERSION,
    }


def extract_videos(content: Mapping[str, Any]) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "video" and value.get("playbacks"):
                video_id = str(value.get("id") or value.get("slug") or "")
                if video_id and video_id not in seen:
                    seen.add(video_id)
                    videos.append(dict(value))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(content)
    return videos


def playback_mp4_url(video: Mapping[str, Any]) -> str:
    playbacks = video.get("playbacks") or []
    for name in ("mp4Avc", "highBit", "highBitAvc"):
        for playback in playbacks:
            url = str(playback.get("url") or "")
            if playback.get("name") == name and ".mp4" in url:
                return url
    for playback in playbacks:
        url = str(playback.get("url") or "")
        if ".mp4" in url:
            return url
    return ""


def video_keywords(video: Mapping[str, Any]) -> set[str]:
    values: list[str] = []
    for item in video.get("keywordsAll") or []:
        if isinstance(item, dict):
            values.extend(
                str(item.get(key) or "") for key in ("displayName", "value", "name")
            )
        else:
            values.append(str(item))
    return {compact_text(value) for value in values if compact_text(value)}


def video_text(video: Mapping[str, Any]) -> str:
    parts = [
        video.get("id"),
        video.get("slug"),
        video.get("title"),
        video.get("headline"),
        video.get("description"),
        video.get("blurb"),
        " ".join(sorted(video_keywords(video))),
    ]
    return compact_text(" ".join(str(part or "") for part in parts))


def play_outcome_category(play: Mapping[str, Any]) -> str:
    result = play.get("result") or {}
    event_type = compact_slug(result.get("eventType")).replace("-", "_")
    event = compact_text(result.get("event"))
    description = compact_text(result.get("description"))
    structured = f"{event_type} {event} {description}"
    if "home_run" in event_type or re.search(r"\b(homers?|home run)\b", structured):
        return "home_run"
    if event_type == "triple" or re.search(r"\btriples?\b", structured):
        return "triple"
    if event_type == "double" or re.search(r"\bdoubles?\b", structured):
        if "double play" not in structured:
            return "double"
    if event_type == "single" or re.search(r"\bsingles?\b", structured):
        return "single"
    if "double_play" in event_type or "double play" in structured:
        return "double_play"
    if "force_out" in event_type or "force out" in structured:
        return "force_out"
    if "field_error" in event_type or "error" in event:
        return "error"
    if "fielders_choice" in event_type or "fielder's choice" in structured:
        return "fielders_choice"
    if "sac_fly" in event_type or "sacrifice fly" in structured:
        return "sac_fly"
    if event_type in {"field_out", "groundout", "flyout", "lineout", "pop_out"}:
        return "out"
    if re.search(r"\b(grounds? out|flies? out|lines? out|pops? out)\b", structured):
        return "out"
    return event_type


def video_outcome_categories(text: str) -> set[str]:
    categories: set[str] = set()
    if re.search(r"\b(strikes? out|strikeout|k's|ks)\b", text):
        categories.add("strikeout")
    if re.search(r"\b(homers?|home run|walk-off homer)\b", text):
        categories.add("home_run")
    if re.search(r"\btriples?\b", text):
        categories.add("triple")
    if re.search(r"\bdoubles?\b", text) and "double play" not in text:
        categories.add("double")
    if re.search(r"\bsingles?\b", text):
        categories.add("single")
    if "double play" in text:
        categories.add("double_play")
    if "force out" in text:
        categories.add("force_out")
    if "fielder's choice" in text:
        categories.add("fielders_choice")
    if re.search(r"\b(sac fly|sacrifice fly)\b", text):
        categories.add("sac_fly")
    if re.search(r"\b(grounds? out|groundout|flies? out|flyout|lines? out|lineout|pops? out|popout)\b", text):
        categories.add("out")
    if re.search(r"\b(reaches?|scores?).*\berror\b", text):
        categories.add("error")
    return categories


def _outcome_compatible(play_outcome: str, video_outcomes: set[str]) -> bool:
    if not video_outcomes or not play_outcome:
        return True
    if play_outcome in video_outcomes:
        return True
    out_family = {"out", "double_play", "force_out", "fielders_choice", "sac_fly"}
    return play_outcome in out_family and bool(video_outcomes & out_family)


def _explicit_video_inning(text: str) -> int | None:
    match = re.search(r"\bin (?:the )?(\d+)(?:st|nd|rd|th)\b", text)
    return int(match.group(1)) if match else None


def _identity_conflicts(play: Mapping[str, Any], video: Mapping[str, Any], text: str) -> list[str]:
    conflicts: list[str] = []
    batter = compact_slug(((play.get("matchup") or {}).get("batter") or {}).get("fullName"))
    pitcher = compact_slug(((play.get("matchup") or {}).get("pitcher") or {}).get("fullName"))
    video_id = compact_slug(f"{video.get('id', '')} {video.get('slug', '')}")
    title = compact_slug(f"{video.get('title', '')} {video.get('headline', '')}")

    generated_play_slug = "-in-play-" in video_id and "-to-" in video_id
    if generated_play_slug:
        if batter and f"-to-{batter}" not in video_id:
            conflicts.append("官方短片 slug 指向另一名击球手")
        if pitcher and not video_id.startswith(f"{pitcher}-"):
            conflicts.append("官方短片 slug 指向另一名投手")
    elif batter and not (
        video_id.startswith(f"{batter}-")
        or title.startswith(f"{batter}-")
        or title == batter
    ):
        conflicts.append("短片标题/slug 没有把目标击球手作为事件主体")

    play_outcome = play_outcome_category(play)
    outcomes = video_outcome_categories(text)
    if not _outcome_compatible(play_outcome, outcomes):
        conflicts.append("短片结果与目标安打/出局结果冲突")

    inning = (play.get("about") or {}).get("inning")
    video_inning = _explicit_video_inning(text)
    if inning not in {None, ""} and video_inning is not None and int(inning) != video_inning:
        conflicts.append("短片局数与目标事件冲突")
    return conflicts


def _trajectory_conflicts(trajectory: str, text: str) -> list[str]:
    conflicts: list[str] = []
    if trajectory == "ground_ball" and re.search(
        r"\b(home run|homers?|fly ball|line drive|pops? out)\b", text
    ):
        if not re.search(r"\bground ball\b", text):
            conflicts.append("视频文字指向空中球")
    if trajectory in {"fly_ball", "line_drive", "pop_fly"} and re.search(
        r"\b(grounds? out|ground ball|groundout)\b", text
    ):
        if not re.search(r"\b(fly ball|line drive|pops? out|home run)\b", text):
            conflicts.append("视频文字指向地滚球")
    return conflicts


def match_video_for_play(
    play: Mapping[str, Any],
    videos: Iterable[Mapping[str, Any]],
    *,
    high_threshold: float = 110.0,
    medium_threshold: float = 65.0,
    long_duration_sec: float = 45.0,
    maximum_duration_sec: float = 90.0,
) -> MediaMatch:
    trajectory = provisional_trajectory(play)
    result = play.get("result") or {}
    description = compact_text(result.get("description"))
    event = compact_text(result.get("event"))
    batter = compact_text(
        ((play.get("matchup") or {}).get("batter") or {}).get("fullName")
    )
    pitcher = compact_text(
        ((play.get("matchup") or {}).get("pitcher") or {}).get("fullName")
    )
    batter_slug = compact_slug(batter)
    pitcher_slug = compact_slug(pitcher)
    description_tokens = {
        token
        for token in compact_slug(description).split("-")
        if len(token) >= 4
        and token
        not in {
            "first",
            "second",
            "third",
            "shortstop",
            "fielder",
            "baseman",
            "sharp",
            "softly",
        }
    }

    best_video: dict[str, Any] | None = None
    best_score = float("-inf")
    best_conflicts: tuple[str, ...] = ()
    best_in_game = False
    best_duration = 0.0
    excluded_media: list[MediaExclusion] = []
    for raw_video in videos:
        video = dict(raw_video)
        duration = parse_duration_seconds(video.get("duration"))
        if duration <= 0:
            continue
        title_pattern = multi_event_title_pattern(video)
        title_text = official_video_title(video)
        title_slug = compact_slug(
            f"{video.get('id', '')} {video.get('slug', '')} {title_text}"
        )
        if title_pattern and (
            (batter and batter in title_text)
            or (batter_slug and batter_slug in title_slug)
        ):
            excluded_media.append(
                MediaExclusion("multi_event_title", title_pattern, video)
            )
            continue
        text = video_text(video)
        text_slug = compact_slug(text)
        keywords = video_keywords(video)
        in_game = "in-game highlight" in keywords
        conflicts = tuple(
            _identity_conflicts(play, video, text)
            + _trajectory_conflicts(trajectory, text)
        )
        score = 0.0
        if batter and batter in text:
            score += 70
        elif batter_slug and batter_slug in text_slug:
            score += 60
        batter_tokens = [token for token in batter_slug.split("-") if len(token) >= 3]
        score += 10 * sum(token in text_slug for token in batter_tokens)
        if pitcher_slug and pitcher_slug in text_slug:
            score += 25
        overlap = sum(token in text_slug.split("-") for token in description_tokens)
        score += min(overlap, 10) * 5
        if event and event in text:
            score += 15
        play_outcome = play_outcome_category(play)
        if play_outcome and play_outcome in video_outcome_categories(text):
            score += 30
        if trajectory == "ground_ball" and "ground" in text:
            score += 18
        elif trajectory == "line_drive" and "line drive" in text:
            score += 18
        elif trajectory == "pop_fly" and re.search(r"\b(pop|popup)\b", text):
            score += 18
        elif trajectory == "fly_ball" and re.search(r"\b(fly|homer|home run)\b", text):
            score += 18
        candidate_inning = (play.get("about") or {}).get("inning")
        if candidate_inning not in {None, ""} and _explicit_video_inning(text) == int(candidate_inning):
            score += 20
        if in_game:
            score += 20
        if "highlight" in keywords:
            score += 5
        if duration > long_duration_sec:
            score -= 35
        score -= 90 * len(conflicts)
        if score > best_score:
            best_score = score
            best_video = video
            best_conflicts = conflicts
            best_in_game = in_game
            best_duration = duration

    if not best_video:
        reason = (
            "匹配到的候选均为多个击球事件合集，已在下载前排除"
            if excluded_media
            else "没有找到可用的官方短片"
        )
        return MediaMatch(
            "low",
            0.0,
            reason,
            None,
            excluded_media=tuple(excluded_media),
        )
    if best_conflicts:
        return MediaMatch(
            "low",
            best_score,
            "候选短片与目标击球手、投手、局数、结果或轨迹存在冲突",
            best_video,
            best_conflicts,
            tuple(excluded_media),
        )
    if best_duration > maximum_duration_sec:
        return MediaMatch(
            "low",
            best_score,
            "候选短片时长异常，保留元数据但暂不下载",
            best_video,
            excluded_media=tuple(excluded_media),
        )
    if best_duration > long_duration_sec and best_score >= medium_threshold:
        return MediaMatch(
            "medium",
            best_score,
            "候选较长，已降低准备优先级；需要人工确认是否只有一次击球",
            best_video,
            excluded_media=tuple(excluded_media),
        )
    if best_score >= high_threshold and best_in_game:
        return MediaMatch(
            "high",
            best_score,
            "比赛、击球主体、结果、描述和官方比赛短片标签一致",
            best_video,
            excluded_media=tuple(excluded_media),
        )
    if best_score >= medium_threshold:
        return MediaMatch(
            "medium",
            best_score,
            "击球主体基本一致，但结果、局数或官方短片证据不完整",
            best_video,
            excluded_media=tuple(excluded_media),
        )
    return MediaMatch(
        "low",
        best_score,
        "候选短片证据不足，暂不下载",
        best_video,
        excluded_media=tuple(excluded_media),
    )

def apply_media_match(
    inventory_row: Mapping[str, object],
    match: MediaMatch,
) -> dict[str, object]:
    result = dict(inventory_row)
    result["media_match_confidence"] = match.confidence
    result["media_match_score"] = match.score
    result["media_match_reason_zh"] = match.reason_zh
    result["matcher_version"] = MATCHER_VERSION
    result["media_status"] = (
        "metadata_only" if match.confidence in {"high", "medium"} else "media_unmatched"
    )
    if match.video:
        video_id = str(match.video.get("id") or match.video.get("slug") or "")
        result["source_video_id"] = video_id
        result["source_title"] = str(
            match.video.get("title") or match.video.get("headline") or ""
        )
        result["source_description"] = str(
            match.video.get("description") or match.video.get("blurb") or ""
        )
        result["source_page_url"] = (
            f"https://www.mlb.com/video/{video_id}" if video_id else ""
        )
        result["source_mp4_url"] = playback_mp4_url(match.video)
        result["media_duration_sec"] = parse_duration_seconds(
            match.video.get("duration")
        )
    return result
