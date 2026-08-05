# MLB 候选采集与审核工具（Windows）

这是与 Groundball、Flyball 审核台并列的第三套独立系统。它从 MLB 官方
比赛事件中寻找可能的 Ground/Fly/Line-drive 单次击球短片，下载到个人电脑，
自动提出最多三个声音候选点，再由人工收录或排除。

系统只保存一个人工确认的击球时间点，不把多个击球点塞进同一个样本。

## 最简单的使用方式

双击：

```text
start_mlb_candidate_curation.bat
```

首次运行会依次：

1. 检查 Windows、Python 3.10+、FFmpeg 和网络依赖；
2. 创建本工具自己的 Python 环境并安装 NumPy；
3. 要求填写批次代号以及负责人分配的开始、结束日期；
4. 从 MLB 官方接口建立候选清单；
5. 自动下载和分析首批约 30 条候选；
6. 打开 `http://127.0.0.1:8767/`。

以后再次双击会读取原批次，补充已消耗的本地队列并继续审核。若电脑缺少
FFmpeg，启动窗口会给出中文安装命令。

负责人应给每个人分配互不重叠的日期范围，例如一个赛季或一个年份。日期只
负责减少重复；真正去重仍使用稳定的 MLB `source_play_id`。

如需命令行参数：

```powershell
.\start_mlb_candidate_curation.ps1 `
  -BatchId member01_2025 `
  -StartDate 2025-03-01 `
  -EndDate 2025-11-15 `
  -BufferTarget 30
```

`-RefreshDiscovery` 会重新扫描同一日期段，但稳定身份会阻止重复写入。
`-PrepareOnly` 只建立清单和补充队列，不打开网页。

## 下载前筛选

系统维护三类互相独立的记录：

- `candidate_inventory.csv`：可能成为 Ground/Fly 样本的候选；
- `prefiltered_auxiliary_events.csv`：界外、擦棒、触击、明显收棒式接触等
  已能从官方 play 数据确认的非目标事件；
- `prefiltered_media_exclusions.csv`：标题明确表示多个击球事件的媒体包。

以下强标题形式会在下载前进入第三份表，例如：

- `four-hit game`、`three hits`；
- `multi-homer game`、`two-homer night`；
- `player highlights`、`game recap`、`condensed game`。

仅仅时长超过 45 秒不会直接删除。标题不明确的长视频会降低准备优先级；
超过安全上限的素材保留元数据但暂不下载。若合集漏到人工界面，可选择
“视频包含多个不同击球事件”。

## 审核逻辑

视频始终静音，原始音频是唯一声音和权威时间轴。增强音频只帮助听辨，不会
替换研究音轨或改变时间。

- 不合格：选择一个明确原因即可，备注和审核人可空；
- 合格：选择可见轨迹、确认 MLB 位置，并保留一个击球点；
- `line_drive` 和 `pop_fly` 在后续二分类中派生为 Fly，但原始人工观察仍保留；
- 返回已审核样本重新保存会更新同一行，不会制造第二个当前结论。

常用快捷键：

- `Space`：播放/暂停；
- `J` / `K`：下一条 / 上一条；
- `A` / `X`：收录 / 排除；
- `G` / `F` / `L` / `P` / `U`：轨迹；
- `1`–`9`：MLB 位置；
- `Q` / `W` / `E`：自动候选点 1/2/3；
- `R`：恢复最初建议点；
- `Ctrl+Enter`：保存并前往下一条未审核样本。

## 页面右上角三个导出

- `审核 CSV`：当前批次的标准人工记录，是本机继续编辑的源记录；
- `合并审计 CSV`：把这些人工记录与 MLB/媒体诊断字段连接，便于查看；
- `团队结果包 ZIP`：交给负责汇总的人，含审核 CSV、已审核条目的来源元数据、
  批次日期和视频 SHA-256 指纹，不包含 MP4/WAV。

团队共享和合并时应使用 ZIP，而不是单独拿“合并审计 CSV”当作写回文件。

## 合并所有成员结果

汇总负责人双击：

```text
merge_team_results.bat
```

一次选择所有成员交回的 ZIP。输出目录包含：

- `merged_reviews.csv`：无冲突、可正式合并的当前结果；
- `merged_reviewed_inventory.csv`：对应 MLB 与媒体来源；
- `conflicts.csv`：同一 play 的人工结论不一致；
- `media_warnings.csv`：同一 MLB 媒体 ID 或文件指纹关联多个 play，疑似合集或
  错误匹配；
- `summary.json`：数量汇总。

一致的重复审核只保留一个样本并合并批次来源；冲突不会被最后写入者覆盖。

## 本地数据与 GitHub 边界

运行数据默认位于：

```text
data/review/mlb_candidate_curation/
```

GitHub 只保存程序、规则、测试和浏览器依赖。以下内容必须保持本地：候选库存、
审核结果、视频、音频、缓存、日志、Python 环境和合并输出。团队成员首次使用时
各自建立日期段清单，因此不会看到虚假的“视频已准备”状态。

工具只监听 `127.0.0.1`，不向局域网或互联网开放审核网页。它不会自动执行
Git pull/push，也没有账号或在线抢占功能。

## 开发验证

```powershell
python -m unittest discover -s .\tests -v
```

正式实现还保留命令行入口：`discover_mlb_candidates.py`、
`prepare_mlb_candidates.py`、`export_training_manifests.py` 和
`merge_team_bundles.py`。
