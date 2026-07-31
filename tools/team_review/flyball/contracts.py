"""Owner-defined Flyball calibration vocabulary and validation constants."""

from __future__ import annotations


MANIFEST_SCHEMA_VERSION = "flyball-calibration-manifest-v1"
REVIEW_SCHEMA_VERSION = "flyball-calibration-review-v1"

CONCLUSIONS = {
    "V": "有效",
    "I": "无效",
    "U": "不确定",
}
TRI_STATE_VALUES = {"Y", "N", "U"}
TRAJECTORIES = {"fly", "line_drive", "pop_fly", "unknown"}

ERROR_CODES = {
    "E01": {
        "name": "没有明确击球声",
        "description": "听不到球棒击球，或只有解说、观众、手套等声音。",
    },
    "E02": {
        "name": "原击球时间错误",
        "description": "sample.csv 的 event_start/event_end 没有框住真正击球声。",
    },
    "E03": {
        "name": "没有击球画面",
        "description": "候选时间附近看不到击球接触阶段，只有飞行、接球或赛后画面。",
    },
    "E04": {
        "name": "开头过短",
        "description": "视频开始太晚，缺少投球、来球或击球前过程。",
    },
    "E05": {
        "name": "结尾过短",
        "description": "视频结束太早，看不到足够的飞球结果或完整过程。",
    },
    "E06": {
        "name": "回放或慢动作",
        "description": "片段是回放、慢动作，或只有回放中的击球声。",
    },
    "E07": {
        "name": "标签或轨迹错误",
        "description": "不是飞球类，或 fly / line_drive / pop_fly 明显不一致。",
    },
    "E08": {
        "name": "音画不同步",
        "description": "击球声音与可见接触阶段明显错开。",
    },
    "E09": {
        "name": "文件问题",
        "description": "视频或音频打不开、缺失、无声、损坏或严重卡顿。",
    },
    "E10": {
        "name": "多次比赛动作/无法对应",
        "description": "同一片段有多个投球或冲击声，无法确定哪个对应标注。",
    },
    "E11": {
        "name": "其他问题",
        "description": "不属于以上类别；必须在备注中写清楚。",
    },
}
