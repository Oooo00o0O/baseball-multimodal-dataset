# 棒球团队审核与候选采集工具（Windows）

本目录包含两类用途不同的工具：

- `start_review.bat`：审核仓库里已有的 Groundball / Flyball 样本；
- `mlb_candidate_curation/start_mlb_candidate_curation.bat`：按分配日期段从
  MLB 官方事件发现、下载并人工筛选新的候选样本。

第三套 MLB 工具的完整说明见
[`mlb_candidate_curation/README.md`](./mlb_candidate_curation/README.md)。

## 已有 Groundball / Flyball 样本审核

这套工具读取一份简单的 TXT 任务清单：每行一个 `sample_id`。`G_...`
自动进入 Groundball 人工验证台，`F_...` 自动进入 Flyball 人工校准台；两套
表单和结果 CSV 保持独立。

## 准备

1. Windows 10 或 11。
2. 安装 Python 3.10 或更高版本。推荐从
   <https://www.python.org/downloads/windows/> 安装并勾选 `Add Python to PATH`。
3. 数据通常位于本仓库的 `dataset/`。如果数据在其他位置，启动时传入
   `-DatasetRoot`。
4. 准备 UTF-8 TXT，例如：

   ```text
   G_0007
   G_0198
   F_0042
   F_0316
   ```

空行和以 `#` 开头的注释会被忽略。重复、格式错误、找不到或不唯一的编号会在
启动前一次性报告；工具不会静默选择错误样本。

## 最简单的启动方式

双击：

```text
tools\team_review\start_review.bat
```

随后选择任务 TXT，并输入审核人代号。工具默认寻找仓库中的 `dataset/`，然后：

- 有 Groundball 时打开 `http://127.0.0.1:8765/`；
- 有 Flyball 时打开 `http://127.0.0.1:8766/`；
- 混合任务会同时打开两套工作台；
- TXT 中每种类型的原始顺序会保留。

也可以从 PowerShell 明确指定参数：

```powershell
.\tools\team_review\start_review.ps1 `
  -AssignmentPath .\my_assignment.txt `
  -ReviewerId member01 `
  -DatasetRoot .\dataset
```

如果 Python 不在 PATH，可先设置：

```powershell
$env:TEAM_REVIEW_PYTHON = "C:\Path\To\python.exe"
```

## 结果与恢复

结果保存在：

```text
tools/team_review/review_outputs/<审核人>/<任务名-任务哈希>/
```

其中可能包括：

- `groundball_reviews.csv`；
- `flyball_reviews.csv`；
- `assignment.txt`；
- `session.json`；
- `review_summary.json`；
- `review_result_bundle.zip`。

同一个审核人用同一份 TXT 再次启动会回到同一目录，并从未审核样本继续。按
`Ctrl+C` 停止启动窗口时，工具会更新 `review_result_bundle.zip`；把这个 ZIP
交还给任务分配者即可。结果目录已被 Git 忽略，不会被正常提交。

## 数据安全

- 服务只监听 `127.0.0.1`，不对局域网或互联网开放。
- 工具只读 `video.mp4`、`audio.wav`、`sample.csv`、`label.txt` 和
  `source.txt`，不会修改数据集。
- 便携版不在线下载或补视频；缺失媒体会明确显示。
- 输出仅写入 `review_outputs/` 或你显式指定的输出目录。
- Groundball 与 Flyball 结果 schema 不会合并。

## 只检查任务而不打开浏览器

```powershell
.\tools\team_review\start_review.ps1 `
  -AssignmentPath .\my_assignment.txt `
  -ReviewerId member01 `
  -DatasetRoot .\dataset `
  -PrepareOnly
```

这会验证任务、解析样本并生成会话清单，但不会启动服务器。

## 新 MLB 候选采集与审核

双击：

```text
tools\team_review\mlb_candidate_curation\start_mlb_candidate_curation.bat
```

首次运行填写负责人分配的开始/结束日期和批次代号。程序会自动建立候选清单、
排除明确的多击球合集、准备首批视频并打开 8767 审核台。所有视频、缓存、个人
审核结果和运行环境都保留在本地，不会进入 Git。

成员完成后从页面右上角下载“团队结果包 ZIP”。汇总负责人双击同目录下的
`merge_team_results.bat`，一次选择全部 ZIP；冲突和同视频多 play 会进入独立
报告，不会互相覆盖。
