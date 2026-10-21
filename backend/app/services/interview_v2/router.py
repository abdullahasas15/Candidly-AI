"""FastAPI Router for Interview v2: WebSocket gateway and /dev/interview cockpit.

Routes:
- GET /dev/interview: Interactive developer cockpit for running full voice interviews live.
- WebSocket /ws/interview/{session_id}: Full duplex audio + control stream driven by SessionRunner.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.database import AsyncSessionLocal
from backend.app.models import InterviewSession
from backend.app.services.auth import decode_access_token
from backend.app.services.interview_v2.conductor import ConductorPhase
from backend.app.services.interview_v2.runner import (
    SessionRunner,
    build_script,
    load_real_session_script,
    warmup_bridge_cache,
)
from backend.app.services.voice.aura_tts import AuraTTSClient
from backend.app.services.voice.flux_stt import FluxSTTClient, get_shared_key_pool

logger = logging.getLogger("candidly.interview_v2.router")

router = APIRouter(tags=["interview_v2"])

# Active runner registry: session_id -> SessionRunner
ACTIVE_RUNNERS: Dict[str, SessionRunner] = {}


@router.on_event("startup")
async def _on_startup() -> None:
    """Pre-synthesize the 8 bridge clips into memory at startup."""
    asyncio.create_task(warmup_bridge_cache())


@router.get("/dev/interview", response_class=HTMLResponse)
async def dev_interview_cockpit(session_id: Optional[str] = Query(None), reset: bool = Query(False)) -> str:
    """Developer testing cockpit for conducting a real hands-free interview with live mic."""
    selected_session_id = session_id

    # If no session_id provided, pick the latest real materialized session from DB
    if not selected_session_id:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(InterviewSession)
                .options(selectinload(InterviewSession.questions))
                .order_by(InterviewSession.created_at.desc())
                .limit(20)
            )
            sessions = result.scalars().all()
            for s in sessions:
                if s.questions and len(s.questions) >= 5:
                    selected_session_id = s.id
                    break
            if not selected_session_id and sessions:
                selected_session_id = sessions[0].id

    default_sid = selected_session_id or "280f5c37-ce1c-43df-b3cd-ed6ab1a22733"

    # Reset cache on request or if previously completed
    if default_sid:
        from backend.app.services.interview_v2.runner import SESSION_STATE_CACHE
        if reset or (default_sid in SESSION_STATE_CACHE and SESSION_STATE_CACHE[default_sid].get("phase") in ("completed", "closing")):
            SESSION_STATE_CACHE.pop(default_sid, None)

    return DEV_INTERVIEW_PAGE_HTML.replace("__SESSION_ID__", default_sid)


@router.websocket("/ws/interview/{session_id}")
async def ws_interview_endpoint(
    websocket: WebSocket,
    session_id: str,
    ticket: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
) -> None:
    """WebSocket endpoint connecting client audio worklet to the Interview v2 SessionRunner."""
    # 1. Extract and validate ticket / token claims
    auth_token = ticket or token
    if not auth_token:
        headers = getattr(websocket, "headers", {})
        auth_header = headers.get("authorization") if hasattr(headers, "get") else None
        if auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ")[1]

    allow_dev = os.getenv("ALLOW_DEV_WS_AUTH", "false").lower() == "true"
    claims = None
    if auth_token:
        if allow_dev and auth_token in ("dev", "test", "dev-token"):
            claims = {"sub": "dev-user", "role": "dev", "session_id": session_id}
        else:
            try:
                claims = decode_access_token(auth_token)
            except Exception as e:
                logger.warning("Invalid WS ticket for session %s: %s", session_id, e)
                claims = None
    elif allow_dev and os.getenv("ENV") in ("development", "dev", "test"):
        claims = {"sub": "dev-user", "role": "dev", "session_id": session_id}

    if not claims:
        logger.warning("Rejecting unauthenticated WS connection for session %s (no valid ticket)", session_id)
        await websocket.close(code=4401, reason="Unauthorized: Missing or invalid ticket")
        return

    # Check origin if present
    headers = getattr(websocket, "headers", {})
    origin = headers.get("origin") if hasattr(headers, "get") else None
    if origin and not allow_dev:
        allowed_origins = os.getenv("ALLOWED_ORIGINS", "").split(",")
        is_allowed = (
            "localhost" in origin
            or "127.0.0.1" in origin
            or any(ao.strip() and ao.strip() in origin for ao in allowed_origins)
        )
        if not is_allowed:
            logger.warning("Rejecting WS connection from disallowed origin %s", origin)
            await websocket.close(code=4403, reason="Forbidden origin")
            return

    # Ticket bound session check
    ticket_session = claims.get("session_id")
    if ticket_session and ticket_session != session_id:
        logger.warning("WS ticket session mismatch: ticket is for %s, requested %s", ticket_session, session_id)
        await websocket.close(code=4403, reason="Forbidden: Ticket bound to different session")
        return

    # 2. Load real session script from database with eager relationships
    session, script = await load_real_session_script(session_id)
    if not session:
        logger.warning("Session %s not found in database", session_id)
        await websocket.close(code=4004, reason="Session not found")
        return

    # 3. Ownership check: user must be candidate, recruiter, or admin
    user_id = claims.get("sub") or claims.get("id")
    user_email = (claims.get("email") or "").lower()
    user_role = claims.get("role")

    is_dev = allow_dev and user_role == "dev"
    is_admin = user_role == "admin"
    is_candidate = (
        hasattr(session, "application")
        and session.application
        and (
            getattr(session.application, "candidate_id", None) == user_id
            or (getattr(session.application, "email", None) and session.application.email.lower() == user_email)
        )
    )
    is_recruiter = (
        hasattr(session, "job")
        and session.job
        and getattr(session.job, "recruiter_id", None) == user_id
    )

    if not (is_candidate or is_recruiter or is_admin or is_dev):
        logger.warning("User %s is not authorized for session %s", user_id, session_id)
        await websocket.close(code=4403, reason="Forbidden: Not session owner")
        return

    if not script.get("questions"):
        logger.warning("Session %s has no questions in database", session_id)
        await websocket.accept()
        await websocket.send_json({
            "type": "SessionError",
            "error": "EmptySession",
            "detail": f"Interview session {session_id} has no questions configured.",
        })
        await websocket.close(code=4000)
        return

    # 4. Key pool & audio clients
    key_pool = get_shared_key_pool()
    flux_client = FluxSTTClient(
        key_pool=key_pool,
        model="flux-general-en",
        sample_rate=16000,
        encoding="linear16",
    )
    aura_client = AuraTTSClient(
        key_pool=key_pool,
        sample_rate=24000,
        encoding="linear16",
    )

    try:
        await flux_client.start()
        if hasattr(flux_client, "wait_until_ready"):
            await flux_client.wait_until_ready(timeout=10.0)
    except Exception as e:
        logger.error("Flux STT initialization failed for session %s: %s", session_id, e)
        await websocket.accept()
        await websocket.send_json({
            "type": "SessionError",
            "error": "STTInitializationFailed",
            "detail": "Failed to initialize audio transcription service.",
        })
        await websocket.close(code=4003)
        return

    # 5. Authorization & Flux readiness succeeded -> Now accept WebSocket!
    await websocket.accept()
    logger.info("Client connected to /ws/interview/%s (user=%s)", session_id, user_id)

    # 6. Clean up incumbent runner ONLY after authorization and connection success
    if session_id in ACTIVE_RUNNERS:
        old_runner = ACTIVE_RUNNERS.pop(session_id, None)
        if old_runner:
            try:
                await old_runner.stop()
            except Exception as e:
                logger.warning("Error stopping incumbent runner: %s", e)

    runner = SessionRunner(
        session_id=session_id,
        script=script,
        websocket=websocket,
        flux_client=flux_client,
        aura_client=aura_client,
    )
    ACTIVE_RUNNERS[session_id] = runner

    # Forward Flux events into runner queue
    async def _forward_flux_loop() -> None:
        try:
            async for ev in flux_client.stream_events():
                await runner.on_flux_event(ev)
        except (asyncio.CancelledError, Exception) as e:
            logger.debug("Flux event forwarding ended: %s", e)

    # Inform client of session metadata first
    await websocket.send_json({
        "type": "SessionConnected",
        "session_id": session_id,
        "question_count": len(script.get("questions", [])),
    })

    # Wait for explicit client_ready handshake event before starting greeting
    client_ready = False
    try:
        while not client_ready:
            msg = await asyncio.wait_for(websocket.receive(), timeout=15.0)
            if "text" in msg and msg["text"]:
                try:
                    payload = json.loads(msg["text"])
                except Exception:
                    continue
                if payload.get("type") == "client_ready":
                    client_ready = True
                    break
                elif payload.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "time": time.time()})
            elif "bytes" in msg and msg["bytes"]:
                # Drop candidate PCM before handshake completes
                pass
    except asyncio.TimeoutError:
        logger.warning("Session %s: client_ready timeout after 15s", session_id)
        await websocket.send_json({
            "type": "SessionError",
            "error": "HandshakeTimeout",
            "detail": "Client audio readiness handshake timed out.",
        })
        await flux_client.stop()
        await websocket.close(code=4008)
        ACTIVE_RUNNERS.pop(session_id, None)
        return

    # Notify client that handshake is complete
    await websocket.send_json({
        "type": "SessionReady",
        "session_id": session_id,
    })

    flux_task = asyncio.create_task(_forward_flux_loop())
    await runner.start()

    # 4. Inbound WebSocket message loop
    try:
        while True:
            message = await websocket.receive()

            # Binary mic PCM chunk (16kHz mono)
            if "bytes" in message and message["bytes"]:
                await runner.on_mic_audio(message["bytes"])

            # JSON control frame
            elif "text" in message and message["text"]:
                try:
                    payload = json.loads(message["text"])
                except Exception:
                    continue

                msg_type = payload.get("type", "")

                if msg_type == "playback_started":
                    speech_id = payload.get("speech_id", "")
                    await runner.on_playback_started(speech_id)

                elif msg_type == "playback_ended":
                    speech_id = payload.get("speech_id", "")
                    await runner.on_playback_ended(speech_id)

                elif msg_type == "ready_button":
                    await runner.on_ready_button()

                elif msg_type == "commit_button":
                    await runner.on_commit_button()

                elif msg_type == "repeat_button":
                    await runner.on_repeat_button()

                elif msg_type == "end_button":
                    req_id = payload.get("request_id")
                    await runner.on_end_button(request_id=req_id)

                elif msg_type == "restart_session":
                    from backend.app.services.interview_v2.runner import SESSION_STATE_CACHE
                    from backend.app.services.interview_v2.conductor import SessionStart, ConductorState
                    SESSION_STATE_CACHE.pop(session_id, None)
                    runner.state = ConductorState()
                    await runner.queue.put(SessionStart(session_id=session_id, plan=runner.script, now_ms=runner.now_ms()))

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong", "time": time.time()})

    except (WebSocketDisconnect, RuntimeError):
        logger.info("Interview WebSocket disconnected for session %s", session_id)
    except Exception as e:
        logger.error("Error in Interview WebSocket loop: %s", e)
    finally:
        flux_task.cancel()
        await flux_client.stop()
        await runner.stop()
        ACTIVE_RUNNERS.pop(session_id, None)


# -----------------------------------------------------------------------------
# Developer Page HTML (/dev/interview)
# -----------------------------------------------------------------------------

DEV_INTERVIEW_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Candidly AI - Autonomous Interview Conductor Cockpit</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    @keyframes pulse-subtle {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.75; }
    }
    .animate-pulse-subtle { animation: pulse-subtle 2s infinite ease-in-out; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased p-6">
  <div class="max-w-6xl mx-auto space-y-6">

    <!-- Header -->
    <header class="flex items-center justify-between border-b border-slate-800 pb-4">
      <div>
        <div class="flex items-center gap-3">
          <span id="connDot" class="h-3 w-3 rounded-full bg-slate-500"></span>
          <h1 class="text-2xl font-bold tracking-tight text-white">Interview Conductor Cockpit</h1>
          <span class="text-xs font-semibold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
            Phase 4: Fast Reply &middot; Autonomous Conductor &middot; Live Mic
          </span>
        </div>
        <p class="text-xs text-slate-400 mt-1">
          Pure Reducer &middot; AudioWorklet Half-Duplex &middot; Pre-Synthesized Bridges (0ms) &middot; Speculative Reaction Streaming
        </p>
      </div>
      <div class="flex items-center gap-3">
        <div class="flex items-center gap-2 bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5">
          <label for="sessionIdInput" class="text-xs font-medium text-slate-400">Session ID:</label>
          <input id="sessionIdInput" type="text" value="__SESSION_ID__" class="bg-slate-950 border border-slate-700 text-xs text-white rounded px-2 py-1 w-64 focus:outline-none focus:border-indigo-500 font-mono" />
          <button id="connectBtn" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium px-3 py-1 rounded transition">Connect</button>
          <button id="restartBtn" class="bg-rose-600/80 hover:bg-rose-500 text-white text-xs font-medium px-2.5 py-1 rounded transition" title="Wipe session state and restart from Question 0">Restart Fresh</button>
        </div>
      </div>
    </header>

    <!-- Phase & Status Banner -->
    <div class="grid grid-cols-4 gap-4">
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div class="text-[11px] font-medium uppercase tracking-wider text-slate-400">Phase</div>
        <div id="phaseDisplay" class="text-xl font-bold text-indigo-400 mt-1">INIT</div>
        <div id="skillDisplay" class="text-xs text-slate-500 mt-0.5">Awaiting start</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div class="text-[11px] font-medium uppercase tracking-wider text-slate-400">Status</div>
        <div id="statusDisplay" class="text-xl font-bold text-white mt-1">Disconnected</div>
        <div id="latencyDisplay" class="text-xs text-emerald-400 mt-0.5">p50: -- ms | p90: -- ms</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div class="text-[11px] font-medium uppercase tracking-wider text-slate-400">Speculation & Bridge</div>
        <div id="specDisplay" class="text-xl font-bold text-sky-400 mt-1">Active</div>
        <div id="bridgeDisplay" class="text-xs text-slate-400 mt-0.5">8 Bridges Pre-Cached (0ms)</div>
      </div>
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div class="text-[11px] font-medium uppercase tracking-wider text-slate-400">Mic Energy</div>
        <div class="flex items-center gap-3 mt-2">
          <div class="flex-1 bg-slate-950 rounded-full h-3 overflow-hidden border border-slate-800">
            <div id="micMeter" class="bg-emerald-500 h-full w-0 transition-all duration-75"></div>
          </div>
          <span id="micDb" class="text-xs font-mono text-slate-400 w-10 text-right">0%</span>
        </div>
        <div class="text-[10px] text-slate-500 mt-1">16kHz Mono PCM16 AEC/NS/AGC</div>
      </div>
    </div>

    <!-- Active Question Card -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
      <div class="flex items-center justify-between pb-3 border-b border-slate-800">
        <span class="text-xs font-semibold text-indigo-400 uppercase tracking-wider">Active Conductor Question</span>
        <div class="flex items-center gap-2">
          <span id="turnCounterBadge" class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">Turn #0</span>
          <span id="botSpeakingBadge" class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400">Bot Idle</span>
        </div>
      </div>
      <div id="activeQuestionText" class="text-lg font-medium text-white mt-3 leading-relaxed">
        Click "Start Interview" or speak to begin.
      </div>
      <div class="mt-4 flex items-center justify-between">
        <div class="flex items-center gap-2 text-xs text-slate-400">
          <span>Candidate Speech:</span>
          <span id="candidateLiveText" class="text-slate-200 italic font-medium">--</span>
        </div>
        <!-- Manual Accelerator Controls (Hands-free is default, buttons optional) -->
        <div class="flex items-center gap-2">
          <button id="readyBtn" class="bg-emerald-700/80 hover:bg-emerald-600 text-white text-xs px-3 py-1 rounded transition">Ready Button</button>
          <button id="commitBtn" class="bg-indigo-700/80 hover:bg-indigo-600 text-white text-xs px-3 py-1 rounded transition">Commit Button</button>
          <button id="repeatBtn" class="bg-amber-700/80 hover:bg-amber-600 text-white text-xs px-3 py-1 rounded transition">Repeat Question</button>
          <button id="endBtn" class="bg-rose-700/80 hover:bg-rose-600 text-white text-xs px-3 py-1 rounded transition">End Interview</button>
        </div>
      </div>
    </div>

    <!-- Per-Turn Latency Waterfall Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div class="flex items-center justify-between pb-3 border-b border-slate-800">
        <div>
          <h2 class="text-sm font-semibold text-white">Per-Turn Latency Log</h2>
          <p class="text-xs text-slate-400">Detailed waterfall: Last Voiced &rarr; EOT &rarr; Commit &rarr; LLM TTFT &rarr; TTS Byte &rarr; Bot Audio</p>
        </div>
        <div id="summaryStats" class="text-xs font-mono text-emerald-400">
          p50: -- ms | p90: -- ms | Target: &le; 1500 ms
        </div>
      </div>
      <div class="mt-3 overflow-x-auto">
        <table class="w-full text-left text-xs font-mono">
          <thead>
            <tr class="text-slate-400 border-b border-slate-800">
              <th class="py-2 px-3">#</th>
              <th class="py-2 px-3">Question</th>
              <th class="py-2 px-3 text-right text-sky-400">Flux Wait</th>
              <th class="py-2 px-3 text-right">Voiced &rarr; Audio</th>
              <th class="py-2 px-3 text-right">Commit &rarr; Audio</th>
              <th class="py-2 px-3 text-right">LLM TTFT</th>
              <th class="py-2 px-3 text-right">TTS First Byte</th>
              <th class="py-2 px-3 text-center">Bridge</th>
              <th class="py-2 px-3 text-center">Speculation</th>
            </tr>
          </thead>
          <tbody id="latencyTableBody" class="divide-y divide-slate-800/60 text-slate-300">
            <tr>
              <td colspan="9" class="py-4 text-center text-slate-500 italic">No turns completed yet. Connect and speak to generate real latency data.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <script>
    let ws = null;
    let audioCtx = null;
    let micStream = null;
    let captureWorklet = null;
    let playbackWorklet = null;

    const latencies = [];

    const connDot = document.getElementById('connDot');
    const phaseDisplay = document.getElementById('phaseDisplay');
    const skillDisplay = document.getElementById('skillDisplay');
    const statusDisplay = document.getElementById('statusDisplay');
    const latencyDisplay = document.getElementById('latencyDisplay');
    const activeQuestionText = document.getElementById('activeQuestionText');
    const candidateLiveText = document.getElementById('candidateLiveText');
    const turnCounterBadge = document.getElementById('turnCounterBadge');
    const botSpeakingBadge = document.getElementById('botSpeakingBadge');
    const micMeter = document.getElementById('micMeter');
    const micDb = document.getElementById('micDb');
    const latencyTableBody = document.getElementById('latencyTableBody');
    const summaryStats = document.getElementById('summaryStats');
    const connectBtn = document.getElementById('connectBtn');
    const sessionIdInput = document.getElementById('sessionIdInput');

    async function initAudio() {
      if (audioCtx) {
        if (audioCtx.state === 'suspended') await audioCtx.resume();
        return;
      }
      audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
      if (audioCtx.state === 'suspended') {
        await audioCtx.resume();
      }

      // Inline Capture AudioWorklet (16kHz PCM16, AEC/NS/AGC, 30ms = 480 samples buffer)
      const captureCode = `
        class CaptureProcessor extends AudioWorkletProcessor {
          constructor() {
            super();
            this.buffer = new Int16Array(480);
            this.bufferIdx = 0;
          }
          process(inputs) {
            const input = inputs[0];
            if (!input || !input[0]) return true;
            const channel = input[0];
            
            // Downsample from Context (24k) to 16k
            const ratio = 16000 / sampleRate;
            const outLength = Math.floor(channel.length * ratio);
            for (let i = 0; i < outLength; i++) {
              const srcIdx = Math.floor(i / ratio);
              const s = Math.max(-1, Math.min(1, channel[srcIdx]));
              const val = s < 0 ? s * 0x8000 : s * 0x7FFF;
              this.buffer[this.bufferIdx++] = val;
              if (this.bufferIdx >= 480) { // 30ms @ 16kHz = 480 samples = 960 bytes
                const chunk = this.buffer.slice(0, 480);
                this.port.postMessage(chunk.buffer, [chunk.buffer]);
                this.bufferIdx = 0;
              }
            }
            return true;
          }
        }
        registerProcessor('capture-processor', CaptureProcessor);
      `;
      const captureBlob = new Blob([captureCode], { type: 'application/javascript' });
      await audioCtx.audioWorklet.addModule(URL.createObjectURL(captureBlob));

      // Inline Playback AudioWorklet (24kHz Ring Buffer)
      const playbackCode = `
        class PlaybackProcessor extends AudioWorkletProcessor {
          constructor() {
            super();
            this.ring = new Float32Array(24000 * 10);
            this.writeIdx = 0;
            this.readIdx = 0;
            this.hasStarted = false;
            this.currentSpeechId = null;

            this.port.onmessage = (e) => {
              const { type, speechId, pcm16 } = e.data;
              if (type === 'chunk' && pcm16) {
                const arr = new Int16Array(pcm16);
                for (let i = 0; i < arr.length; i++) {
                  this.ring[this.writeIdx % this.ring.length] = arr[i] / 32768.0;
                  this.writeIdx++;
                }
                if (speechId) this.currentSpeechId = speechId;
              } else if (type === 'flush') {
                this.readIdx = this.writeIdx;
                this.hasStarted = false;
              }
            };
          }
          process(inputs, outputs) {
            const out = outputs[0][0];
            const buffered = this.writeIdx - this.readIdx;

            if (!this.hasStarted && buffered >= 3600) { // 150ms buffer
              this.hasStarted = true;
              this.port.postMessage({ type: 'playback_started', speechId: this.currentSpeechId });
            }

            if (this.hasStarted && buffered > 0) {
              for (let i = 0; i < out.length; i++) {
                if (this.readIdx < this.writeIdx) {
                  out[i] = this.ring[this.readIdx % this.ring.length];
                  this.readIdx++;
                } else {
                  out[i] = 0;
                }
              }
              if (this.readIdx >= this.writeIdx) {
                this.hasStarted = false;
                this.port.postMessage({ type: 'playback_ended', speechId: this.currentSpeechId });
              }
            } else {
              out.fill(0);
            }
            return true;
          }
        }
        registerProcessor('playback-processor', PlaybackProcessor);
      `;
      const playbackBlob = new Blob([playbackCode], { type: 'application/javascript' });
      await audioCtx.audioWorklet.addModule(URL.createObjectURL(playbackBlob));

      // Mic stream
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        }
      });

      const micSource = audioCtx.createMediaStreamSource(micStream);
      captureWorklet = new AudioWorkletNode(audioCtx, 'capture-processor');
      playbackWorklet = new AudioWorkletNode(audioCtx, 'playback-processor');

      micSource.connect(captureWorklet);
      playbackWorklet.connect(audioCtx.destination);

      captureWorklet.port.onmessage = (e) => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(e.data);
          // Energy Meter (scaled for natural voice levels)
          const arr = new Int16Array(e.data);
          let sum = 0;
          for (let i = 0; i < arr.length; i++) sum += Math.abs(arr[i]);
          const avg = sum / arr.length;
          const pct = Math.min(100, Math.round((avg / 1200) * 100));
          micMeter.style.width = pct + '%';
          micDb.innerText = pct + '%';
        }
      };

      playbackWorklet.port.onmessage = (e) => {
        const { type, speechId } = e.data;
        if (ws && ws.readyState === WebSocket.OPEN) {
          if (type === 'playback_started') {
            botSpeakingBadge.innerText = 'Bot Speaking';
            botSpeakingBadge.className = 'text-xs px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-semibold';
            ws.send(JSON.stringify({ type: 'playback_started', speech_id: speechId || 'speech_welcome' }));
          } else if (type === 'playback_ended') {
            botSpeakingBadge.innerText = 'Bot Idle';
            botSpeakingBadge.className = 'text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400';
            ws.send(JSON.stringify({ type: 'playback_ended', speech_id: speechId || 'speech_welcome' }));
          }
        }
      };
    }

    let currentSpeechId = null;

    function connect() {
      const sessionId = sessionIdInput.value.trim();
      if (!sessionId) return;

      if (ws) ws.close();

      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${proto}//${window.location.host}/ws/interview/${sessionId}`;
      ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';

      ws.onopen = async () => {
        connDot.className = 'h-3 w-3 rounded-full bg-emerald-500 animate-pulse';
        statusDisplay.innerText = 'Connected';
        statusDisplay.className = 'text-xl font-bold text-emerald-400 mt-1';
        connectBtn.disabled = false;
        connectBtn.innerText = 'Disconnect';
        if (audioCtx && audioCtx.state === 'suspended') {
          await audioCtx.resume();
        }
        ws.send(JSON.stringify({ type: 'client_ready', sample_rate: audioCtx ? audioCtx.sampleRate : 24000 }));
      };

      ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          // TTS 24kHz audio chunk
          if (playbackWorklet) {
            playbackWorklet.port.postMessage({
              type: 'chunk',
              speechId: currentSpeechId || 'speech_welcome',
              pcm16: event.data,
            }, [event.data]);
          }
          return;
        }

        try {
          const msg = JSON.parse(event.data);

          if (msg.type === 'UIStatus') {
            phaseDisplay.innerText = msg.phase.toUpperCase();
            if (msg.payload && msg.payload.question_text) {
              activeQuestionText.innerText = msg.payload.question_text;
            }
            if (msg.payload && msg.payload.skill) {
              skillDisplay.innerText = msg.payload.skill;
            }
          } else if (msg.type === 'TTSStarted') {
            currentSpeechId = msg.speech_id;
            botSpeakingBadge.innerText = 'Bot Speaking';
            botSpeakingBadge.className = 'text-xs px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-semibold';
            if (msg.text) activeQuestionText.innerText = msg.text;
          } else if (msg.type === 'TTSCancelled') {
            if (playbackWorklet) playbackWorklet.port.postMessage({ type: 'flush' });
          } else if (msg.type === 'TurnMetrics') {
            recordTurnMetrics(msg.metrics);
          } else if (msg.type === 'Update') {
            candidateLiveText.innerText = msg.text || '--';
          }
        } catch (e) {
          console.error('Error handling WS message:', e);
        }
      };

      ws.onclose = () => {
        connDot.className = 'h-3 w-3 rounded-full bg-slate-500';
        statusDisplay.innerText = 'Disconnected';
        statusDisplay.className = 'text-xl font-bold text-white mt-1';
        connectBtn.disabled = false;
        connectBtn.innerText = 'Connect';
      };
    }

    function recordTurnMetrics(m) {
      latencies.push(m.voiced_to_audio_ms);
      latencies.sort((a, b) => a - b);
      const p50 = latencies[Math.floor(latencies.length * 0.5)];
      const p90 = latencies[Math.floor(latencies.length * 0.9)];

      latencyDisplay.innerText = `p50: ${p50} ms | p90: ${p90} ms`;
      summaryStats.innerText = `p50: ${p50} ms | p90: ${p90} ms | Target: ≤ 1500 ms`;
      turnCounterBadge.innerText = `Turn #${m.turn_index}`;

      const row = document.createElement('tr');
      row.className = 'hover:bg-slate-800/40 transition';
      const specLabel = m.speculation_used ? 'USED' : m.speculation_discarded ? (m.speculation_discard_reason === 'text_mismatch' ? 'DISCARD (TEXT)' : 'DISCARD (1.2s)') : 'NONE';
      row.innerHTML = `
        <td class="py-2.5 px-3 font-semibold text-slate-400">${m.turn_index}</td>
        <td class="py-2.5 px-3 text-white max-w-xs truncate">${m.question_text}</td>
        <td class="py-2.5 px-3 text-right font-mono text-sky-300">${m.flux_wait_ms !== null && m.flux_wait_ms !== undefined ? m.flux_wait_ms + ' ms' : '--'}</td>
        <td class="py-2.5 px-3 text-right font-bold ${m.voiced_to_audio_ms <= 1500 ? 'text-emerald-400' : 'text-amber-400'}">${m.voiced_to_audio_ms} ms</td>
        <td class="py-2.5 px-3 text-right text-slate-300">${m.commit_to_audio_ms} ms</td>
        <td class="py-2.5 px-3 text-right text-slate-400">${m.llm_ttft_ms !== null ? m.llm_ttft_ms + ' ms' : '--'}</td>
        <td class="py-2.5 px-3 text-right text-slate-400">${m.first_tts_ms !== null ? m.first_tts_ms + ' ms' : '--'}</td>
        <td class="py-2.5 px-3 text-center"><span class="px-1.5 py-0.5 rounded text-[10px] ${m.used_bridge ? 'bg-amber-500/20 text-amber-300' : 'bg-slate-800 text-slate-500'}">${m.used_bridge ? 'YES' : 'NO'}</span></td>
        <td class="py-2.5 px-3 text-center"><span class="px-1.5 py-0.5 rounded text-[10px] ${m.speculation_used ? 'bg-emerald-500/20 text-emerald-300' : m.speculation_discarded ? 'bg-rose-500/20 text-rose-300' : 'bg-slate-800 text-slate-500'}">${specLabel}</span></td>
      `;

      if (latencyTableBody.querySelector('td[colspan]')) {
        latencyTableBody.innerHTML = '';
      }
      latencyTableBody.prepend(row);
    }

    connectBtn.onclick = async () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
      } else {
        connectBtn.disabled = true;
        connectBtn.innerText = 'Starting...';
        try {
          await initAudio();
          connect();
        } catch (err) {
          console.error('Audio initialization error:', err);
          alert('Microphone or Audio Initialization failed: ' + (err.message || err));
          connectBtn.disabled = false;
          connectBtn.innerText = 'Connect';
        }
      }
    };

    window.addEventListener('click', () => {
      if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
    });

    document.getElementById('readyBtn').onclick = () => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ready_button' }));
    };
    document.getElementById('restartBtn').onclick = () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'restart_session' }));
      }
    };
    document.getElementById('commitBtn').onclick = () => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'commit_button' }));
    };
    document.getElementById('repeatBtn').onclick = () => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'repeat_button' }));
    };
    document.getElementById('endBtn').onclick = () => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'end_button' }));
    };
  </script>
</body>
</html>
"""
