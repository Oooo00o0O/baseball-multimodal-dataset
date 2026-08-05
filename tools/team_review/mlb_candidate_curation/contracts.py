"""Stable schemas and vocabulary for MLB candidate curation."""

from __future__ import annotations


INVENTORY_SCHEMA_VERSION = "mlb-candidate-inventory-v1"
AUXILIARY_SCHEMA_VERSION = "mlb-prefiltered-auxiliary-v1"
MEDIA_EXCLUSION_SCHEMA_VERSION = "mlb-prefiltered-media-exclusion-v1"
REVIEW_SCHEMA_VERSION = "mlb-candidate-review-v1"

IDENTITY_VERSION = "mlb-source-play-v1"

OBSERVED_TRAJECTORIES = {
    "ground_ball",
    "fly_ball",
    "line_drive",
    "pop_fly",
    "unknown",
}

DERIVED_LABEL_BY_TRAJECTORY = {
    "ground_ball": "ground_ball",
    "fly_ball": "fly_ball",
    "line_drive": "fly_ball",
    "pop_fly": "fly_ball",
    "unknown": "",
}

MLB_LOCATIONS = {str(value) for value in range(1, 10)}
REVIEWED_LOCATIONS = MLB_LOCATIONS | {"unknown"}

LOCATION_SOURCES = {
    "accepted_official",
    "human_corrected",
    "human_filled",
    "unknown",
}

ADMISSION_STATUSES = {"admitted", "excluded"}
EXCLUSION_REASONS = {
    "no_contact",
    "audio_video_mismatch",
    "trajectory_not_visible",
    "replay_or_slow_motion",
    "duplicate_play",
    "multiple_distinct_plays",
    "broken_media",
    "wrong_play",
    "foul_ball",
    "bunt_or_check_swing",
    "other",
}

MEDIA_MATCH_CONFIDENCES = {"", "high", "medium", "low"}
MEDIA_STATUSES = {
    "metadata_only",
    "match_pending",
    "media_unmatched",
    "queued_for_preparation",
    "prepared",
    "preparation_failed",
}

AUXILIARY_EVENT_TYPES = {
    "foul_ball",
    "foul_tip",
    "bunt",
    "checked_swing_contact",
    "other_non_target",
}

AUXILIARY_CLASSIFICATION_SOURCES = {
    "mlb_structured",
    "official_play_description",
}

MEDIA_EXCLUSION_REASONS = {
    "multi_event_title",
}

INVENTORY_FIELDS = [
    "inventory_schema_version",
    "source_play_id",
    "identity_method",
    "identity_version",
    "game_pk",
    "play_id",
    "at_bat_index",
    "play_event_index",
    "game_date",
    "game_info",
    "inning",
    "half_inning",
    "batter",
    "pitcher",
    "mlb_event_raw",
    "play_description",
    "mlb_trajectory_raw",
    "mlb_location_raw",
    "source_video_id",
    "source_title",
    "source_description",
    "source_page_url",
    "source_mp4_url",
    "media_match_confidence",
    "media_match_score",
    "media_match_reason_zh",
    "matcher_version",
    "media_status",
    "video_relpath",
    "audio_relpath",
    "media_duration_sec",
    "auto_hit_time_1",
    "auto_hit_score_1",
    "auto_hit_time_2",
    "auto_hit_score_2",
    "auto_hit_time_3",
    "auto_hit_score_3",
    "detector_version",
    "detector_config",
    "discovered_at_utc",
    "updated_at_utc",
]

INVENTORY_IMMUTABLE_FIELDS = {
    "source_play_id",
    "identity_method",
    "identity_version",
    "game_pk",
    "play_id",
    "at_bat_index",
    "play_event_index",
    "game_date",
    "mlb_event_raw",
    "play_description",
    "mlb_trajectory_raw",
    "mlb_location_raw",
}

AUXILIARY_FIELDS = [
    "auxiliary_schema_version",
    "source_play_id",
    "game_pk",
    "play_id",
    "game_date",
    "game_info",
    "inning",
    "half_inning",
    "batter",
    "auxiliary_event_type",
    "classification_source",
    "classification_evidence",
    "mlb_event_raw",
    "play_description",
    "source_title",
    "source_page_url",
    "prefilter_version",
    "recorded_at_utc",
]

MEDIA_EXCLUSION_FIELDS = [
    "media_exclusion_schema_version",
    "source_play_id",
    "source_video_id",
    "game_pk",
    "game_date",
    "batter",
    "source_title",
    "source_description",
    "source_page_url",
    "source_mp4_url",
    "media_duration_sec",
    "exclusion_reason",
    "matched_pattern",
    "matcher_version",
    "recorded_at_utc",
]

REVIEW_FIELDS = [
    "review_schema_version",
    "inventory_schema_version",
    "batch_id",
    "source_play_id",
    "admission_status",
    "exclusion_reason",
    "observed_trajectory",
    "derived_ground_fly_label",
    "mlb_location_raw",
    "reviewed_location",
    "location_source",
    "proposed_hit_time",
    "reviewed_hit_time",
    "hit_time_source",
    "contact_eligible",
    "ground_fly_eligible",
    "location_eligible",
    "broken_bat",
    "reviewer_id",
    "notes",
    "reviewed_at_utc",
]
