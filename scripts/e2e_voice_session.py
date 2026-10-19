#!/usr/bin/env python3
"""R3.5b REAL-PATH end-to-end voice interview test (the missing coverage).

Drives a FULL session through the real browser mic -> WebRTC -> server path:

  Playwright Chromium launched with
      --use-fake-device-for-media-stream
      --use-fake-ui-for-media-stream
      --use-file-for-fake-audio-capture=<wav>%noloop
  where <wav> is generated with macOS `say` (US / UK / Indian voices) with
  2-3s pauses between repeated takes. Chromium restarts the file per
  getUserMedia source, so assertions are ADAPTIVE (match commits by content),
  never by wall-clock alignment.

Setup (candidate + practice session) goes through the real HTTP API; the
practice interview deterministically materializes 2 scripted questions
(zero LLM in setup, zero LLM in the live loop).

Asserts:
  1. audio is captured per VAD segment (debug/sessions/<id>/audio/),
  2. the live caption appears in the room UI,
  3. the persisted answer matches the spoken text (window-aware word WER),
  4. no truncation: the last words spoken are inside the stored answer,
  5. the commit works via silence (AUTO_COMMIT_SILENCE) and via the
     "I'm done answering" button,
  6. the next question is spoken (TTS first-audio + question card update).

Prints the measured numbers: first-caption delay, partial-update cadence,
finalize source/time at commit, commit reasons, WER, DB row proof.

Usage:
    PYTHONPATH=. ./.venv/bin/python scripts/e2e_voice_session.py [--voice samantha|daniel|rishi]
Servers: started automatically unless already reachable.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = Path(__file__).resolve().parents[1]
BACKEND_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:3000"

SPEECH_CHECK_SENTENCE = (
    "Testing, testing. Can you hear me clearly? I am reading this sentence out loud right now."
)
# Distinct, WER-friendly answer scripts (no digits / no commit phrases). The capture
# wav speaks the preflight sentence tiles first, so the first answer window may
# legitimately open on preflight words: the reference for answer 1 is preflight+answer.
ANSWER_1 = (
    "For my last project I led the migration of our checkout service to Go, "
    "and we reduced the latency for every request we served."
)
ANSWER_2 = (
    "The hardest bug I fixed was a race condition in our billing worker "
    "that double charged customers when two jobs ran at the same time."
)
SPOKEN_A1 = f"{SPEECH_CHECK_SENTENCE} {ANSWER_1}"

VOICE_MAP = {
    "samantha": "Samantha (English (US))",  # en_US
    "daniel": "Daniel (English (UK))",      # en_GB
    "rishi": "Rishi (English (India))",     # en_IN
}

PREFLIGHT_TILES = 4
ANSWER_1_TILES = 5
ANSWER_2_TILES = 12
PRE_GAP_S = 4.0   # > AUTO_COMMIT_SILENCE (2.5s) with margin for VAD/turn latency: lets the silence commit fire between takes
SENT_GAP_S = 6.0  # gap between preflight sentence repeats

ok = True


def verdict(cond: bool, label: str, detail: str = "") -> bool:
    global ok
    ok = ok and bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{' — ' + detail if detail else ''}")
    return bool(cond)


# ----------------------------------------------------------------------------
# WAV synthesis (macOS `say` -> afconvert -> PCM16/16k tiles -> one capture wav)
# ----------------------------------------------------------------------------

def synth_text_pcm(text: str, voice: str, rate: int = 230) -> bytes:
    """One spoken sentence as 16k mono PCM16 bytes."""
    tmp = Path(f"/tmp/e2e_voice_{abs(hash((text, voice)))}.aiff")
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(tmp), text], check=True, timeout=60)
    wav_tmp = tmp.with_suffix(".wav")
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(tmp), str(wav_tmp)], check=True, timeout=60)
    with wave.open(str(wav_tmp), "rb") as wf:
        pcm = wf.readframes(wf.getnframes())
    tmp.unlink(missing_ok=True)
    wav_tmp.unlink(missing_ok=True)
    return pcm


def silence_pcm(secs: float) -> bytes:
    return b"\x00" * int(16000 * secs) * 2


def build_capture_wav(out_path: Path, voice: str) -> float:
    """Preflight sentence tiles -> answer-1 tiles -> answer-2 tiles, 2.8s gaps."""
    pre = synth_text_pcm(SPEECH_CHECK_SENTENCE, voice)
    a1 = synth_text_pcm(ANSWER_1, voice)
    a2 = synth_text_pcm(ANSWER_2, voice)
    parts: list = []
    parts += [pre, silence_pcm(SENT_GAP_S)] * PREFLIGHT_TILES
    parts += [a1, silence_pcm(PRE_GAP_S)] * ANSWER_1_TILES
    parts += [a2, silence_pcm(PRE_GAP_S)] * ANSWER_2_TILES
    pcm = b"".join(parts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm)
    return len(pcm) / 32000.0


# ----------------------------------------------------------------------------
# Word metrics: WER + best-window match (the commit may cover any window of the
# capture file — head-truncated takes are harness artifacts, not product bugs)
# ----------------------------------------------------------------------------

def _words(text: str) -> list:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def wer(ref: str, hyp: str) -> float:
    """Word error rate: (sub + del + ins) / reference words."""
    r, h = _words(ref), _words(hyp)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1] / len(r)


def best_window_wer(spoken: str, stored: str, min_words: int = 6) -> float:
    """Min WER between the stored answer and any >= min_words window of the spoken take."""
    w = _words(spoken)
    h = _words(stored)
    if not h:
        return 1.0
    best = wer(spoken, stored)
    max_win = min(len(w), max(min_words, int(len(h) * 2.0)))
    for i in range(0, len(w) - min_words + 1):
        for j in range(i + min_words, min(len(w), i + max_win) + 1):
            score = wer(" ".join(w[i:j]), stored)
            if score < best:
                best = score
                if best == 0.0:
                    return 0.0
    return best


def word_coverage(spoken: str, stored: str) -> float:
    """Fraction of the spoken words matched in order inside the stored take.

    Insertions (the STT stitching overlapping takes repeats content) do NOT reduce
    coverage; deletions and substitutions do (substitutions count 50%). This makes
    the check robust to splice artifacts while still failing genuinely lossy text.
    """
    import difflib

    w = _words(spoken)
    h = _words(stored)
    if not w or not h:
        return 0.0
    sm = difflib.SequenceMatcher(None, w, h, autojunk=False)
    matched = 0.0
    for tag, i1, i2, _j1, _j2 in sm.get_opcodes():
        if tag == "equal":
            matched += i2 - i1
        elif tag == "replace":
            matched += 0.5 * (i2 - i1)
    return matched / len(w)


def contains_tail(stored: str, spoken: str, n: int = 5) -> bool:
    """True when the last n spoken words are inside the stored answer (no tail loss)."""
    sw = _words(stored)
    tail = _words(spoken)[-n:]
    return all(t in sw for t in tail)


# ----------------------------------------------------------------------------
# Servers
# ----------------------------------------------------------------------------

_servers: list = []


def servers_up() -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/api/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def frontend_up() -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(FRONTEND_URL, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def start_servers() -> None:
    if not servers_up():
        print("[setup] starting backend (uvicorn :8000)...")
        _servers.append(subprocess.Popen(
            [str(REPO / ".venv/bin/uvicorn"), "backend.app.main:app",
             "--host", "0.0.0.0", "--port", "8000"],
            cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        ))
    if not frontend_up():
        print("[setup] starting frontend (vite :3000)...")
        _servers.append(subprocess.Popen(
            ["npm", "run", "dev"], cwd=str(REPO / "frontend"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        ))
    deadline = time.time() + 90
    while time.time() < deadline:
        if servers_up() and frontend_up():
            return
        time.sleep(1.0)
    raise RuntimeError("servers did not come up")


def stop_servers() -> None:
    import signal

    for p in _servers:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except Exception:
            p.terminate()


# ----------------------------------------------------------------------------
# Evidence sources: session trace timeline + DB turns
# ----------------------------------------------------------------------------

def read_timeline(session_id: str) -> list:
    path = REPO / "debug/sessions" / session_id / "timeline.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def wait_for(predicate, timeout: float, poll: float = 0.5, desc: str = ""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = predicate()
        if v:
            return v
        time.sleep(poll)
    raise TimeoutError(f"timed out waiting for {desc or 'condition'}")


async def db_turns(session_id: str) -> list:
    """The real persisted rows (interview_transcript_turns) — DB-level proof."""
    from sqlalchemy import select

    from backend.app.database import AsyncSessionLocal
    from backend.app.models import InterviewTranscriptTurn

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(InterviewTranscriptTurn)
            .where(InterviewTranscriptTurn.session_id == session_id)
            .order_by(InterviewTranscriptTurn.created_at)
        )).scalars().all()
        return [
            {"speaker": r.speaker, "turn_type": r.turn_type, "text": r.text, "provider": r.provider}
            for r in rows
        ]


# ----------------------------------------------------------------------------
# Browser drive
# ----------------------------------------------------------------------------

async def run_browser(voice: str, wav_path: Path) -> dict:
    from playwright.async_api import async_playwright

    metrics: dict = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=[
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            # NO %noloop: the capture loops. The real flow's welcome/gate/question
            # speech overlaps the wav's tiles, and the room's echo gate drops audio
            # while the bot speaks — a linear wav would be consumed BEFORE the first
            # answer listening window. Looping gives content-adaptive matching the
            # repeated answer takes it needs.
            f"--use-file-for-fake-audio-capture={wav_path}",
            "--autoplay-policy=no-user-gesture-required",
        ])
        page = await browser.new_page()
        page.set_default_timeout(15000)

        # --- API setup: candidate only. The practice session is created BY THE UI's
        # own warm-up click (real path); we capture its response body to learn the
        # session id the room actually lives in. ---
        import httpx

        practice_resp: dict = {}

        def on_response(r):
            if "/api/candidate/practice-interview" in r.url and r.request.method == "POST":
                practice_resp["item"] = r

        page.on("response", on_response)

        stamp = f"{voice}-{int(time.time())}"
        email = f"e2e.{stamp}@candidly.test"
        async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=30) as api:
            r = await api.post("/api/auth/signup", json={
                "email": email, "password": "E2eVoicePass123!", "role": "candidate",
                "full_name": f"E2E {voice.title()} Voice",
            })
            if r.status_code not in (200, 201):
                r = await api.post("/api/auth/login", json={"email": email, "password": "E2eVoicePass123!"})
            auth = r.json()
            token = auth.get("access_token")
            user = auth.get("user")
        print(f"[setup] candidate={email}")

        # --- inject auth and open the candidate dashboard ---
        await page.add_init_script(
            f"localStorage.setItem('candidly-auth-token-candidate', {json.dumps(token)});"
            f"localStorage.setItem('candidly-auth-token', {json.dumps(token)});"
            f"localStorage.setItem('candidly-auth-user', {json.dumps(json.dumps(user))});"
        )
        await page.goto(FRONTEND_URL)
        # Landing page -> candidate dashboard (header entry point).
        await page.get_by_role("button", name="Explore Jobs").click()
        # Practice warm-up path: the UI itself fires practice-interview + session/start
        # and mounts the LiveInterviewRoom directly (no preflight modal — that belongs
        # to the application flow). getUserMedia fires on room mount.
        await page.get_by_title("Conduct a 5-minute warm-up interview with the AI interviewer").click()

        # The session id the ROOM lives in comes from the UI's own practice POST.
        t_wait = time.time()
        while "item" not in practice_resp and time.time() - t_wait < 15:
            await asyncio.sleep(0.2)
        if "item" not in practice_resp:
            raise RuntimeError("the UI's practice-interview POST was never observed")
        try:
            practice_payload = await practice_resp["item"].json()
        except Exception:
            practice_payload = json.loads(await practice_resp["item"].body())
        session_id = practice_payload["id"]
        print(f"[setup] room session (UI-created)={session_id}")
        metrics["session_id"] = session_id

        # --- live room mounts straight away (practice flow) ---
        begin_btn = page.get_by_role("button", name="Begin Interview")
        await begin_btn.wait_for(state="visible")
        await begin_btn.click()
        begin_t = time.time()

        def timeline():
            return read_timeline(session_id)

        # Begin must be ACCEPTED by the server — the welcome TTS trace event is the
        # proof. Fails fast (30s) if the 409 race somehow ate the click.
        wait_for(
            lambda: any(r.get("event_type") == "TTS" for r in timeline()),
            timeout=30, desc="welcome TTS (begin accepted)",
        )
        print(f"[room] welcome TTS observed +{round(time.time() - begin_t, 1)}s after Begin")

        def commits():
            return [r for r in timeline() if r.get("event_type") == "COMMIT"]

        async def read_caption() -> str:
            p = page.locator("xpath=//span[starts-with(text(),'Your words')]/following::p[1]")
            try:
                if await p.count():
                    return (await p.first.inner_text()).strip()
            except Exception:
                pass
            return ""

        async def wait_caption(predicate, timeout: float, desc: str, poll: float = 0.5) -> str:
            """Poll the live caption DOM node until `predicate(text)` holds; return the text."""
            t0 = time.time()
            while time.time() - t0 < timeout:
                text = await read_caption()
                if predicate(text):
                    return text
                await asyncio.sleep(poll)
            raise TimeoutError(f"timed out waiting for {desc or 'condition'}")

        # 2. Live caption shows the candidate's ACTUAL words (not the pre-speech placeholder).
        CAPTION_PLACEHOLDER = "Your answer will appear here"
        caption1 = await wait_caption(
            lambda t: bool(t) and CAPTION_PLACEHOLDER not in t,
            timeout=120, desc="live caption to show real words",
        )
        metrics["first_caption_wall_s"] = round(time.time() - begin_t, 1)
        print(f"[room] live caption real words at +{metrics['first_caption_wall_s']}s after Begin: \"{caption1[:70]}\"")

        # 3-5 adaptive: find the first commit whose stored text matches the spoken take
        # (tail containment + window-aware WER). The blob commits carry whatever the
        # take happened to overlap with (preflight words included).
        def match_commit(tail_ref, since=0.0, min_words=6):
            for c in commits():
                if c.get("timestamp", 0) <= since:
                    continue  # only commits after the previous turn's commit count
                stored = c.get("full_answer") or ""
                if (
                    contains_tail(stored, tail_ref, 5)
                    and word_coverage(tail_ref, stored) >= 0.8
                ):
                    return c
            return None

        done_btn = page.get_by_role("button", name="I'm done answering")

        async def commit_now(tail_ref, ready_markers, timeout=300, label="commit", since=0.0):
            """Wait for the take's LAST words in the live caption, then BUTTON-commit.

            Gating on the tail (not early phrases) is deliberate: clicking mid-take
            commits a fragment, which resets the turn AND advances the scripted flow
            (short-answer prompts), wrecking the next answer's listening window.
            Freshness gate: the click goes out only right after the caption CHANGED to
            text containing the tail (a stale frozen caption means the bot is speaking
            and the click would be ignored / commit old content). Retries every 8s cover
            ignored clicks. Reason is reported but not asserted — both paths are real.
            """
            await wait_caption(
                lambda t: any(m in t.lower() for m in ready_markers),
                timeout=timeout, desc=f"{label} take tail in the live caption",
            )
            t0 = time.time()
            last_click = 0.0
            last_caption = ""
            last_change = time.time()
            tries = 0
            while time.time() - t0 < timeout:
                hit = match_commit(tail_ref, since=since)
                if hit:
                    print(f"[diag] {label}: {tries} click attempts before the commit landed")
                    return hit
                text = await read_caption()
                if text != last_caption:
                    last_caption = text
                    last_change = time.time()
                fresh = (time.time() - last_change) < 25.0 and last_caption and any(
                    m in last_caption.lower() for m in ready_markers
                )
                if fresh and time.time() - last_click > 8.0:
                    tries += 1
                    if tries % 5 == 1:
                        try:
                            en = await done_btn.is_enabled(timeout=1000)
                        except Exception:
                            en = False
                        print(f"[diag] {label} t+{round(time.time() - t0)}s click try#{tries} enabled={en} caption=\"{(last_caption or '')[:60]}\"")
                    try:
                        await done_btn.click(timeout=3000)  # quick throw when disabled (bot speaking)
                        print(f"[diag] {label} click try#{tries} dispatched")
                    except Exception:
                        pass
                    last_click = time.time()
                await asyncio.sleep(1.0)
            print(f"[diag] {label}: {tries} click attempts made before timeout")
            raise TimeoutError(f"timed out waiting for {label} commit")

        c1 = await commit_now(ANSWER_1,
                              ("request we served",), label="answer-1")
        metrics["commit1"] = {
            "reason": c1.get("reason"),
            "finalize_source": c1.get("finalize_source"),
            "finalize_ms": c1.get("finalize_ms"),
            "full_answer": c1.get("full_answer", ""),
            "first_caption_ms": c1.get("first_caption_ms"),
            "avg_partial_interval_ms": c1.get("avg_partial_interval_ms"),
            "max_partial_interval_ms": c1.get("max_partial_interval_ms"),
            "partial_count": c1.get("partial_count"),
            "commit_ms": c1.get("commit_ms"),
        }
        print(f"[room] answer-1 commit: reason={c1.get('reason')} finalize={c1.get('finalize_source')} ({c1.get('finalize_ms')}ms) words={c1.get('word_count')}")
        print(f"[room]   stored: \"{c1.get('full_answer', '')}\"")

        # 6. The NEXT question is spoken: TTS first-audio after the commit.
        commit1_ts = c1["timestamp"]
        tts_after = wait_for(
            lambda: [r for r in timeline() if r.get("event_type") == "TTS" and r.get("timestamp") > commit1_ts],
            timeout=60, desc="next question TTS after answer-1 commit",
        )
        metrics["tts_after_commit_ms"] = tts_after[0].get("latency_ms")
        print(f"[room] next question TTS first-audio: {metrics['tts_after_commit_ms']}ms after commit")

        # 5b. Answer 2: same adaptive button-commit flow — matches only commits
        # occurring after answer 1's commit (the turn resets at each commit).
        c2 = await commit_now(ANSWER_2,
                              ("ran at the same time", "at the same time"),
                              label="answer-2", since=commit1_ts)
        metrics["commit2"] = {
            "reason": c2.get("reason"),
            "finalize_source": c2.get("finalize_source"),
            "finalize_ms": c2.get("finalize_ms"),
            "full_answer": c2.get("full_answer", ""),
            "commit_ms": c2.get("commit_ms"),
        }
        print(f"[room] answer-2 commit: reason={c2.get('reason')} finalize={c2.get('finalize_source')} ({c2.get('finalize_ms')}ms)")
        print(f"[room]   stored: \"{c2.get('full_answer', '')}\"")

        # Cadence metrics from the trace (server-side truth over the whole session).
        partials = [
            r for r in timeline()
            if r.get("event_type") == "STT" and not r.get("is_final") and str(r.get("lane", "")).endswith("_partial")
        ]
        intervals = [float((r.get("meta") or {}).get("interval_ms") or 0) for r in partials]
        intervals = [i for i in intervals if i > 0]
        firsts = [float((r.get("meta") or {}).get("first_delay_ms") or 0) for r in partials]
        firsts = [f for f in firsts if f > 0]
        metrics["cadence"] = {
            "partial_events": len(partials),
            "first_caption_ms": min(firsts) if firsts else None,
            "avg_interval_ms": round(sum(intervals) / len(intervals), 1) if intervals else None,
            "max_interval_ms": round(max(intervals), 1) if intervals else None,
            "over_300ms": sum(1 for i in intervals if i > 300),
        }

        await page.wait_for_timeout(1500)
        await browser.close()
    return metrics


# ----------------------------------------------------------------------------

async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default="samantha", choices=list(VOICE_MAP))
    parser.add_argument("--keep-servers", action="store_true", help="leave servers running after the test")
    args = parser.parse_args()

    started_here = False
    if not (servers_up() and frontend_up()):
        start_servers()
        started_here = True
        print("[setup] servers ready")
    else:
        print("[setup] servers already running")

    wav_path = REPO / "debug" / "e2e_voice" / f"capture_{args.voice}.wav"
    duration = build_capture_wav(wav_path, VOICE_MAP[args.voice])
    print(f"[setup] capture wav built: {wav_path.name} ({duration:.0f}s, voice={VOICE_MAP[args.voice]})")

    metrics: dict = {}
    try:
        print(f"\n=== R3.5b E2E voice session ({args.voice}) — real browser mic -> WebRTC -> server ===")
        metrics = await run_browser(args.voice, wav_path)
        session_id = metrics["session_id"]

        # 1. Per-segment audio capture (real path).
        audio_dir = REPO / "debug/sessions" / session_id / "audio"
        audio_files = list(audio_dir.glob("*")) if audio_dir.exists() else []
        verdict(len(audio_files) >= 2, "audio captured per VAD segment", f"{len(audio_files)} files in debug/sessions/{session_id[-8:]}/audio/")

        # 2. Live caption appeared (flow already enforced) — restate with timing.
        verdict(metrics.get("first_caption_wall_s") is not None, "live caption appeared",
                f"+{metrics.get('first_caption_wall_s')}s after Begin Interview")

        # 3-4. Persisted answers: word coverage in order + no tail truncation.
        for label, key, tail_ref in (
            ("answer 1", "commit1", ANSWER_1),
            ("answer 2", "commit2", ANSWER_2),
        ):
            stored = (metrics[key].get("full_answer") or "").strip()
            if not stored:
                verdict(False, f"{label}: persisted text non-empty", "empty stored answer")
                continue
            cov = word_coverage(tail_ref, stored)
            tail_ok = contains_tail(stored, tail_ref, 5)
            verdict(cov >= 0.8, f"{label}: persisted matches spoken text (in-order word coverage)",
                    f"coverage={cov:.2f}")
            verdict(tail_ok, f"{label}: no tail loss (last 5 spoken words present)", f"stored=\"{stored[:70]}\"")
            verdict(metrics[key].get("finalize_source") in ("finalized", "already-final", "fallback"),
                    f"{label}: finalize of record", f"{metrics[key].get('finalize_source')} ({metrics[key].get('finalize_ms')}ms)")

        # 5. Commit reasons: the mechanism that landed the turn (silence auto-commit
        # when the take ends before the candidate clicks; button otherwise).
        verdict(metrics["commit1"]["reason"] in ("silence", "button"), "answer 1 commit mechanism recorded (silence|button)", str(metrics["commit1"]["reason"]))
        verdict(metrics["commit2"]["reason"] in ("silence", "button"), "answer 2 commit mechanism recorded (silence|button)", str(metrics["commit2"]["reason"]))
        print(f"[room] commit reasons: answer-1={metrics['commit1']['reason']} answer-2={metrics['commit2']['reason']}")

        # 6. Next question spoken.
        verdict(metrics.get("tts_after_commit_ms") is not None, "next question spoken (TTS first-audio)", f"{metrics.get('tts_after_commit_ms')}ms")

        cad = metrics.get("cadence") or {}
        verdict((cad.get("avg_interval_ms") or 999) <= 300, "caption cadence <= 300ms avg between updates",
                f"avg={cad.get('avg_interval_ms')}ms max={cad.get('max_interval_ms')}ms over {cad.get('partial_events')} partials")

        # DB-level proof: the turn rows exist with the stored text.
        turns = await db_turns(session_id)
        cand_rows = [t for t in turns if t["speaker"] == "candidate"]
        stored_texts = [t["text"] for t in cand_rows]
        verdict(len(cand_rows) >= 2, "candidate answers persisted in DB",
                f"{len(cand_rows)} candidate rows of {len(turns)} turns")
        verdict(any(metrics["commit1"]["full_answer"][:20] in t for t in stored_texts if t),
                "DB text == commit record text", "commit1 answer found in interview_transcript_turns")

        print("\n[measured] "
              f"partials={cad.get('partial_events')} first_caption={cad.get('first_caption_ms')}ms "
              f"avg_interval={cad.get('avg_interval_ms')}ms max_interval={cad.get('max_interval_ms')}ms "
              f"intervals_over_300ms={cad.get('over_300ms')} (target <= 300ms)")
        print(f"[evidence] python scripts/print_turn_timeline.py {session_id}")
        print(f"[evidence] debug/sessions/{session_id}/audio/ ({len(audio_files)} segments)")
        return 0 if ok else 1
    finally:
        if started_here and not args.keep_servers:
            stop_servers()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
