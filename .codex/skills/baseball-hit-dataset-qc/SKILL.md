---
name: baseball-hit-dataset-qc
description: Audit and repair baseball bat-ball contact datasets, especially fly_ball batches on GitHub main. Use for video-confirmed audio timing, source recovery and recuts, Qwen visual confirmation of local audio candidates, batch reports, and publish gates.
---

# Baseball Hit Dataset QC

Use `origin/main` as the authoritative dataset state. Preserve its collector and
sample path exactly. Treat four-digit `Codex_Workstation/F_####` IDs and
three-digit contributor IDs as separate namespaces.

## Full Audit Before Editing

1. Fetch `origin/main` and work from a clean branch or worktree based on it.
2. Inventory every `dataset/fly_ball/<collector>/<sample_id>` directory.
3. Check all five required files: `video.mp4`, `audio.wav`, `label.txt`,
   `sample.csv`, and `source.txt`.
4. Analyze `audio.wav` around the existing `event_start` and `event_end`.
5. Record local transient candidates, the candidate nearest the annotation,
   audio confidence, clip duration, pre-contact context, post-contact context,
   source URL, source path, and `clip_start_time`.
6. Classify each row as a direct-use candidate or needs editing. Separate at
   least: wrong timestamp, missing or masked contact audio, insufficient video
   to verify contact, altered slow-motion contact audio, semantic uncertainty,
   and unreadable media. A trailing catch/play replay is not an error.
7. Write the complete audit CSV and a count summary before changing any sample.

The audit is non-destructive. A direct-use candidate is still subject to a
video spot check; it is not a guaranteed training sample merely because a loud
sound occurs near the annotation.

## Repair Batches

Split rows into batches of at most 250 while retaining the requested audit
order. For the current high-risk fly-ball audit, process IDs from highest to
lowest. Each queue row must include its exact main-relative path and original
metadata.

For each batch:

1. Keep the original sample immutable until a replacement passes all gates.
2. If context is short or contact audio is absent, locate the original source.
3. Convert sample-relative contact time to source time with:
   `source_contact = clip_start_time + sample_contact`.
4. Recut enough source context to make the visible contact and corresponding
   normal-speed hit sound unambiguous. Prefer roughly 1 to 2 seconds before and
   several seconds after when available, but do not impose a fixed trajectory-
   dependent length or require the landing/catch to be present.
5. Run local audio analysis on the repaired clip and produce a finite list of
   timestamped contact candidates.
6. Give Qwen the repaired audio-video clip and the supplied candidate list.
   Qwen may confirm or reject candidates and judge live-play/replay semantics;
   it must not invent an unrestricted final timestamp.
7. Bind the accepted result to one supplied audio candidate. Derive a narrow
   0.05 to 0.15 second event interval in code.
8. Build source-aligned second-pass evidence from the original media: retain a
   lossless audio excerpt around the audio candidate and extract a timestamped
   sequence of original-video frames around it. An optional candidate-centered
   video excerpt may provide context but must not be the sole evidence.
9. Use an independent Qwen review to check the source-aligned evidence. Require
   a visible batting/contact action and evidence consistent with the candidate
   audio. A disagreement with the full-clip pass is a
   `multimodal_conflict_pending`, not an automatic rejection.
10. Reject only when the source-aligned evidence positively establishes a
   non-contact event (for example an outfielder/catch at the exact candidate
   window or an identified commentary/glove sound), or when the selected
   contact itself is slow motion with altered audio. Ignore a trailing replay.
   Do not reject solely because a short video model fails to report contact.
11. Preserve the source URL, source path, source offset, before/after values,
   model response, and decision evidence.

## Hard Rules

- Audio is the authoritative clock. Video confirms that a live bat-ball action
  occurs near the audio candidate.
- Do not accept crowd noise, commentary, glove pops, edits, or altered
  slow-motion audio as contact merely because they are high-energy sounds.
- Do not reject a sample merely because a catch/play replay follows an already
  verified visual-contact plus contact-sound pair.
- Do not require the landing, catch, or full ball flight when contact video and
  its corresponding sound are unambiguous.
- Do not publish a first-pass Qwen acceptance without independent,
  source-aligned evidence review.
- A short-clip model rejection is never a hard invalidation when a full-clip
  model has aligned a local audio candidate with visible contact. Mark the row
  as `multimodal_conflict_pending` and resolve it with original frames and
  original audio.
- Do not accept placeholder or generic model evidence. Evidence must describe
  the visible batter/pitch/swing/contact and the specific candidate sound.
- Do not let the contact-timing model automatically change trajectory metadata;
  route proposed fly, line-drive, or pop-fly changes to a separate review.
- Do not replace unresolved data with an empty directory or placeholder.
- Do not silently drop a sample. Keep it unchanged and mark it unresolved until
  source recovery and review are complete.
- Do not publish a replacement whose context is too short to verify the
  visual-contact and sound pair.
- Do not publish work created from a legacy branch or remapped sample number.
- Never expose API keys in tracked files, logs, reports, prompts, or commits.

## Batch Publish Gate

Before publishing a batch:

1. Verify schema and all required files.
2. Verify audio and video are readable and synchronized.
3. Verify the final event interval is bound to a local audio candidate.
4. Verify the full-clip Qwen pass and source-aligned evidence review place live
   visual contact near that candidate. Resolve every model disagreement before
   publishing; the second reviewer should use a different model where quota
   permits.
5. Record fly-ball semantics separately. Trailing replay is allowed; reject
   only an unverified contact pair or altered slow-motion contact audio.
6. Reconcile every queue row to exactly one outcome: replaced, metadata-only
   correction, unchanged unresolved, or confirmed unusable with evidence.
7. Generate a detailed CSV and Markdown report listing every changed sample,
   before/after timestamps, recut lengths, source offsets, error categories,
   unresolved items, and validation results.
8. Fetch `origin/main`, integrate any new remote commits without force pushing,
   and publish the verified batch directly to `main`.
9. Notify the user that the batch is available for inspection, then immediately
   start the next batch.

See [workflow.md](references/workflow.md) for required report fields and stop
conditions.
