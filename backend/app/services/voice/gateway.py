"""Voice Gateway Service.

FastAPI WebSocket gateway connecting client mic audio to Deepgram Flux STT
and Aura-2 TTS, plus an interactive developer verification page.

Phase 2 Features:
- Capture: AudioWorklet at 16kHz mono PCM16 with AEC, NS, AGC (30ms frames).
- Playback: AudioWorklet ring buffer for 24kHz Aura-2 PCM (250ms pre-buffer + soft fade-in).
- Half-Duplex: Server blocks mic forwarding during bot speech + 300ms post playback.
- Keyterms: Dynamic extraction from session JobSkill and BlueprintSection (max 20, deduped).
- Defaults: 0.85 threshold / 6000ms timeout from env (4-5s thinking pause tolerance).
- Duplicate checker: Flags repeated 1-4 word n-grams within each turn (report only).
- Metrics: Shows latency from last voiced frame, trigger, and playback start delay.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from websockets.exceptions import ConnectionClosed

from backend.app.database import AsyncSessionLocal
from backend.app.models import (
    BlueprintSection,
    InterviewBlueprint,
    InterviewSession,
    JobApplication,
    JobPosting,
    JobSkill,
)
from backend.app.services.auth import decode_access_token
from backend.app.services.voice.aura_tts import AuraTTSClient
from backend.app.services.voice.flux_stt import (
    DEFAULT_EOT_THRESHOLD,
    DEFAULT_EOT_TIMEOUT_MS,
    DeepgramKeyPool,
    EagerEndOfTurn,
    EndOfTurn,
    FluxSTTClient,
    StartOfTurn,
    TurnResumed,
    Update,
    get_shared_key_pool,
)

logger = logging.getLogger("candidly.voice.gateway")

router = APIRouter(tags=["voice"])

DEFAULT_KEYTERMS: List[str] = [
    "exponential backoff",
    "composite index",
    "blue-green",
]


def _validate_ws_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Validate JWT token from query param or header.

    Dev token bypass strictly requires an explicit environment flag:
        ALLOW_DEV_WS_AUTH=true
    and is OFF by default.
    """
    allow_dev = os.getenv("ALLOW_DEV_WS_AUTH", "false").lower() == "true"

    if not token:
        if allow_dev and os.getenv("ENV") in ("development", "dev", "test"):
            return {"sub": "dev-user", "role": "dev"}
        return None

    if allow_dev and token in ("dev", "test", "dev-token"):
        return {"sub": "dev-user", "role": "dev"}

    try:
        payload = decode_access_token(token)
        return payload
    except Exception as e:
        logger.warning("WebSocket token verification failed: %s", e)
        if allow_dev:
            return {"sub": "dev-user-fallback", "role": "dev"}
        return None


def _resume_keyterms(application) -> List[str]:
    """Extract biasing vocabulary from the candidate's parsed resume.

    The candidate will actually SAY these words (their technologies, companies,
    project names) — biasing Deepgram toward them is the single biggest STT
    accuracy lever available for personalized interviews.
    """
    resume = getattr(application, "resume", None)
    if not resume:
        return []
    raw = getattr(resume, "parsed_structured_data", None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, dict):
        return []

    terms: List[str] = []

    def _clean(value) -> Optional[str]:
        text = str(value or "").strip()
        # Keyterms must be 1-4 words to be useful biasing terms
        if not text or len(text.split()) > 4:
            return None
        return text

    skills = raw.get("skills") or {}
    if isinstance(skills, dict):
        for values in skills.values():
            if isinstance(values, list):
                for v in values:
                    t = _clean(v)
                    if t:
                        terms.append(t)
    elif isinstance(skills, list):
        for v in skills:
            t = _clean(v)
            if t:
                terms.append(t)

    for job in raw.get("work_experience") or raw.get("experience") or []:
        if isinstance(job, dict):
            t = _clean(job.get("company") or job.get("name"))
            if t:
                terms.append(t)

    for proj in raw.get("projects") or []:
        if isinstance(proj, dict):
            t = _clean(proj.get("name") or proj.get("title"))
            if t:
                terms.append(t)
            for tech in proj.get("technologies") or proj.get("skills") or []:
                t = _clean(tech)
                if t:
                    terms.append(t)

    return terms


async def get_session_keyterms(session_id: str) -> List[str]:
    """Retrieve keyterms for the session.

    Priority order (highest transcription impact first):
    1. Job competency names (the interview's scoring vocabulary)
    2. Blueprint section skill names
    3. Candidate resume vocabulary (technologies, companies, projects) —
       these are the words the candidate will actually say
    4. Acceptance keyterms ('exponential backoff', 'composite index', 'blue-green')

    Returns up to 20 unique keyterms (no weights).
    """
    keyterms: List[str] = []
    seen: Set[str] = set()

    def add_term(term: Optional[str]) -> None:
        if not term:
            return
        cleaned = term.strip()
        if not cleaned:
            return
        lower = cleaned.lower()
        if lower not in seen and len(keyterms) < 20:
            seen.add(lower)
            keyterms.append(cleaned)

    # 1. Query database for session-specific skills, blueprint terms, and resume vocabulary
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(InterviewSession)
                .options(
                    selectinload(InterviewSession.job).selectinload(JobPosting.skills),
                    selectinload(InterviewSession.blueprint).selectinload(InterviewBlueprint.sections),
                    selectinload(InterviewSession.application).selectinload(JobApplication.resume),
                )
                .filter(InterviewSession.id == session_id)
            )
            session = result.scalars().first()
            if session:
                if session.job and session.job.skills:
                    for skill in session.job.skills:
                        if skill.name:
                            add_term(skill.name)
                if session.blueprint and session.blueprint.sections:
                    for section in session.blueprint.sections:
                        if section.skill_name:
                            add_term(section.skill_name)
                if session.application:
                    for term in _resume_keyterms(session.application):
                        add_term(term)
    except Exception as e:
        logger.warning("Could not fetch session keyterms from database for %s: %s", session_id, e)

    # 2. Add required test keyterms
    for default_term in DEFAULT_KEYTERMS:
        add_term(default_term)

    return keyterms[:20]


def check_repeated_ngrams(text: str) -> List[Dict[str, Any]]:
    """Flag repeated adjacent n-grams of 1-4 words within the turn (report only)."""
    words = re.sub(r"[^a-zA-Z0-9'\s]", " ", text.lower()).split()
    dups: List[Dict[str, Any]] = []
    for n in range(1, 5):
        i = 0
        while i <= len(words) - 2 * n:
            if words[i : i + n] == words[i + n : i + 2 * n]:
                matched_phrase = " ".join(words[i : i + 2 * n])
                dups.append({"n": n, "match": matched_phrase})
                i += n
            else:
                i += 1
    return dups


# -----------------------------------------------------------------------------
# WebSocket Endpoint: /ws/voice/{session_id}
# -----------------------------------------------------------------------------

