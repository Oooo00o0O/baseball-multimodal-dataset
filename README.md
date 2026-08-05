# Baseball Multimodal Dataset

A multimodal baseball dataset with audio-visual event segmentation and structured annotation.

This repository stores a multimodal baseball event dataset for machine learning research on hit-type classification.

## GitHub 分支使用说明

所有组员在开始提交数据前，请先阅读：

- [GitHub 个人分支使用指南（VS Code）](./GITHUB_BRANCH_GUIDE.md)

请勿直接向 `main` 分支提交个人工作内容。

The dataset focuses on:

- Audio: bat-ball contact sounds
- Video: MLB Film Room clips or similar source clips
- Temporal event segmentation
- Structured labels for supervised learning

The initial target classes are:

- Ground Ball
- Fly Ball

## Repository Structure

```text
baseball-multimodal-dataset/
|-- dataset/
|   |-- ground_ball/
|   |   |-- README.md
|   |   |-- Zihan_Chai/
|   |   |   `-- G_001/
|   |   |       |-- video.mp4
|   |   |       |-- audio.wav
|   |   |       |-- label.txt
|   |   |       |-- sample.csv
|   |   |       `-- source.txt
|   |   `-- <collector_name>/
|   `-- fly_ball/
|       |-- README.md
|       |-- Zihan_Chai/
|       |   `-- F_001/
|       |       |-- video.mp4
|       |       |-- audio.wav
|       |       |-- label.txt
|       |       |-- sample.csv
|       |       `-- source.txt
|       `-- <collector_name>/
|-- docs/
|   |-- annotation_guideline.md
|   `-- dataset_schema.md
`-- README.md
```

The first level under `dataset/` is the event label. The next level is the collector folder, such as `Zihan_Chai` or a future collector like `Zhangsan`.

GitHub may compact single-child folders in the file browser. The actual structure is still:

```text
dataset/<label>/<collector>/<sample_id>/
```

## Sample Definition

Each sample is a temporal event segment, not a single timestamp. A segment should include:

- Pre-contact: pitch and bat preparation
- Contact moment: bat-ball collision
- Post-contact: early ball movement

Typical event durations:

- Ground Ball: about 4-6 seconds
- Fly Ball: about 5-7 seconds

## Naming Rules

- Ground Ball samples: `G_001`, `G_002`, ...
- Fly Ball samples: `F_001`, `F_002`, ...
- Collector identity is encoded in the folder path, for example `dataset/ground_ball/Zihan_Chai/G_001/`.

## Dataset Principles

- No redundant metadata in CSV files
- Event-based temporal segmentation using `event_start` and `event_end`
- Traceability through `source.txt`
- Suitable for audio feature extraction, supervised learning, and future audio-video fusion research

See [docs/annotation_guideline.md](docs/annotation_guideline.md) and [docs/dataset_schema.md](docs/dataset_schema.md) for detailed rules.

## Windows team tools

Portable local review and new-candidate collection tools are documented in
[`tools/team_review/README.md`](./tools/team_review/README.md). The MLB candidate
curation tool downloads runtime media locally; generated media and review state
are intentionally excluded from Git.
