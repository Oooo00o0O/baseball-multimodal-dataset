"""Coverage-aware selection for the bounded prepared-media buffer."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping


AIR_TRAJECTORIES = {"fly_ball", "line_drive", "pop_fly"}


@dataclass(frozen=True)
class ScheduleConfig:
    """Tunable preparation targets; changing them never changes saved reviews."""

    buffer_target: int = 30
    per_game_cap: int = 3
    ground_target: int = 15
    air_target: int = 15
    fly_ball_target: int = 5
    line_drive_target: int = 5
    pop_fly_target: int = 5
    per_location_target: int = 2

    def validate(self) -> None:
        values = {
            "buffer_target": self.buffer_target,
            "per_game_cap": self.per_game_cap,
            "ground_target": self.ground_target,
            "air_target": self.air_target,
            "fly_ball_target": self.fly_ball_target,
            "line_drive_target": self.line_drive_target,
            "pop_fly_target": self.pop_fly_target,
            "per_location_target": self.per_location_target,
        }
        for name, value in values.items():
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.buffer_target and not self.per_game_cap:
            raise ValueError("per_game_cap must be positive when the buffer is enabled")


@dataclass(frozen=True)
class ScheduledCandidate:
    source_play_id: str
    priority_score: float
    reason_zh: str


def _text(row: Mapping[str, object], field: str) -> str:
    return str(row.get(field) or "").strip().lower()


def _trajectory_family(trajectory: str) -> str:
    if trajectory == "ground_ball":
        return "ground"
    if trajectory in AIR_TRAJECTORIES:
        return "air"
    return "unknown"


def _provisional_trajectory(raw: str) -> str:
    return {"popup": "pop_fly", "pop_up": "pop_fly"}.get(raw, raw)

def _review_coverage(
    reviews: Iterable[Mapping[str, object]],
) -> tuple[Counter[str], Counter[str], Counter[str]]:
    families: Counter[str] = Counter()
    subtypes: Counter[str] = Counter()
    locations: Counter[str] = Counter()
    for row in reviews:
        if _text(row, "admission_status") != "admitted":
            continue
        trajectory = _text(row, "observed_trajectory")
        family = _trajectory_family(trajectory)
        if family != "unknown":
            families[family] += 1
        if trajectory in AIR_TRAJECTORIES:
            subtypes[trajectory] += 1
        location = _text(row, "reviewed_location")
        if location in {str(value) for value in range(1, 10)}:
            locations[location] += 1
    return families, subtypes, locations


def _deficit(current: int, target: int) -> float:
    if target <= 0 or current >= target:
        return 0.0
    return (target - current) / target


def select_for_preparation(
    inventory_rows: Iterable[Mapping[str, object]],
    review_rows: Iterable[Mapping[str, object]],
    config: ScheduleConfig | None = None,
) -> list[ScheduledCandidate]:
    """Select unreviewed high/medium matches for the current bounded buffer.

    Human-admitted reviews establish the coverage deficits. Each newly selected
    row then provisionally fills its hinted cells so one discovery cluster
    cannot monopolize the whole buffer.
    """

    config = config or ScheduleConfig()
    config.validate()
    inventory = [dict(row) for row in inventory_rows]
    reviews = [dict(row) for row in review_rows]
    reviewed_ids = {
        _text(row, "source_play_id")
        for row in reviews
        if _text(row, "source_play_id")
    }
    occupied = [
        row
        for row in inventory
        if _text(row, "source_play_id") not in reviewed_ids
        and _text(row, "media_status") in {"queued_for_preparation", "prepared"}
    ]
    slots = max(0, config.buffer_target - len(occupied))
    if not slots:
        return []

    game_counts: Counter[str] = Counter(_text(row, "game_pk") for row in occupied)
    family_counts, subtype_counts, location_counts = _review_coverage(reviews)
    for row in occupied:
        trajectory = _provisional_trajectory(_text(row, "mlb_trajectory_raw"))
        family = _trajectory_family(trajectory)
        if family != "unknown":
            family_counts[family] += 1
        if trajectory in AIR_TRAJECTORIES:
            subtype_counts[trajectory] += 1
        location = _text(row, "mlb_location_raw")
        if location in {str(value) for value in range(1, 10)}:
            location_counts[location] += 1

    candidates = [
        row
        for row in inventory
        if _text(row, "source_play_id") not in reviewed_ids
        and _text(row, "media_status")
        in {"metadata_only", "match_pending", "preparation_failed"}
        and _text(row, "media_match_confidence") in {"high", "medium"}
        and _text(row, "source_mp4_url")
    ]
    selected: list[ScheduledCandidate] = []

    while candidates and len(selected) < slots:
        ranked: list[tuple[float, str, dict[str, object], list[str]]] = []
        for row in candidates:
            game_pk = _text(row, "game_pk")
            if game_counts[game_pk] >= config.per_game_cap:
                continue
            confidence = _text(row, "media_match_confidence")
            trajectory = _provisional_trajectory(_text(row, "mlb_trajectory_raw"))
            family = _trajectory_family(trajectory)
            location = _text(row, "mlb_location_raw")
            score = 100.0 if confidence == "high" else 10.0
            reasons = ["高可信媒体匹配" if confidence == "high" else "中可信媒体匹配"]

            family_target = (
                config.ground_target if family == "ground" else config.air_target
            )
            family_gain = (
                _deficit(family_counts[family], family_target)
                if family != "unknown"
                else 0.0
            )
            if family_gain:
                score += 30.0 * family_gain
                reasons.append("补齐滚地/空中覆盖")

            subtype_target = {
                "fly_ball": config.fly_ball_target,
                "line_drive": config.line_drive_target,
                "pop_fly": config.pop_fly_target,
            }.get(trajectory, 0)
            subtype_gain = _deficit(subtype_counts[trajectory], subtype_target)
            if subtype_gain:
                score += 18.0 * subtype_gain
                reasons.append("补齐空中球子类")

            location_gain = (
                _deficit(location_counts[location], config.per_location_target)
                if location in {str(value) for value in range(1, 10)}
                else 0.0
            )
            if location_gain:
                score += 12.0 * location_gain
                reasons.append("补齐 MLB 位置")

            score -= 4.0 * game_counts[game_pk]
            stable_id = _text(row, "source_play_id")
            ranked.append((score, stable_id, row, reasons))

        if not ranked:
            break
        score, stable_id, row, reasons = max(
            ranked,
            key=lambda item: (item[0], item[1]),
        )
        selected.append(
            ScheduledCandidate(
                source_play_id=stable_id,
                priority_score=round(score, 6),
                reason_zh="；".join(dict.fromkeys(reasons)),
            )
        )
        candidates.remove(row)
        game_pk = _text(row, "game_pk")
        game_counts[game_pk] += 1
        trajectory = _provisional_trajectory(_text(row, "mlb_trajectory_raw"))
        family = _trajectory_family(trajectory)
        if family != "unknown":
            family_counts[family] += 1
        if trajectory in AIR_TRAJECTORIES:
            subtype_counts[trajectory] += 1
        location = _text(row, "mlb_location_raw")
        if location in {str(value) for value in range(1, 10)}:
            location_counts[location] += 1
    return selected