@router.websocket("/ws/voice/{session_id}")
async def voice_websocket_gateway(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(None),
    eot_threshold: Optional[float] = Query(None),
    eot_timeout_ms: Optional[int] = Query(None),
) -> None:
    """Real-time voice gateway for a candidate interview session.

    Accepts 16kHz 16-bit linear PCM microphone frames from the client.
    Streams back typed Flux STT events (StartOfTurn, Update, EndOfTurn)
    and Aura-2 24kHz PCM TTS audio frames upon request.
    """
    # 1. Authenticate via token query param or Authorization header
    auth_header = websocket.headers.get("authorization")
    extracted_token = token
    if not extracted_token and auth_header and auth_header.startswith("Bearer "):
        extracted_token = auth_header.split(" ")[1]

    claims = _validate_ws_token(extracted_token)
    if not claims:
        logger.warning("Rejecting unauthorized voice WS connection for session %s", session_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized JWT token")
        return

    await websocket.accept()
    logger.info("Voice WS accepted for session %s (user=%s)", session_id, claims.get("sub"))

    # 2. Keyterms extraction & client configuration
    session_keyterms = await get_session_keyterms(session_id)
    target_threshold = eot_threshold if eot_threshold is not None else DEFAULT_EOT_THRESHOLD
    target_timeout = eot_timeout_ms if eot_timeout_ms is not None else DEFAULT_EOT_TIMEOUT_MS

    logger.info(
        "Session %s config: threshold=%.2f, timeout=%dms, keyterms (%d)=%s",
        session_id,
        target_threshold,
        target_timeout,
        len(session_keyterms),
        session_keyterms,
    )

    key_pool = get_shared_key_pool()
    flux_client = FluxSTTClient(
        key_pool=key_pool,
        model="flux-general-en",
        sample_rate=16000,
        encoding="linear16",
        eot_threshold=target_threshold,
        eot_timeout_ms=target_timeout,
        keyterms=session_keyterms,
    )
    aura_client = AuraTTSClient(
        key_pool=key_pool,
        sample_rate=24000,
        encoding="linear16",
    )

    await flux_client.start()

    # Inform client of active session parameters
    await websocket.send_json({
        "type": "SessionReady",
        "session_id": session_id,
        "keyterms": session_keyterms,
        "eot_threshold": target_threshold,
        "eot_timeout_ms": target_timeout,
    })

    # Half-Duplex State: drop mic audio while bot is speaking until playback_ended + 300ms
    bot_speaking: bool = False
    bot_mute_until: float = 0.0
    last_tts_chunk_sent_time: float = 0.0

    # Active TTS streaming task
    active_tts_task: Optional[asyncio.Task[None]] = None

    # Latency tracking timestamps
    last_text_change_time: float = time.perf_counter()
    last_voiced_frame_time: float = time.perf_counter()
    last_update_text: str = ""

    async def forward_flux_events() -> None:
        """Stream Flux STT events back to the client as JSON frames."""
        nonlocal last_text_change_time, last_voiced_frame_time, last_update_text
        try:
            async for event in flux_client.stream_events():
                if isinstance(event, StartOfTurn):
                    last_text_change_time = time.perf_counter()
                    await websocket.send_json({
                        "type": "StartOfTurn",
                        "transcript": event.transcript,
                        "turn_index": event.turn_index,
                        "audio_window_start": event.audio_window_start,
                        "audio_window_end": event.audio_window_end,
                    })
                elif isinstance(event, Update):
                    if event.text and event.text != last_update_text:
                        last_update_text = event.text
                        last_text_change_time = time.perf_counter()

                    await websocket.send_json({
                        "type": "Update",
                        "text": event.text,
                        "turn_index": event.turn_index,
                        "confidence": event.confidence,
                        "audio_window_start": event.audio_window_start,
                        "audio_window_end": event.audio_window_end,
                    })
                elif isinstance(event, EagerEndOfTurn):
                    await websocket.send_json({
                        "type": "EagerEndOfTurn",
                        "transcript": event.text,
                        "turn_index": event.turn_index,
                        "confidence": event.confidence,
                        "audio_window_start": event.audio_window_start,
                        "audio_window_end": event.audio_window_end,
                    })
                elif isinstance(event, TurnResumed):
                    await websocket.send_json({
                        "type": "TurnResumed",
                        "transcript": event.text,
                        "turn_index": event.turn_index,
                        "audio_window_start": event.audio_window_start,
                        "audio_window_end": event.audio_window_end,
                    })
                elif isinstance(event, EndOfTurn):
                    now = time.perf_counter()
                    latency_ms = max(0.0, (now - last_text_change_time) * 1000.0) if last_text_change_time else 0.0
                    latency_from_voiced_ms = max(0.0, (now - last_voiced_frame_time) * 1000.0) if last_voiced_frame_time else latency_ms

                    # Duplicate check (report only)
                    dups = check_repeated_ngrams(event.text)

                    await websocket.send_json({
                        "type": "EndOfTurn",
                        "text": event.text,
                        "confidence": event.confidence,
                        "turn_index": event.turn_index,
                        "trigger": event.trigger,
                        "latency_ms": round(latency_ms, 1),
                        "latency_from_voiced_ms": round(latency_from_voiced_ms, 1),
                        "duplicates": dups,
                        "audio_window_start": event.audio_window_start,
                        "audio_window_end": event.audio_window_end,
                    })
        except (WebSocketDisconnect, ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.warning("Error forwarding Flux events: %s", e)

    flux_task = asyncio.create_task(forward_flux_events())

    async def run_tts_stream(text_to_speak: str, request_id: Optional[str] = None) -> None:
        """Synthesize and stream 24k PCM audio chunks over WebSocket."""
        nonlocal bot_speaking, bot_mute_until, last_tts_chunk_sent_time
        try:
            first_chunk = True
            async for chunk in aura_client.speak(text_to_speak):
                if first_chunk:
                    first_chunk = False
                    bot_speaking = True
                    flux_client.set_bot_speaking(True)
                    bot_mute_until = float("inf")  # Mute until playback_ended + 300ms
                    await websocket.send_json({
                        "type": "TTSStarted",
                        "request_id": request_id,
                        "first_audio_ms": aura_client.last_first_audio_ms,
                        "voice": aura_client.voice,
                    })
                await websocket.send_bytes(chunk)

            last_tts_chunk_sent_time = time.perf_counter()
            await websocket.send_json({
                "type": "TTSDone",
                "request_id": request_id,
                "first_audio_ms": aura_client.last_first_audio_ms,
                "total_duration_ms": aura_client.last_total_duration_ms,
                "audio_bytes": aura_client.last_audio_bytes,
                "last_chunk_sent_at": last_tts_chunk_sent_time,
            })
        except asyncio.CancelledError:
            bot_speaking = False
            flux_client.set_bot_speaking(False)
            bot_mute_until = 0.0
            await aura_client.cancel()
            await websocket.send_json({"type": "TTSCancelled", "request_id": request_id})
        except Exception as e:
            bot_speaking = False
            flux_client.set_bot_speaking(False)
            bot_mute_until = 0.0
            logger.error("TTS stream error: %s", e)
            await websocket.send_json({"type": "TTSError", "request_id": request_id, "error": str(e)})

    # 3. Handle incoming client messages (binary mic PCM or JSON control)
    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"]:
                raw_bytes = message["bytes"]
                now = time.perf_counter()
                # Half-Duplex Guard: during bot speech or within 300ms post-playback,
                # send zero-filled PCM silence frames to Flux instead of dropping entirely.
                # This prevents Deepgram inactivity timeouts on long replies and keeps Flux's audio timeline synchronized.
                if bot_speaking or now < bot_mute_until:
                    await flux_client.send_audio(b"\x00" * len(raw_bytes))
                    continue

                if len(raw_bytes) >= 320:
                    peak = max(
                        abs(int.from_bytes(raw_bytes[j : j + 2], "little", signed=True))
                        for j in range(0, len(raw_bytes), 2)
                    )
                    if peak > 600:
                        last_voiced_frame_time = time.perf_counter()

                await flux_client.send_audio(raw_bytes)

            elif "text" in message and message["text"]:
                try:
                    payload = json.loads(message["text"])
                except Exception:
                    continue

                event_type = payload.get("type", "")

                if event_type == "playback_ended":
                    # Bot audio finished playing on client. Apply +300ms echo suppression window.
                    bot_speaking = False
                    bot_mute_until = time.perf_counter() + 0.300
                    logger.info("Bot playback ended on client. Half-duplex mute active for +300ms.")
                    async def _unmute_flux_after_delay() -> None:
                        await asyncio.sleep(0.300)
                        if not bot_speaking:
                            flux_client.set_bot_speaking(False)
                    asyncio.create_task(_unmute_flux_after_delay())
                    await websocket.send_json({
                        "type": "HalfDuplexMute",
                        "mute_ms": 300,
                    })

                elif event_type in ("speak", "test_tts"):
                    # Cancel any prior active speech
                    if active_tts_task and not active_tts_task.done():
                        active_tts_task.cancel()
                        await asyncio.sleep(0.01)

                    text_to_speak = payload.get("text", "")
                    req_id = payload.get("request_id")
                    active_tts_task = asyncio.create_task(run_tts_stream(text_to_speak, req_id))

                elif event_type in ("cancel", "interrupt"):
                    bot_speaking = False
                    flux_client.set_bot_speaking(False)
                    bot_mute_until = 0.0
                    if active_tts_task and not active_tts_task.done():
                        active_tts_task.cancel()
                    await aura_client.cancel()
                    await websocket.send_json({"type": "TTSCancelled"})

                elif event_type == "ping":
                    await websocket.send_json({"type": "pong", "time": time.time()})

    except (WebSocketDisconnect, ConnectionClosed, RuntimeError) as exc:
        logger.info("Voice WS disconnected for session %s: %s", session_id, exc)
    except Exception as e:
        logger.error("Error in Voice WS loop: %s", e)
    finally:
        flux_task.cancel()
        if active_tts_task and not active_tts_task.done():
            active_tts_task.cancel()
        await flux_client.stop()
        await aura_client.close()


# -----------------------------------------------------------------------------
# Developer Page: /dev/voice
# -----------------------------------------------------------------------------

DEV_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Candidly AI Voice Gateway - Dev Cockpit</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    @keyframes pulse-slow {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.85; transform: scale(1.03); }
    }
    .animate-pulse-slow { animation: pulse-slow 2.5s infinite ease-in-out; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased p-6">
  <div class="max-w-5xl mx-auto space-y-6">

    <!-- Header -->
    <header class="flex items-center justify-between border-b border-slate-800 pb-4">
      <div>
        <div class="flex items-center gap-3">
          <span class="h-3 w-3 rounded-full bg-emerald-500 animate-pulse"></span>
          <h1 class="text-2xl font-bold tracking-tight text-white">Voice v2 Dev Cockpit</h1>
          <span class="text-xs font-semibold px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
            Phase 2: AudioWorklet &middot; Half-Duplex &middot; Keyterms
          </span>
        </div>
        <p class="text-xs text-slate-400 mt-1">
          Capture Worklet (16k PCM16, AEC/NS/AGC) &middot; Playback Worklet (24k Ring Buffer, 250ms jitter guard + soft fade) &middot; Half-Duplex Echo Suppression
        </p>
      </div>
      <div class="flex items-center gap-3">
        <div class="flex items-center gap-2 bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1">
          <label for="eotThresholdSelect" class="text-[11px] font-medium text-slate-400">Flux Profile:</label>
          <select id="eotThresholdSelect" class="bg-slate-950 border border-slate-700 text-xs text-white rounded px-2 py-0.5 focus:outline-none focus:border-indigo-500 cursor-pointer">
            <option value="0.85">0.85 / 6000ms (Recommended - 5s Thinking Tolerance)</option>
            <option value="0.8">0.80 / 5000ms (Balanced)</option>
            <option value="0.7">0.70 / 4000ms (Fast Response)</option>
          </select>
        </div>
        <div id="connectionPill" class="px-3 py-1.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center gap-2">
          <span class="h-2 w-2 rounded-full bg-amber-400 animate-ping"></span>
          Connecting...
        </div>
      </div>
    </header>

    <!-- Keyterms Strip -->
    <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5 flex items-center justify-between">
      <div class="flex items-center gap-2 flex-wrap">
        <span class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Active Keyterms:</span>
        <div id="keytermsList" class="flex items-center gap-1.5 flex-wrap">
          <span class="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 text-xs font-mono">Loading...</span>
        </div>
      </div>
      <div id="halfDuplexBadge" class="px-2.5 py-1 rounded-full text-[11px] font-medium bg-slate-800 text-slate-400 border border-slate-700 flex items-center gap-1.5">
        <span class="h-1.5 w-1.5 rounded-full bg-slate-400"></span>
        Mic Active (Half-Duplex Ready)
      </div>
    </div>

    <!-- Controls Strip -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <!-- Mic Controls -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
        <div>
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Microphone Capture</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-mono">AudioWorklet (30ms)</span>
          </div>
          <div class="mt-3 flex items-center gap-3">
            <button id="toggleMicBtn" class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-sm transition shadow-lg shadow-emerald-950">
              Start Mic Stream
            </button>
            <div id="micStatusText" class="text-xs text-slate-400">Mic: Inactive</div>
          </div>
        </div>
        <!-- Volume meter -->
        <div class="mt-4">
          <div class="flex justify-between text-[11px] text-slate-400 mb-1">
            <span>Input Level</span>
            <span id="vuLevel">0%</span>
          </div>
          <div class="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
            <div id="vuBar" class="bg-emerald-500 h-full w-0 transition-all duration-75"></div>
          </div>
        </div>
      </div>

      <!-- Turn Stats -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Session Statistics</span>
        <div class="grid grid-cols-3 gap-2 mt-2 text-center">
          <div class="bg-slate-950 p-2 rounded-lg border border-slate-800">
            <div class="text-[10px] text-slate-400 uppercase">Turns</div>
            <div id="turnCount" class="text-xl font-bold text-indigo-400">0</div>
          </div>
          <div class="bg-slate-950 p-2 rounded-lg border border-slate-800">
            <div class="text-[10px] text-slate-400 uppercase">Dup N-Grams</div>
            <div id="dupCount" class="text-xl font-bold text-emerald-400">0</div>
          </div>
          <div class="bg-slate-950 p-2 rounded-lg border border-slate-800">
            <div class="text-[10px] text-slate-400 uppercase">EoT Latency</div>
            <div id="eotLatency" class="text-xl font-bold text-cyan-400">-</div>
          </div>
        </div>
        <div class="text-[11px] text-slate-400 mt-2 text-center" id="sessionStateText">
          State: <span class="text-slate-300 font-medium">Ready</span>
        </div>
      </div>

      <!-- TTS Controls -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col justify-between">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Aura-2 TTS Playback</span>
          <span class="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 font-mono">RingBuffer (250ms Jitter Guard)</span>
        </div>
        <div class="space-y-2 mt-2">
          <input id="ttsInput" type="text" value="Hello! We are testing our blue-green deployment with exponential backoff and a composite index."
            class="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500">
          <div class="flex gap-2">
            <button id="speakBtn" class="flex-1 px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs transition">
              Speak Sentence
            </button>
            <button id="cancelTtsBtn" class="px-3 py-1.5 rounded bg-rose-600/20 hover:bg-rose-600/40 text-rose-300 border border-rose-600/30 font-medium text-xs transition">
              Cancel
            </button>
          </div>
        </div>
        <div class="text-[11px] text-slate-400 mt-1 flex justify-between">
          <span>Playback Delay:</span>
          <span id="playbackStartMetric" class="text-indigo-300 font-mono">-</span>
        </div>
      </div>
    </div>

    <!-- Interview Question Loop & Consolidated Answer Section (Speech between Questions = 1 Answer) -->
    <div class="bg-indigo-950/40 border border-indigo-800/50 rounded-xl p-5 shadow-lg space-y-4">
      <div class="flex items-center justify-between flex-wrap gap-2">
        <div class="flex items-center gap-2">
          <span class="h-2.5 w-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
          <span class="text-xs font-bold uppercase tracking-wider text-indigo-300">
            Interview Question Loop &middot; Consolidated Answer Mode
          </span>
        </div>
        <div class="text-[11px] text-slate-400">
          Speech between questions is grouped into <strong class="text-emerald-400">one single answer</strong>.
        </div>
      </div>

      <!-- Current Question Box -->
      <div class="bg-slate-900/90 border border-slate-800 rounded-lg p-3.5 flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div class="space-y-1 flex-1">
          <div class="text-[11px] font-semibold text-indigo-400 uppercase tracking-wider flex items-center gap-2">
            <span id="questionBadge">Question 1 of 3</span>
            <span id="questionStatus" class="text-slate-400 font-normal">&middot; Ready</span>
          </div>
          <div id="currentQuestionText" class="text-sm font-medium text-white">
            "Can you describe your experience designing high-availability backend systems and database indexing?"
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button id="askQuestionBtn" class="px-3.5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs transition flex items-center gap-1.5 shadow">
            <span>&#9658;</span> Ask Question (TTS)
          </button>
          <button id="nextQuestionBtn" class="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium text-xs transition">
            Skip / Next &rarr;
          </button>
        </div>
      </div>

      <!-- Live Consolidated Candidate Answer -->
      <div class="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-2.5">
        <div class="flex items-center justify-between text-xs flex-wrap gap-2">
          <span class="font-semibold text-emerald-400 flex items-center gap-2">
            <span id="answeringIndicator" class="h-2 w-2 rounded-full bg-slate-600"></span>
            Accumulated Candidate Answer for Current Question
          </span>
          <div class="flex items-center gap-3">
            <span id="chunkCountBadge" class="text-[11px] text-slate-400 font-mono">0 speech segments combined</span>
            <button id="submitAnswerBtn" class="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition shadow flex items-center gap-1.5">
              <span>&#10003;</span> Submit Answer (Manual End Turn)
            </button>
          </div>
        </div>
        <div id="consolidatedAnswerDisplay" class="text-slate-400 text-sm leading-relaxed min-h-[3rem] p-3 rounded bg-slate-900/60 border border-slate-800/80 italic">
          Click "Ask Question" or start speaking. All spoken sentences will accumulate here into one complete answer, even across 3–5 second thinking pauses!
        </div>
        <div class="text-[11px] text-slate-500 flex items-center justify-between">
          <span>Hands-free: Say <strong class="text-indigo-300">"That's my answer"</strong> or <strong class="text-indigo-300">"I'm done"</strong> to auto-submit.</span>
          <span id="answerWordCount" class="font-mono text-slate-400">0 words</span>
        </div>
      </div>
    </div>

    <!-- Live Interim Update Captions Banner -->
    <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-inner">
      <div class="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-indigo-400 mb-2">
        <span class="flex items-center gap-2">
          <span id="updateOrb" class="h-2 w-2 rounded-full bg-slate-500"></span>
          Live Interim Caption (Update event)
        </span>
        <span class="text-[11px] font-normal text-slate-400">Zero text stitching active</span>
      </div>
      <div id="interimText" class="text-lg italic text-slate-300 min-h-[2.5rem] flex items-center">
        Speak into your microphone to view live hypotheses...
      </div>
    </div>

    <!-- Finalized Transcript Turn History -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div class="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
        <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Finalized Answers (EndOfTurn on new line)
        </h2>
        <button id="clearLogsBtn" class="text-xs text-slate-400 hover:text-white transition">Clear Log</button>
      </div>
      <div id="turnHistory" class="space-y-3 min-h-[200px] max-h-[420px] overflow-y-auto pr-2">
        <div class="text-xs text-slate-500 italic">No turns completed yet.</div>
      </div>
    </div>

  </div>

  <script>
    // ---------------------------------------------------------------------------
    // Configuration & State
    // ---------------------------------------------------------------------------
    const loc = window.location;
    const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    const urlParams = new URLSearchParams(loc.search);
    const initialThresh = urlParams.get('eot_threshold') || localStorage.getItem('eot_threshold') || '0.85';

    let ws = null;
    let micAudioCtx = null;
    let micStream = null;
    let captureWorkletNode = null;
    let isMicStreaming = false;

    // TTS playback Web Audio Context (24000 Hz) & Worklet
    let ttsAudioCtx = null;
    let playbackWorkletNode = null;
    let lastTtsDoneTime = 0;
    let lastTtsStartTime = 0;
    let lastFirstAudioMs = 0;

    // Stats
    let turnCount = 0;
    let totalDuplicates = 0;
    let latencies = [];

    // UI Elements
    const eotThresholdSelect = document.getElementById('eotThresholdSelect');
    const connectionPill = document.getElementById('connectionPill');
    const toggleMicBtn = document.getElementById('toggleMicBtn');
    const micStatusText = document.getElementById('micStatusText');
    const vuBar = document.getElementById('vuBar');
    const vuLevel = document.getElementById('vuLevel');
    const interimText = document.getElementById('interimText');
    const updateOrb = document.getElementById('updateOrb');
    const turnHistory = document.getElementById('turnHistory');
    const turnCountEl = document.getElementById('turnCount');
    const dupCountEl = document.getElementById('dupCount');
    const eotLatencyEl = document.getElementById('eotLatency');
    const sessionStateText = document.getElementById('sessionStateText');
    const ttsInput = document.getElementById('ttsInput');
    const speakBtn = document.getElementById('speakBtn');
    const cancelTtsBtn = document.getElementById('cancelTtsBtn');
    const playbackStartMetric = document.getElementById('playbackStartMetric');
    const keytermsList = document.getElementById('keytermsList');
    const halfDuplexBadge = document.getElementById('halfDuplexBadge');
    const clearLogsBtn = document.getElementById('clearLogsBtn');

    // Select profile
    if (eotThresholdSelect) {
      eotThresholdSelect.value = initialThresh;
      if (!eotThresholdSelect.value) eotThresholdSelect.value = '0.85';
      eotThresholdSelect.onchange = () => {
        localStorage.setItem('eot_threshold', eotThresholdSelect.value);
        if (ws) {
          ws.close();
        }
        connectWs();
      };
    }

    // ---------------------------------------------------------------------------
    // Interview Simulation State (Speech between Questions = 1 Consolidated Answer)
    // ---------------------------------------------------------------------------
    const SAMPLE_QUESTIONS = [
      "Can you describe your experience designing high-availability backend systems and database indexing?",
      "How do you implement exponential backoff and handle transient failures in distributed microservices?",
      "Walk me through a blue-green deployment strategy and how you avoid downtime during schema migrations?"
    ];
    let currentQuestionIdx = 0;
    let consolidatedAnswerText = "";
    let consolidatedSegmentCount = 0;
    let isBotAsking = false;

    const questionBadge = document.getElementById('questionBadge');
    const questionStatus = document.getElementById('questionStatus');
    const currentQuestionTextEl = document.getElementById('currentQuestionText');
    const askQuestionBtn = document.getElementById('askQuestionBtn');
    const nextQuestionBtn = document.getElementById('nextQuestionBtn');
    const answeringIndicator = document.getElementById('answeringIndicator');
    const chunkCountBadge = document.getElementById('chunkCountBadge');
    const submitAnswerBtn = document.getElementById('submitAnswerBtn');
    const consolidatedAnswerDisplay = document.getElementById('consolidatedAnswerDisplay');
    const answerWordCount = document.getElementById('answerWordCount');

    let autoCommitTimer = null;
    let autoCommitCountdownInterval = null;
    let autoCommitDeadline = 0;

    function cancelAutoCommitTimer() {
      if (autoCommitTimer) {
        clearTimeout(autoCommitTimer);
        autoCommitTimer = null;
      }
      if (autoCommitCountdownInterval) {
        clearInterval(autoCommitCountdownInterval);
        autoCommitCountdownInterval = null;
      }
    }

    function updateQuestionUI() {
      const qText = SAMPLE_QUESTIONS[currentQuestionIdx];
      if (questionBadge) questionBadge.textContent = `Question ${currentQuestionIdx + 1} of ${SAMPLE_QUESTIONS.length}`;
      if (currentQuestionTextEl) currentQuestionTextEl.textContent = `"${qText}"`;
      if (questionStatus) questionStatus.textContent = isBotAsking ? '· Speaking (Half-Duplex Active)' : '· Ready for candidate answer';
    }

    async function askCurrentQuestion() {
      cancelAutoCommitTimer();
      const qText = SAMPLE_QUESTIONS[currentQuestionIdx];
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert("Please wait for WebSocket connection.");
        return;
      }
      await ensurePlaybackWorklet();
      if (playbackWorkletNode) {
        playbackWorkletNode.port.postMessage({ type: 'start' });
      }
      isBotAsking = true;
      updateQuestionUI();
      sessionStateText.innerHTML = 'State: <span class="text-amber-400 font-bold">Bot Speaking Question...</span>';
      consolidatedAnswerText = "";
      consolidatedSegmentCount = 0;
      if (consolidatedAnswerDisplay) {
        consolidatedAnswerDisplay.textContent = 'Listening for your answer... speak freely and pause to think as much as you like.';
        consolidatedAnswerDisplay.className = 'text-slate-400 text-sm leading-relaxed min-h-[3rem] p-3 rounded bg-slate-900/60 border border-slate-800/80 italic';
      }
      if (chunkCountBadge) chunkCountBadge.textContent = '0 speech segments combined';
      if (answerWordCount) answerWordCount.textContent = '0 words';
      if (answeringIndicator) answeringIndicator.className = 'h-2 w-2 rounded-full bg-slate-600';

      ws.send(JSON.stringify({ type: 'test_tts', text: qText }));
    }

    function submitCurrentAnswer(reason = "Manual button") {
      cancelAutoCommitTimer();
      const cleanAnswer = consolidatedAnswerText.trim();
      if (!cleanAnswer) {
        alert("No answer detected yet. Speak into your microphone first!");
        return;
      }

      const qText = SAMPLE_QUESTIONS[currentQuestionIdx];
      const qNum = currentQuestionIdx + 1;
      const words = cleanAnswer.split(/\s+/).filter(Boolean).length;

      if (turnHistory.children.length === 1 && turnHistory.children[0].classList.contains('italic')) {
        turnHistory.innerHTML = '';
      }

      const qaCard = document.createElement('div');
      qaCard.className = 'p-4 rounded-xl bg-gradient-to-r from-indigo-950/60 to-slate-900 border border-indigo-500/40 space-y-2.5 shadow-md animate-fadeIn';
      qaCard.innerHTML = `
        <div class="flex items-center justify-between text-xs">
          <span class="font-bold text-indigo-300 uppercase tracking-wide">Question ${qNum}: ${escapeHtml(qText)}</span>
          <span class="px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[10px] font-medium">✓ Completed (${escapeHtml(reason)})</span>
        </div>
        <div class="text-sm text-slate-100 font-normal leading-relaxed pl-3 border-l-2 border-emerald-400 bg-slate-950/40 p-2.5 rounded-r">
          ${escapeHtml(cleanAnswer)}
        </div>
        <div class="flex items-center justify-between text-[11px] text-slate-400 pt-1 border-t border-slate-800/80">
          <div class="flex items-center gap-3">
            <span>Words: <strong class="text-emerald-300">${words}</strong></span>
            <span>Segments combined: <strong class="text-indigo-300">${consolidatedSegmentCount}</strong></span>
            <span class="text-emerald-400">Zero cut-offs mid-thought</span>
          </div>
          <span>${new Date().toLocaleTimeString()}</span>
        </div>
      `;
      turnHistory.prepend(qaCard);

      consolidatedAnswerText = "";
      consolidatedSegmentCount = 0;
      currentQuestionIdx = (currentQuestionIdx + 1) % SAMPLE_QUESTIONS.length;
      updateQuestionUI();

      if (consolidatedAnswerDisplay) {
        consolidatedAnswerDisplay.textContent = `Question ${qNum} submitted! Ready for Question ${currentQuestionIdx + 1}. Click "Ask Question" or speak to begin.`;
        consolidatedAnswerDisplay.className = 'text-emerald-400 text-sm leading-relaxed min-h-[3rem] p-3 rounded bg-slate-900/60 border border-emerald-900/40 italic';
      }
      if (chunkCountBadge) chunkCountBadge.textContent = '0 speech segments combined';
      if (answerWordCount) answerWordCount.textContent = '0 words';
      if (answeringIndicator) answeringIndicator.className = 'h-2 w-2 rounded-full bg-slate-600';
    }

    if (askQuestionBtn) askQuestionBtn.onclick = askCurrentQuestion;
    if (nextQuestionBtn) nextQuestionBtn.onclick = () => {
      currentQuestionIdx = (currentQuestionIdx + 1) % SAMPLE_QUESTIONS.length;
      consolidatedAnswerText = "";
      consolidatedSegmentCount = 0;
      updateQuestionUI();
      if (consolidatedAnswerDisplay) {
        consolidatedAnswerDisplay.textContent = `Moved to Question ${currentQuestionIdx + 1}. Click "Ask Question" or speak to begin.`;
      }
    };
    if (submitAnswerBtn) submitAnswerBtn.onclick = () => submitCurrentAnswer("Manual button click");

    // ---------------------------------------------------------------------------
    // AudioWorklet Processors Inline Code
    // ---------------------------------------------------------------------------
    const captureWorkletCode = `
    class CaptureWorkletProcessor extends AudioWorkletProcessor {
      constructor() {
        super();
        // 480 samples at 16kHz = 30ms frames (requirement: 20-40ms)
        this.frameSize = 480;
        this.buffer = new Float32Array(this.frameSize);
        this.bufferIndex = 0;
      }

      process(inputs, outputs, parameters) {
        const input = inputs[0];
        if (!input || !input[0]) return true;
        const channelData = input[0];

        for (let i = 0; i < channelData.length; i++) {
          this.buffer[this.bufferIndex++] = channelData[i];
          if (this.bufferIndex >= this.frameSize) {
            // Convert Float32 to Int16 PCM
            const pcm16 = new Int16Array(this.frameSize);
            let sumSquares = 0;
            for (let j = 0; j < this.frameSize; j++) {
              const s = Math.max(-1, Math.min(1, this.buffer[j]));
              sumSquares += s * s;
              pcm16[j] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            const rms = Math.sqrt(sumSquares / this.frameSize);
            this.port.postMessage({
              pcm16: pcm16.buffer,
              rms: rms
            }, [pcm16.buffer]);
            this.bufferIndex = 0;
          }
        }
        return true;
      }
    }
    registerProcessor('capture-worklet-processor', CaptureWorkletProcessor);
    `;

    const playbackWorkletCode = `
    class PlaybackWorkletProcessor extends AudioWorkletProcessor {
      constructor() {
        super();
        // Ring buffer for 24kHz PCM (capacity: 480000 samples = 20 seconds)
        this.capacity = 480000;
        this.buffer = new Float32Array(this.capacity);
        this.writeIndex = 0;
        this.readIndex = 0;
        this.bufferedCount = 0;

        // 250ms pre-buffer at 24kHz = 6000 samples (eliminates network arrival jitter underflow)
        this.prebufferThreshold = 6000;
        this.isPlaying = false;
        this.isRebuffering = false;
        this.eos = false;
        this.playbackStartedEmitted = false;
        this.fadeInSamplesRemaining = 64; // ~2.7ms linear fade-in prevents DC offset pop/click

        this.port.onmessage = (e) => {
          const data = e.data;
          if (data.type === 'start') {
            this.writeIndex = 0;
            this.readIndex = 0;
            this.bufferedCount = 0;
            this.isPlaying = false;
            this.isRebuffering = false;
            this.eos = false;
            this.playbackStartedEmitted = false;
            this.fadeInSamplesRemaining = 64;
          } else if (data.type === 'chunk') {
            const int16 = new Int16Array(data.pcm16);
            for (let i = 0; i < int16.length; i++) {
              if (this.bufferedCount < this.capacity) {
                this.buffer[this.writeIndex] = int16[i] / 32768.0;
                this.writeIndex = (this.writeIndex + 1) % this.capacity;
                this.bufferedCount++;
              }
            }
            // Start playing once 250ms is buffered
            if (!this.isPlaying && this.bufferedCount >= this.prebufferThreshold) {
              this.isPlaying = true;
              this.isRebuffering = false;
              this.fadeInSamplesRemaining = 64;
              if (!this.playbackStartedEmitted) {
                this.playbackStartedEmitted = true;
                this.port.postMessage({ type: 'playback_started', t: currentTime });
              }
            } else if (this.isRebuffering && (this.bufferedCount >= 2400 || this.eos)) {
              // Resumed from underflow once 100ms rebuffered
              this.isRebuffering = false;
              this.fadeInSamplesRemaining = 64;
            }
          } else if (data.type === 'eos') {
            this.eos = true;
            this.isRebuffering = false;
            if (this.bufferedCount > 0 && !this.isPlaying) {
              this.isPlaying = true;
              this.fadeInSamplesRemaining = 64;
              if (!this.playbackStartedEmitted) {
                this.playbackStartedEmitted = true;
                this.port.postMessage({ type: 'playback_started', t: currentTime });
              }
            }
          } else if (data.type === 'flush') {
            this.writeIndex = 0;
            this.readIndex = 0;
            this.bufferedCount = 0;
            this.isPlaying = false;
            this.isRebuffering = false;
            this.eos = false;
            this.playbackStartedEmitted = false;
            this.fadeInSamplesRemaining = 64;
          }
        };
      }

      process(inputs, outputs, parameters) {
        const output = outputs[0];
        if (!output || !output[0]) return true;
        const channel = output[0];
        const blockSize = channel.length;

        if (!this.isPlaying || this.isRebuffering) {
          channel.fill(0);
          return true;
        }

        for (let i = 0; i < blockSize; i++) {
          if (this.bufferedCount > 0) {
            let sample = this.buffer[this.readIndex];
            this.readIndex = (this.readIndex + 1) % this.capacity;
            this.bufferedCount--;

            if (this.fadeInSamplesRemaining > 0) {
              const gain = (64 - this.fadeInSamplesRemaining) / 64.0;
              sample *= gain;
              this.fadeInSamplesRemaining--;
            }
            channel[i] = sample;
          } else {
            // Buffer underflow mid-utterance: mute cleanly and rebuff
            if (!this.eos) {
              this.isRebuffering = true;
              this.fadeInSamplesRemaining = 64;
              channel.fill(0, i);
              break;
            } else {
              channel[i] = 0;
            }
          }
        }

        // Buffer drained after server indicated end of speech
        if (this.eos && this.bufferedCount === 0) {
          this.isPlaying = false;
          this.isRebuffering = false;
          this.eos = false;
          this.playbackStartedEmitted = false;
          this.port.postMessage({ type: 'playback_ended', t: currentTime });
        }

        return true;
      }
    }
    registerProcessor('playback-worklet-processor', PlaybackWorkletProcessor);
    `;

    // ---------------------------------------------------------------------------
    // WebSocket Lifecycle
    // ---------------------------------------------------------------------------
    function connectWs() {
      const selectedThresh = eotThresholdSelect ? eotThresholdSelect.value : '0.85';
      let selectedTimeout = 6000;
      if (selectedThresh === '0.8') selectedTimeout = 5000;
      else if (selectedThresh === '0.7') selectedTimeout = 4000;
      const wsUrl = `${wsProto}//${loc.host}/ws/voice/smoke-test?token=dev-token&eot_threshold=${selectedThresh}&eot_timeout_ms=${selectedTimeout}`;

      connectionPill.innerHTML = '<span class="h-2 w-2 rounded-full bg-amber-400 animate-ping"></span> Connecting...';
      connectionPill.className = 'px-3 py-1.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center gap-2';

      ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';

      ws.onopen = () => {
        connectionPill.innerHTML = '<span class="h-2 w-2 rounded-full bg-emerald-400"></span> Connected';
        connectionPill.className = 'px-3 py-1.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-2';
        sessionStateText.innerHTML = 'State: <span class="text-emerald-400 font-medium">Ready</span>';
        updateQuestionUI();
      };

      ws.onmessage = async (event) => {
        if (typeof event.data === 'string') {
          try {
            const msg = JSON.parse(event.data);
            handleJsonEvent(msg);
          } catch (e) {
            console.error('Invalid JSON message:', e);
          }
        } else if (event.data instanceof ArrayBuffer) {
          // Binary frame = 24kHz Aura-2 TTS PCM
          feedPlaybackWorklet(event.data);
        }
      };

      ws.onclose = () => {
        connectionPill.innerHTML = '<span class="h-2 w-2 rounded-full bg-rose-400"></span> Disconnected';
        connectionPill.className = 'px-3 py-1.5 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/30 flex items-center gap-2';
        sessionStateText.innerHTML = 'State: <span class="text-rose-400 font-medium">Disconnected</span>';
        setTimeout(connectWs, 3000);
      };

      ws.onerror = (err) => {
        console.error('Voice WS Error:', err);
      };
    }

    // ---------------------------------------------------------------------------
    // Event Handlers
    // ---------------------------------------------------------------------------
    function handleJsonEvent(evt) {
      if (evt.type === 'SessionReady') {
        if (evt.keyterms && Array.isArray(evt.keyterms)) {
          keytermsList.innerHTML = evt.keyterms.map(t => 
            `<span class="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 text-xs font-mono">${escapeHtml(t)}</span>`
          ).join('');
        }

      } else if (evt.type === 'StartOfTurn') {
        cancelAutoCommitTimer();
        if (chunkCountBadge && consolidatedSegmentCount > 0) {
          chunkCountBadge.textContent = `${consolidatedSegmentCount} segment${consolidatedSegmentCount > 1 ? 's' : ''} combined (speaking...)`;
        }
        sessionStateText.innerHTML = 'State: <span class="text-emerald-400 font-bold">User Speaking</span>';
        updateOrb.className = 'h-2 w-2 rounded-full bg-emerald-500 animate-ping';
        interimText.textContent = evt.transcript || '(Listening...)';
        interimText.className = 'text-lg italic text-emerald-300 min-h-[2.5rem] flex items-center';

      } else if (evt.type === 'Update') {
        cancelAutoCommitTimer();
        updateOrb.className = 'h-2 w-2 rounded-full bg-indigo-500 animate-pulse';
        interimText.textContent = evt.text || '...';
        interimText.className = 'text-lg italic text-slate-100 min-h-[2.5rem] flex items-center';

      } else if (evt.type === 'EndOfTurn') {
        sessionStateText.innerHTML = 'State: <span class="text-indigo-400 font-medium">Turn Ended</span>';
        updateOrb.className = 'h-2 w-2 rounded-full bg-slate-500';
        interimText.textContent = 'Awaiting speech...';
        interimText.className = 'text-lg italic text-slate-500 min-h-[2.5rem] flex items-center';

        appendFinalTurn(evt);

      } else if (evt.type === 'TTSStarted') {
        lastTtsStartTime = performance.now();
        lastFirstAudioMs = evt.first_audio_ms || 0;
        halfDuplexBadge.className = 'px-2.5 py-1 rounded-full text-[11px] font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1.5 animate-pulse';
        halfDuplexBadge.innerHTML = '<span class="h-1.5 w-1.5 rounded-full bg-amber-400"></span> Bot Speaking (Half-Duplex Active)';
        if (playbackWorkletNode) {
          playbackWorkletNode.port.postMessage({ type: 'start' });
        }

      } else if (evt.type === 'TTSDone') {
        lastTtsDoneTime = performance.now();
        if (playbackWorkletNode) {
          playbackWorkletNode.port.postMessage({ type: 'eos' });
        }

      } else if (evt.type === 'HalfDuplexMute') {
        isBotAsking = false;
        updateQuestionUI();
        halfDuplexBadge.className = 'px-2.5 py-1 rounded-full text-[11px] font-medium bg-sky-500/20 text-sky-300 border border-sky-500/30 flex items-center gap-1.5';
        halfDuplexBadge.innerHTML = '<span class="h-1.5 w-1.5 rounded-full bg-sky-400"></span> Post-Echo Window (+300ms)';
        setTimeout(() => {
          halfDuplexBadge.className = 'px-2.5 py-1 rounded-full text-[11px] font-medium bg-slate-800 text-slate-400 border border-slate-700 flex items-center gap-1.5';
          halfDuplexBadge.innerHTML = '<span class="h-1.5 w-1.5 rounded-full bg-slate-400"></span> Mic Active (Half-Duplex Ready)';
        }, evt.mute_ms || 300);

      } else if (evt.type === 'TTSCancelled') {
        if (playbackWorkletNode) {
          playbackWorkletNode.port.postMessage({ type: 'flush' });
        }
        halfDuplexBadge.className = 'px-2.5 py-1 rounded-full text-[11px] font-medium bg-slate-800 text-slate-400 border border-slate-700 flex items-center gap-1.5';
        halfDuplexBadge.innerHTML = '<span class="h-1.5 w-1.5 rounded-full bg-slate-400"></span> Mic Active (Half-Duplex Ready)';
      }
    }

    // Duplicate checker: flags repeated n-grams of 1-4 words within the same turn (report only)
    function findRepeatedNGrams(str) {
      const words = str.toLowerCase().replace(/[^a-z0-9'\s]/g, ' ').split(/\s+/).filter(Boolean);
      const dups = [];
      for (let n = 1; n <= 4; n++) {
        let i = 0;
        while (i <= words.length - 2 * n) {
          let isMatch = true;
          for (let j = 0; j < n; j++) {
            if (words[i + j] !== words[i + n + j]) {
              isMatch = false;
              break;
            }
          }
          if (isMatch) {
            dups.push({ n: n, match: words.slice(i, i + 2 * n).join(' ') });
            i += n;
          } else {
            i++;
          }
        }
      }
      return dups;
    }

    function appendFinalTurn(evt) {
      turnCount++;
      turnCountEl.textContent = `${turnCount}`;

      const text = (evt.text || '').trim();
      const detectedDups = evt.duplicates || findRepeatedNGrams(text);
      totalDuplicates += detectedDups.length;
      dupCountEl.textContent = `${totalDuplicates}`;
      dupCountEl.className = totalDuplicates === 0 ? 'text-xl font-bold text-emerald-400' : 'text-xl font-bold text-rose-400';

      const measuredLatency = evt.latency_ms !== undefined ? evt.latency_ms : 0;
      const voicedLatency = evt.latency_from_voiced_ms !== undefined ? evt.latency_from_voiced_ms : measuredLatency;
      latencies.push(voicedLatency);

      // Compute simple p50
      if (latencies.length > 0) {
        const sorted = [...latencies].sort((a, b) => a - b);
        const p50 = sorted[Math.floor(sorted.length * 0.5)];
        eotLatencyEl.textContent = `${p50.toFixed(0)}ms`;
      }

      // 1. Consolidated Answer Accumulation (User's Idea: Speech between Questions = 1 Answer)
      const commitMatch = text.match(/\b(that's my answer|thats my answer|that is my answer|i am done answering|i'm done answering|i am done|i'm done|thats all i have)\b/i);
      let segmentText = text;
      let shouldCommit = false;
      let commitReason = "";

      if (commitMatch) {
        shouldCommit = true;
        commitReason = `Voice phrase: "${commitMatch[0]}"`;
        segmentText = text.replace(commitMatch[0], "").trim();
      }

      if (segmentText) {
        if (consolidatedAnswerText) {
          consolidatedAnswerText += " " + segmentText;
        } else {
          consolidatedAnswerText = segmentText;
        }
        consolidatedSegmentCount++;

        const words = consolidatedAnswerText.split(/\s+/).filter(Boolean).length;
        if (consolidatedAnswerDisplay) {
          consolidatedAnswerDisplay.textContent = consolidatedAnswerText;
          consolidatedAnswerDisplay.className = 'text-slate-100 text-sm leading-relaxed min-h-[3rem] p-3 rounded bg-slate-900/90 border border-slate-700 font-normal';
        }
        if (chunkCountBadge) {
          chunkCountBadge.textContent = `${consolidatedSegmentCount} segment${consolidatedSegmentCount > 1 ? 's' : ''} combined (thinking pauses tolerated)`;
        }
        if (answerWordCount) {
          answerWordCount.textContent = `${words} words`;
        }
        if (answeringIndicator) {
          answeringIndicator.className = 'h-2 w-2 rounded-full bg-emerald-400 animate-pulse';
        }
      }

      if (shouldCommit && consolidatedAnswerText.trim()) {
        submitCurrentAnswer(commitReason);
        return;
      }

      // Start 4.5s autonomous silence auto-commit countdown (hands-free completion)
      if (consolidatedAnswerText.trim() && !isBotAsking) {
        cancelAutoCommitTimer();
        const silenceWindowMs = 4500;
        autoCommitDeadline = performance.now() + silenceWindowMs;

        autoCommitCountdownInterval = setInterval(() => {
          const remaining = Math.max(0, autoCommitDeadline - performance.now());
          const secs = (remaining / 1000).toFixed(1);
          if (remaining > 0 && chunkCountBadge) {
            chunkCountBadge.innerHTML = `<span class="text-amber-400 font-medium animate-pulse">● Thinking pause (auto-commits in ${secs}s if done)</span>`;
          }
        }, 100);

        autoCommitTimer = setTimeout(() => {
          cancelAutoCommitTimer();
          if (consolidatedAnswerText.trim() && !isBotAsking) {
            submitCurrentAnswer("Autonomous silence detection (4.5s idle)");
          }
        }, silenceWindowMs);
      }

      // Remove placeholder
      if (turnHistory.children.length === 1 && turnHistory.children[0].classList.contains('italic')) {
        turnHistory.innerHTML = '';
      }

      const turnCard = document.createElement('div');
      turnCard.className = 'p-3 rounded-lg bg-slate-950/70 border border-slate-800 space-y-1.5 opacity-80 hover:opacity-100 transition';

      const confPercent = Math.round((evt.confidence || 0) * 100);
      const confBadgeColor = confPercent >= 70 ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' : 'bg-amber-500/20 text-amber-300 border-amber-500/30';
      const triggerBadgeColor = evt.trigger === 'timeout' ? 'bg-amber-500/20 text-amber-300 border-amber-500/30' : 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30';
      const dupBadge = detectedDups.length > 0 
        ? `<span class="px-2 py-0.5 rounded border text-[10px] bg-rose-500/20 text-rose-300 border-rose-500/30 font-medium">Dup (${detectedDups.map(d => `${d.n}-gram: "${d.match}"`).join(', ')})</span>`
        : `<span class="px-2 py-0.5 rounded border text-[10px] bg-emerald-500/10 text-emerald-300 border-emerald-500/20">Zero dups</span>`;

      turnCard.innerHTML = `
        <div class="flex items-center justify-between text-xs">
          <span class="font-semibold text-slate-400">Raw Speech Segment #${evt.turn_index + 1}</span>
          <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded border text-[10px] ${triggerBadgeColor}">Trigger: ${evt.trigger || 'model'}</span>
            <span class="px-2 py-0.5 rounded border text-[10px] bg-sky-500/20 text-sky-300 border-sky-500/30" title="Latency from last voiced audio frame">EoT (Voiced): ${voicedLatency.toFixed(0)}ms</span>
            ${dupBadge}
            <span class="px-2 py-0.5 rounded border text-[10px] ${confBadgeColor}">Conf: ${confPercent}%</span>
            <span class="text-slate-400 text-[10px]">${new Date().toLocaleTimeString()}</span>
          </div>
        </div>
        <div class="text-xs text-slate-300 font-normal leading-relaxed">${escapeHtml(text)}</div>
      `;

      turnHistory.appendChild(turnCard);
      turnHistory.scrollTop = turnHistory.scrollHeight;
    }

    function escapeHtml(s) {
      return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // ---------------------------------------------------------------------------
    // Microphone Capture via AudioWorklet (16kHz Linear PCM)
    // ---------------------------------------------------------------------------
    async function startMic() {
      try {
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            sampleRate: 16000,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          }
        });

        micAudioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        if (micAudioCtx.state === 'suspended') {
          await micAudioCtx.resume();
        }

        const blob = new Blob([captureWorkletCode], { type: 'application/javascript' });
        const workletUrl = URL.createObjectURL(blob);
        await micAudioCtx.audioWorklet.addModule(workletUrl);
        URL.revokeObjectURL(workletUrl);

        const source = micAudioCtx.createMediaStreamSource(micStream);
        captureWorkletNode = new AudioWorkletNode(micAudioCtx, 'capture-worklet-processor');

        captureWorkletNode.port.onmessage = (event) => {
          if (!isMicStreaming || !ws || ws.readyState !== WebSocket.OPEN) return;
          const { pcm16, rms } = event.data;

          if (rms > 0.03 && autoCommitTimer) {
            cancelAutoCommitTimer();
            if (chunkCountBadge && consolidatedSegmentCount > 0) {
              chunkCountBadge.textContent = `${consolidatedSegmentCount} segment${consolidatedSegmentCount > 1 ? 's' : ''} combined (speaking...)`;
            }
          }

          // Update VU level
          const pct = Math.min(100, Math.round(rms * 400));
          vuBar.style.width = `${pct}%`;
          vuLevel.textContent = `${pct}%`;

          // Stream 20-40ms PCM binary frame
          ws.send(pcm16);
        };

        source.connect(captureWorkletNode);

        isMicStreaming = true;
        toggleMicBtn.textContent = 'Stop Mic Stream';
        toggleMicBtn.className = 'px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-medium text-sm transition';
        micStatusText.textContent = 'Mic: Streaming 16kHz PCM (Worklet)';
        micStatusText.className = 'text-xs text-emerald-400 font-medium';
      } catch (err) {
        alert('Could not access microphone: ' + err.message);
      }
    }

    function stopMic() {
      isMicStreaming = false;
      if (captureWorkletNode) {
        captureWorkletNode.disconnect();
        captureWorkletNode = null;
      }
      if (micAudioCtx) {
        micAudioCtx.close();
        micAudioCtx = null;
      }
      if (micStream) {
        micStream.getTracks().forEach(t => t.stop());
        micStream = null;
      }

      toggleMicBtn.textContent = 'Start Mic Stream';
      toggleMicBtn.className = 'px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-sm transition shadow-lg shadow-emerald-950';
      micStatusText.textContent = 'Mic: Inactive';
      micStatusText.className = 'text-xs text-slate-400';
      vuBar.style.width = '0%';
      vuLevel.textContent = '0%';
    }

    toggleMicBtn.onclick = () => {
      if (isMicStreaming) stopMic();
      else startMic();
    };

    // ---------------------------------------------------------------------------
    // TTS Playback via AudioWorklet Ring Buffer (24kHz PCM16)
    // ---------------------------------------------------------------------------
    async function ensurePlaybackWorklet() {
      if (!ttsAudioCtx) {
        ttsAudioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
      }
      if (ttsAudioCtx.state === 'suspended') {
        await ttsAudioCtx.resume();
      }
      if (!playbackWorkletNode) {
        const blob = new Blob([playbackWorkletCode], { type: 'application/javascript' });
        const workletUrl = URL.createObjectURL(blob);
        await ttsAudioCtx.audioWorklet.addModule(workletUrl);
        URL.revokeObjectURL(workletUrl);

        playbackWorkletNode = new AudioWorkletNode(ttsAudioCtx, 'playback-worklet-processor');
        playbackWorkletNode.port.onmessage = (e) => {
          if (e.data.type === 'playback_started') {
            const now = performance.now();
            let deltaText = '';
            if (lastTtsDoneTime > 0) {
              const deltaMs = Math.round(now - lastTtsDoneTime);
              deltaText = `${deltaMs >= 0 ? '+' : ''}${deltaMs}ms after last chunk`;
            } else if (lastTtsStartTime > 0) {
              const deltaMs = Math.round(now - lastTtsStartTime);
              deltaText = `${deltaMs}ms after request (250ms buffer ready)`;
            }
            playbackStartMetric.textContent = deltaText || 'Started (250ms pre-buffered)';
          } else if (e.data.type === 'playback_ended') {
            const nowMs = Math.round(performance.now());
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'playback_ended', t: nowMs }));
            }
          }
        };
        playbackWorkletNode.connect(ttsAudioCtx.destination);
      }
    }

    async function feedPlaybackWorklet(arrayBuffer) {
      await ensurePlaybackWorklet();
      playbackWorkletNode.port.postMessage({
        type: 'chunk',
        pcm16: arrayBuffer
      }, [arrayBuffer]);
    }

    speakBtn.onclick = async () => {
      await ensurePlaybackWorklet();
      if (playbackWorkletNode) {
        playbackWorkletNode.port.postMessage({ type: 'start' });
      }
      const text = ttsInput.value.trim();
      if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
      playbackStartMetric.textContent = 'Buffering 250ms...';
      ws.send(JSON.stringify({ type: 'test_tts', text: text }));
    };

    cancelTtsBtn.onclick = () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'cancel' }));
      }
      if (playbackWorkletNode) {
        playbackWorkletNode.port.postMessage({ type: 'flush' });
      }
      playbackStartMetric.textContent = 'Cancelled';
    };

    clearLogsBtn.onclick = () => {
      turnHistory.innerHTML = '<div class="text-xs text-slate-500 italic">Logs cleared.</div>';
    };

    // Start WebSocket
    connectWs();
  </script>
</body>
</html>
"""


@router.get("/dev/voice", response_class=HTMLResponse)
@router.get("/voice-dev", response_class=HTMLResponse)
@router.get("/api/voice/dev", response_class=HTMLResponse)
async def dev_voice_page() -> HTMLResponse:
    """Developer verification interface for testing Deepgram Flux STT & Aura-2 TTS."""
    return HTMLResponse(content=DEV_PAGE_HTML)
