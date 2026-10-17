# R3.5 — Simple, Reliable Live Interview — Final Report

Branch `r3.5-simple-reliable` · commits `4dd8467` → `a64456b` → `1e89b30` → `ffc9b93`

---

## 1. Part 0 — Diagnosis of the captured sessions

Evidence source: `debug/sessions/` (5 sessions; `a91c6e92-…-704d2538d6c2` is the only one with real turns), analyzed offline by `scripts/analyze_captured_audio.py` and rendered with all replays into **`review/stt_review.html`** (+ `review/stt_review_summary.json`, `review/timeline_analysis.json`).

| Finding | Evidence |
|---|---|
| **Zero audio was ever captured** | All 5 sessions have empty `audio/` folders — `save_audio_segment` existed in `trace.py` but was never wired into the STT path. **Fixed in R3.5**: `run_stt` persists every VAD window (verified: `debug/sessions/provider_drive_probe/audio/` populated by `scripts/drive_provider_stt.py`). |
| **Accuracy lane was 1.7–23 s late** | 7 lane-2 finals: **median 8 716 ms, max 23 015 ms** — the live loop was fed by the *slow* Whisper lane, so captions and turn decisions lagged speech by whole sentences. |
| **Garbled text in finals** | 2/7 finals flagged (word repeated ×2: "Yahi Yahi…", "Yeah, yeah"); 1 Devanagari lane-1 interim (`इन द ब्रांच`) from a broken streaming transcode. |
| **Answers chopped across turns** | 2 of 5 commits received >1 final (split seconds apart); 1 turn got a 6.8 s LLM `failure_safety` fallback injected **off-context** as a follow-up. |
| **en-US vs en-IN** | Identical transcript on the 4.92 s demo clip; en-IN marginally faster end-to-end (12.8 s vs 14.0 s incl. realtime feed). Both verified working in `transcribe_with_provider_async(locale=…)`. |
| **Cross-provider replay agreement** | Apple / Parakeet / Whisper transcripts on the demo clip: 100% word overlap between all three (review HTML, "demo sample" row). |

## 2. What shipped

### Provider layer (`stt_provider.py` + `voice_pipeline.ProviderSTTService`)
- `STT_PROVIDER=auto` chain: **`apple_speechanalyzer`** (Apple SpeechAnalyzer on-device dictation, Swift helper `native/apple_stt/`) → `apple_sfspeech` → `local_two_lane`. Deepgram wired only behind key+flag.
- One provider produces live words **and** finals — *no second transcription pass ever runs*.
- Single warm helper session for the process lifetime (0.5–0.8 s boot,kept warm across segments; rebuilds were proven to lose utterance heads).
- Spontaneous Apple finals **append only when they add content** (a wholesale clear used to roll live captions back).
- `flush_and_wait` returns the stitched cumulative partial text in **0 ms** at commit — the ≤ 1 s budget is met with no rebuild and no second pass.
- Echo gate: helper receives **nothing** while the bot speaks.
- Audio capture wired per VAD window → Part 0 review tooling keeps working for future sessions.

### Simple interviewer (`simple_session.py`, `INTERVIEW_MODE=simple` default)
- Strict `ASKING → LISTENING → COMMITTED` state machine, zero LLM in the live loop (enforced by tests that patch every LLM entry point to raise).
- Script: welcome agenda + intro hook (one utterance) → per skill: anchor → escalation; **"no experience" swaps to `anchor_alt` verbatim and consumes the skill's second slot**; candidate can request a repeat anytime. Bridges ≤ 3 words ("Got it.", "Thanks."), skill transitions ≤ 12 words ("Alright. Now let's talk about {Skill}." = 7 words measured).
- Commit: **"I'm done answering"** button → `POST /api/interview-sessions/{id}/commit-turn`; spoken **"that's my answer / I'm done"** (phrase stripped from the answer); **`AUTO_COMMIT_SILENCE=2.5 s`** after speech stops with the "finishing…" ring 1 s earlier. Empty answers get one prompt, then the flow moves on gracefully.
- Under 90 s remaining, remaining skills are shed (time-skip) → candidate Q&A + closing.
- Answers persist with provider name, speech duration, and commit reason; post-loop judge still runs (LLM allowed after the interview).

