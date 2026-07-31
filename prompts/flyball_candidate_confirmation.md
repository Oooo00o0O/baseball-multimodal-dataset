You are auditing a baseball fly-ball audio-video dataset.

Inspect the entire supplied clip and listen to its audio. The local program has
already extracted ranked audio transient candidates. Audio is the authoritative
clock. Your role is to decide whether one supplied candidate matches visible
bat-ball contact in the video.

Rules:

1. Select at most one supplied candidate. Never invent or interpolate a time.
2. Inspect about 0.6 seconds before and after each promising candidate.
3. Require a live pitch, swing/contact, and follow-through sequence near the
   selected audio candidate.
4. Reject glove pops, ball bounces, crowd reactions, commentary consonants,
   replay transitions, editing sounds, and camera cuts.
5. A replay of the catch or play after an already verified contact does not
   invalidate the sample. Reject replay/slow motion only when the selected
   contact itself has altered or slowed audio and no normal-speed contact pair
   is available.
6. The clip does not need to show the landing, catch, or complete ball flight.
   Record trajectory uncertainty separately; do not reject an otherwise clear
   visual-contact plus contact-sound pair for incomplete post-contact footage.
7. Copy the selected candidate index and timestamp exactly from the supplied
   list. If none is verified, use null for both.
8. Return the video-frame contact time separately as
   `visual_contact_seconds`. Normally it should be near the selected audio
   candidate. A clip can have a stable audio-video offset of up to 0.5 seconds:
   when this is visibly the same live pitch, swing, and contact, keep the audio
   candidate as the time label and describe the offset in the evidence. Do not
   use this allowance for an unrelated crowd, commentary, glove, replay, or
   editing sound.
9. Do not return a corrected interval. Program code creates the final interval.

Return only strict JSON:

{
  "decision": "accept|review|reject",
  "confidence": 0.0,
  "selected_audio_candidate_index": 1,
  "selected_audio_candidate_seconds": 0.0,
  "visual_contact_seconds": 0.0,
  "selected_candidate_matches_visual_contact": true,
  "contact_audible": true,
  "contact_sound_normal_speed": true,
  "contact_visible": true,
  "live_play": true,
  "replay_or_slow_motion_at_contact": false,
  "trailing_replay_present": false,
  "fly_ball_semantics": true,
  "full_play_visible": true,
  "clip_context_sufficient": true,
  "trajectory_type": "fly|pop_fly|line_drive|other|uncertain",
  "audio_evidence": "brief evidence",
  "visual_evidence": "brief evidence",
  "failure_reason": ""
}
