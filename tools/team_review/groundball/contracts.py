"""Owner-defined Groundball validation vocabulary and validation constants."""

from __future__ import annotations


REVIEW_SCHEMA_VERSION = "groundball-validation-review-v1"

CONCLUSIONS = {
    "V": "有效",
    "I": "无效",
    "D": "舍弃（不计入正式 20 条）",
}

FORMAL_CONCLUSIONS = {"V", "I"}
CHECK_VALUES = {"Y", "N"}

ERROR_CODES = {
    "E01": {
        "name": "没有击球事件",
        "description": (
            "视频中没有球棒打到球；常见情况是只有后续传球、防守处理或赛后画面。"
        ),
    },
    "E02": {
        "name": "原击球时间错误",
        "description": (
            "sample.csv 的 event_start/event_end 没有框住真正击球点，或明显偏早、偏晚。"
        ),
    },
    "E03": {
        "name": "只有击球后的其他过程",
        "description": (
            "候选时间附近没有击球接触阶段，只有球已出去、传球、接球或防守处理。"
        ),
    },
    "E04": {
        "name": "击球前缺失",
        "description": "整个 video.mp4 开始太晚，缺少击球前准备或来球过程。",
    },
    "E05": {
        "name": "击球后缺失",
        "description": "整个 video.mp4 结束太早，看不到球刚被打出去后的一段过程。",
    },
    "E06": {
        "name": "回放或慢动作",
        "description": "片段是回放、慢动作，或只有回放中的击球声。",
    },
    "E07": {
        "name": "视频前后过程不足",
        "description": "能看到击球点，但整个视频对击球前后过程的覆盖太短。",
    },
    "E08": {
        "name": "样本剪错或非目标事件",
        "description": "不是当前样本对应的击球，或视频内容明显不对。",
    },
    "E09": {
        "name": "多个事件混杂",
        "description": "能判断当前标注对应了错误事件；如果完全分不清，应直接舍弃。",
    },
    "E10": {
        "name": "其他明确错误",
        "description": "不属于以上类别；必须在备注中写清楚具体原因。",
    },
}


LEGACY_REVIEW_SCHEMA_VERSION = "contact-audit-review-v1"
LEGACY_STATUSES = {
    "pass",
    "corrected_pass",
    "no_contact",
    "material_issue",
    "uncertain",
}