### UI (`LiveInterviewRoom.jsx` + `PreFlightCheckModal.jsx`)
- Two panes: AI state orb (~140 px) + state pill (Speaking / Listening / **"AI is speaking, please wait"** / "Finishing your answer…" with spinner / Finished) + current question only | candidate camera + live words caption. "Topic N of M — mm:ss left" top bar. Controls: Mute · **I'm done answering** · Repeat question · End interview. Collapsed transcript drawer.
- Removed: question card, dual-lane labels, phase banners, CC toggle, full robot avatar, interrupt affordances.
- Pre-flight: provider readiness gate (`GET /api/stt/status` blocks Enter) + **speech check** — read one sentence, ≥ 80 % word match via `POST /api/stt/preflight-check`, retakes capped, provider name shown with the transcript.

## 3. Measured numbers (this branch)

| Metric | Value |
|---|---|
| Apple helper warm boot | 0.5–0.8 s (once; stays hot for the process lifetime) |
| First live caption after speech starts | **1 019 ms** (Apple's 1 s volatile batch cadence) |
| Caption delay after that | updates every ~1 s batch; word-level progress visible continuously |
| `flush_and_wait` at commit | **0 ms** (stitched text of record; no rebuild) |
| Rule decision (bridge/next question) | ~0 ms (no LLM) |
| TTS first audio after commit (warm Kokoro) | 155 ms (bridge) – **409–855 ms** (bridge + full next question) |
| Commit → audible next question, end-to-end | **≈ 0.4–0.9 s** (≈0 s if pre-warmed: the next-step texts are pre-synthesized while the candidate answers) |
| `run_stt` window finalization overhead | 4.5–5.9 ms |
| Total scripted flow latency budget | commit + rules + TTS ≈ **≤ 1 s** ✓ |
| Verify suite | **46/46 offline + 3 real-provider = 49 PASS** (`scripts/verify_r3_5.py [--stt]`) |
| Apple dictation quality on the 4.92 s clip | 7/7 keywords, exact: "Testing the Apple Speech transcriber, this is a live streaming check with real speech" |
| Smart turn / VAD load | 0.31 s / 0.06 s |

## 4. Effective configuration (`\.env`, committed keys are defaults)

```
STT_PROVIDER=auto          # -> apple_speechanalyzer (status=installed, ready)
STT_LOCALE=en-US           # en-IN also verified
INTERVIEW_MODE=simple      # adaptive retained behind the flag
AUTO_COMMIT_SILENCE=2.5
ALLOW_BARGE_IN=false
QUESTIONS_PER_SKILL=2
RESUME_PROBES=false
STT_CONTEXT_TERMS=         # optional job-vocabulary boost
DEBUG_AUDIO_CAPTURE=1      # Part 0 capture now wired
```
Build the helper once per machine: `bash scripts/build_apple_stt.sh` (release binary at `native/apple_stt/.build/release/apple_stt`).

## 5. How to test manually

1. `bash scripts/build_apple_stt.sh` (if the binary is missing), then `uvicorn backend.app.main:app …` + `cd frontend && npm run dev`.
2. Candidate login → start an interview session → pre-flight modal: mic checks → **Speech check** (shows "Apple Speech (on-device)"; reads a sentence; ≥ 80 % unlocks Enter; engine not ready blocks Enter with a retry notice).
3. Live room: greeting + intro play back-to-back → answer freely (words appear live) → let 2.5 s pass OR press **I'm done answering** OR say **"…that's my answer"** → bridge + next question within ~1 s. While the bot speaks, talking shows the rose "AI is speaking, please wait" pill and never cuts the question.
4. Say "no experience" on a skill → that skill's alternate anchor is asked verbatim and the escalation is skipped. Say a 2-word answer → "Could you say a bit more?" (once). Ask to repeat → verbatim repeat.
5. Watch the transcript drawer, "Topic N of M — mm:ss" counting down, and the finishing ring on auto-commit.
6. Offline review of any session: `PYTHONPATH=. ./.venv/bin/python scripts/build_stt_review.py` → `review/stt_review.html`.

## 6. Remaining / future work
- `verify_r3_5.py --stt` (3 real-helper checks) is machine-dependent (needs the built binary + macOS ≥ 14) — kept out of the default run.
- Deepgram branch of the provider chain is implemented but intentionally untested (no API key policy in this repo).
- Future live sessions will now populate `debug/sessions/*/audio/`, making the review HTML fully side-by-side (live vs Apple vs Parakeet vs Whisper) with real captures.
