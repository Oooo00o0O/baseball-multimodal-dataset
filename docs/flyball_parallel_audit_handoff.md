# Flyball Parallel Audit Handoff

## Work Allocation

Use two non-overlapping reverse-order batches from the same `origin/main`
snapshot. Do not edit or publish another worker's batch.

| Worker | Batch | `global_index` range | Ordered-row offset |
|---|---:|---:|---:|
| Current workstation | 001 | 1207 down to 958 | 0 |
| Desktop Codex | 002 | 957 down to 708 | 250 |

If `origin/main` changes before a batch is published, do not silently merge
the data. Fetch it, keep the batch report, and reconcile only the paths in
your assigned batch.

## Required Standard

Accept a sample only when all three statements are true:

1. A batter's live swing/contact is visible near the selected time.
2. A corresponding bat-ball contact sound is audible at normal speed.
3. The final timestamp is one of the locally measured audio candidates.

Do not require the landing, catch, or full ball flight. A replay after a
verified contact is allowed. Reject or re-cut only when the selected contact
itself is slow motion with altered audio, the sound is not bat-ball contact,
or the visual and audio evidence cannot be aligned.

Ignore the `replay` field in Haofei Wang's manual sheet. It was filled with a
different interpretation and is not evidence about the selected contact.

## Desktop Setup

1. Clone the repository and create a clean worktree from `origin/main`.
2. Check out the audit tooling branch supplied by the other worker. This
   branch contains the audit scripts and the latest rules, but no unreviewed
   dataset replacements.
3. Put the Qwen key only in a local ignored `.env` file:

```text
QWEN_API_KEY=your_key_here
```

4. Confirm that `python` and `ffmpeg` are available. Do not commit `.env`,
   preview caches, audio caches, or Qwen usage logs.

## Create the Desktop Queue

Run the following from the repository root. It takes the next 250 samples
after the current workstation's tail batch, preserving the descending global
order.

```powershell
python scripts/prepare_flyball_visual_queue.py `
  --input reports/flyball_full_audit_20260730/audio_prefilter_all.csv `
  --queue reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/visual_queue.csv `
  --empty-recut-manifest reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/recut_manifest.csv `
  --checkpoint 2 `
  --order global-index-desc `
  --offset 250 `
  --max-rows 250
```

Verify that the queue contains 250 rows and that its highest and lowest
`global_index` are 957 and 708. Stop if it does not.

## Phase 1: Local Audio Candidates

This finds candidate transients only. It is not a pass/fail decision.

```powershell
python scripts/apply_contact_audio_gate_to_queue.py `
  --queue reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/visual_queue.csv `
  --model reports/flyball_full_audit_20260730/optimization/audio_gate_v4/audio_gate_model.json `
  --output reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/audio_gate_all250.csv
```

## Phase 2: Video-First Qwen Review

Qwen first identifies a visible live swing and a broad time window without
being told a final timestamp. Run in resumable chunks of 25. Each rerun skips
completed rows in the same JSONL file.

```powershell
python scripts/qwen_propose_live_swing_windows.py `
  --queue reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/visual_queue.csv `
  --output-jsonl reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/qwen_video_first.jsonl `
  --env-file .env `
  --ffmpeg ffmpeg `
  --preview-cache .qwen_preview_cache_2mb `
  --config config/qwen_reclean_models.json `
  --usage-jsonl reports/flyball_full_audit_20260730/qwen_usage_reverse_batch002_video.jsonl `
  --limit 25
```

The script aggregates all local Qwen usage logs. It changes models before a
model reaches 90 percent of its 1,000,000-token quota. Do not bypass this by
deleting usage logs. A row with an empty `model` or empty `result` is a failed
call, not a model decision; rerun it after fixing the local script/error.

## Phase 3: Bind Video to a Local Audio Candidate

Only candidates inside Qwen's visual window and above the calibrated audio
threshold may proceed.

```powershell
python scripts/bind_video_audio_candidates.py `
  --queue reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/visual_queue.csv `
  --qwen-jsonl reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/qwen_video_first.jsonl `
  --audio-gate reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/audio_gate_all250.csv `
  --rule reports/flyball_full_audit_20260730/optimization/end_to_end_pilot_20/multimodal_v1/multimodal_best_rule.json `
  --output reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/bound_candidates.csv
```

Rows marked unresolved, unbound, rejected, or conflict are not allowed to
overwrite their original dataset folders. Add them to `recut_manifest.csv`
with an evidence-based reason and recover/re-cut from their original source.

## Phase 4: Independent Verification

Use a different Qwen model to confirm every bound candidate against the
original video and candidate-centred audio evidence.

```powershell
python scripts/qwen_crosscheck_fullclip_candidate.py `
  --first-pass-summary reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/bound_candidates.csv `
  --output-jsonl reports/flyball_full_audit_20260730/reverse_batches/batch_002_tail250/crosscheck.jsonl `
  --env-file .env `
  --ffmpeg ffmpeg `
  --preview-cache .qwen_preview_cache_2mb `
  --config config/qwen_reclean_models.json `
  --model qwen3.5-omni-flash `
  --usage-jsonl reports/flyball_full_audit_20260730/qwen_usage_reverse_batch002_crosscheck.jsonl
```

A disagreement is `multimodal_conflict_pending`, not an automatic rejection.
Resolve it with original frames and original audio before changing a sample.

## Phase 5: Re-cut, Validate, and Publish

For every replacement:

1. Recover the original source using `source.txt` and `clip_start_time`.
2. Re-cut enough context to show the selected contact, normally 1 to 2 seconds
   before and several seconds after when the source allows.
3. Re-run local audio candidates, video-first Qwen, candidate binding, and
   independent verification on the replacement.
4. Set a tight `event_start` and `event_end` around the accepted audio
   transient, normally 0.05 to 0.15 seconds.
5. Keep before/after timing, source offset, model evidence, and recut reason.

At 250 rows, generate the batch CSV and Markdown report. The report must
reconcile every queue row to exactly one outcome: metadata-only correction,
replacement, unchanged unresolved, or confirmed unusable with evidence.

Only then fetch `origin/main`, verify that the assigned paths have no remote
conflict, and publish the batch directly to `main`. Never publish partial
first-pass results or empty placeholder folders.
