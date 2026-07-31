from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from docx import Document


FIELDNAMES = [
    "annotator",
    "source_file",
    "sample_id",
    "human_conclusion",
    "original_time_correct",
    "human_contact_time",
    "sound",
    "visual",
    "full_process",
    "replay",
    "trajectory",
    "errors",
    "calibration_use",
    "normalization_note",
]


def normalize_id(value: str) -> str:
    match = re.fullmatch(r"(?:F_?)?(\d+)", value.strip(), flags=re.IGNORECASE)
    if not match:
        return value.strip()
    return f"F_{int(match.group(1)):04d}"


def clean(value: str | None) -> str:
    return (value or "").replace("\n", " ").strip()


def docx_rows(path: Path) -> list[dict[str, str]]:
    document = Document(path)
    rows: list[dict[str, str]] = []
    for table in document.tables:
        for row in table.rows:
            cells = [clean(cell.text) for cell in row.cells]
            if len(cells) < 11 or cells[1] == "样本ID" or not re.fullmatch(r"(?:F_?)?\d+", cells[1], flags=re.IGNORECASE):
                continue
            rows.append(
                {
                    "sample_id": cells[1],
                    "human_conclusion": cells[2],
                    "original_time_correct": cells[3],
                    "human_contact_time": cells[4],
                    "sound": cells[5],
                    "visual": cells[6],
                    "full_process": cells[7],
                    "replay": cells[8],
                    "trajectory": cells[9],
                    "errors": cells[10],
                }
            )
    return rows


def csv_rows(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", newline="", encoding=encoding) as handle:
                rows = list(csv.DictReader(handle))
            if rows:
                return [
                    {
                        "sample_id": clean(row.get("样本ID") or row.get("sample_id")),
                        "human_conclusion": clean(row.get("结论") or row.get("conclusion")),
                        "original_time_correct": clean(
                            row.get("原时间 / 正确") or row.get("原时间正确") or row.get("original_time_correct")
                        ),
                        "human_contact_time": clean(row.get("正确击球秒") or row.get("contact_time")),
                        "sound": clean(row.get("声音") or row.get("sound")),
                        "visual": clean(row.get("画面") or row.get("picture")),
                        "full_process": clean(row.get("全过程") or row.get("full_process")),
                        "replay": clean(row.get("回放") or row.get("replay")),
                        "trajectory": clean(row.get("轨迹") or row.get("trajectory") or row.get("recorded_trajectory")),
                        "errors": clean(row.get("错误代码 / 备注") or row.get("error_codes")),
                    }
                    for row in rows
                    if clean(row.get("样本ID") or row.get("sample_id"))
                ]
        except UnicodeDecodeError:
            continue
    raise ValueError(f"cannot decode {path}")


def normalize(row: dict[str, str], annotator: str, source_file: Path) -> dict[str, str]:
    sample_id = normalize_id(row["sample_id"])
    conclusion = row["human_conclusion"]
    note = ""

    # The agreed review rule is that a later or earlier replay does not invalidate
    # a separate live contact. Haofei marked every replay cell Y, so it is excluded.
    replay = "" if annotator == "Haofei Wang" else row["replay"]
    if annotator == "Haofei Wang":
        note = "replay_field_ignored_by_project_rule"

    # Zhengxuan's F_0515 has a real live contact at 3.287 seconds after an earlier
    # replay segment. It is valid under the revised replay rule.
    if annotator == "Zhengxuan Liu" and sample_id == "F_0515":
        conclusion = "V"
        row["original_time_correct"] = "N"
        row["human_contact_time"] = "3.287"
        row["errors"] = "E02"
        note = "normalized_from_U: live_contact_after_separate_replay"

    # The project currently ignores fly/line-drive/pop-fly subtype disagreements.
    # Diqing's F_0758 is therefore a valid contact example rather than an uncertain
    # semantic example.
    if annotator == "Diqing Tang" and sample_id == "F_0758":
        conclusion = "V"
        note = "normalized_from_U: trajectory_subtype_out_of_scope"

    if conclusion in {"V", "I"}:
        calibration_use = "hard"
    else:
        calibration_use = "soft"

    return {
        "annotator": annotator,
        "source_file": str(source_file),
        "sample_id": sample_id,
        "human_conclusion": conclusion,
        "original_time_correct": row["original_time_correct"],
        "human_contact_time": row["human_contact_time"],
        "sound": row["sound"],
        "visual": row["visual"],
        "full_process": row["full_process"],
        "replay": replay,
        "trajectory": row["trajectory"],
        "errors": row["errors"],
        "calibration_use": calibration_use,
        "normalization_note": note,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the frozen fly-ball human calibration table.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--haoran", type=Path, required=True)
    parser.add_argument("--zichen", type=Path, required=True)
    parser.add_argument("--haofei", type=Path, required=True)
    parser.add_argument("--zhengxuan", type=Path, required=True)
    parser.add_argument("--diqing", type=Path, required=True)
    args = parser.parse_args()

    sources = [
        ("Haoran Yan", args.haoran, csv_rows),
        ("Zichen Yang", args.zichen, docx_rows),
        ("Haofei Wang", args.haofei, docx_rows),
        ("Zhengxuan Liu", args.zhengxuan, docx_rows),
        ("Diqing Tang", args.diqing, csv_rows),
    ]
    records = [
        normalize(row, annotator, path)
        for annotator, path, reader in sources
        for row in reader(path)
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(records)

    hard = sum(row["calibration_use"] == "hard" for row in records)
    print(f"records={len(records)} hard={hard} output={args.output}")


if __name__ == "__main__":
    main()
