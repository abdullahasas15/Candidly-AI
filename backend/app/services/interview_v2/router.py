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
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.database import AsyncSessionLocal
from backend.app.models import InterviewSession
from backend.app.services.auth import decode_access_token
from backend.app.services.interview_v2.conductor import ConductorPhase
from backend.app.services.interview_v2.finalizer import finalize_interview_session
from backend.app.services.ws_ticket_store import consume_ws_ticket
from backend.app.services.interview_v2.runner import (
    SESSION_STATE_CACHE,
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

# Pending disconnect grace tasks: session_id -> asyncio.Task
PENDING_DISCONNECT_TASKS: Dict[str, asyncio.Task] = {}


@router.on_event("startup")
async def _on_startup() -> None:
    """Pre-synthesize the 8 bridge clips into memory at startup and verify director model."""
    try:
        from backend.app.services.interview_v2.director import verify_director_model
        verify_director_model()
    except Exception as e:
        logger.warning("Director model verification failed at startup: %s", e)
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
) -> None:
    """WebSocket endpoint connecting client audio worklet to the Interview v2 SessionRunner."""
    # 1. Extract and cryptographically validate ticket claims BEFORE accept
    auth_ticket = ticket
    if not auth_ticket:
        headers = getattr(websocket, "headers", {})
        auth_header = headers.get("authorization") if hasattr(headers, "get") else None
        if auth_header and auth_header.startswith("Bearer "):
            auth_ticket = auth_header.split(" ")[1]

    allow_dev = (
        os.getenv("ALLOW_DEV_WS_AUTH", "false").lower() == "true"
        and os.getenv("ENV") in ("development", "dev", "test")
    )
    claims = None
    if auth_ticket:
        if allow_dev and auth_ticket in ("dev", "test", "dev-token"):
            claims = {"sub": "dev-user", "role": "dev", "session_id": session_id, "type": "ws_ticket"}
        else:
            try:
                decoded = decode_access_token(auth_ticket)
                # Enforce ws_ticket type, session binding, and user claims
                if (
                    decoded.get("type") == "ws_ticket"
                    and decoded.get("session_id") == session_id
                    and (decoded.get("sub") or decoded.get("id"))
                    and decoded.get("role")
                ):
                    claims = decoded
                else:
                    logger.warning("Ticket rejected: invalid type or session mismatch for %s", session_id)
            except Exception as e:
                logger.warning("Invalid WS ticket for session %s: %s", session_id, e)
                claims = None
    elif allow_dev:
        claims = {"sub": "dev-user", "role": "dev", "session_id": session_id, "type": "ws_ticket"}

    if not claims:
        logger.warning("Rejecting unauthenticated WS connection for session %s (no valid ticket)", session_id)
        # Reject at handshake before accept: produces HTTP 403 / close code 1006 in browser
        await websocket.close(code=4401, reason="Unauthorized: Missing or invalid ticket")
        return

    # 1b. Atomically consume the ticket in shared storage. The DB primary-key
    # constraint makes this single-use across workers, not just this process.
    dev_bypass = bool(allow_dev and (not auth_ticket or auth_ticket in ("dev", "test", "dev-token")))
    if not dev_bypass:
        try:
            consumed = await consume_ws_ticket(auth_ticket, claims)
        except Exception as exc:
            logger.exception("WebSocket ticket store unavailable for session %s: %s", session_id, exc)
            await websocket.close(code=1011, reason="Ticket store unavailable")
            return
        if not consumed:
            logger.warning("Rejecting replayed WebSocket ticket for session %s", session_id)
            await websocket.close(code=4401, reason="Unauthorized: Ticket already used")
            return

    # 2. Cancel any pending disconnect grace finalization for this session
    pending_disco = PENDING_DISCONNECT_TASKS.pop(session_id, None)
    if pending_disco and not pending_disco.done():
        logger.info("Session %s reconnected before disconnect grace expired; cancelling finalizer", session_id)
        pending_disco.cancel()

    # 3. Call accept() BEFORE loading session / checking ownership so terminal close frames reach client
    await websocket.accept()

    # 4. Exact origin check
    headers = getattr(websocket, "headers", {})
    origin = headers.get("origin") if hasattr(headers, "get") else None
    env = os.getenv("ENV", "development").lower()
    raw_allowed = os.getenv("ALLOWED_ORIGINS", "")

    if env == "production":
        allowed_list = [ao.strip() for ao in raw_allowed.split(",") if ao.strip()]
        if not allowed_list:
            logger.critical("ALLOWED_ORIGINS must be configured in production environment!")
            await websocket.send_json({
                "type": "SessionError",
                "error": "ServerConfigurationError",
                "detail": "Allowed origins not configured in production.",
            })
            await websocket.close(code=1011, reason="Server misconfigured")
            return
    else:
        default_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
        allowed_list = [ao.strip() for ao in raw_allowed.split(",") if ao.strip()] + default_origins

    if origin and not allow_dev:
        allowed_tuples = set()
        for ao in allowed_list:
            p = urlparse(ao)
            allowed_tuples.add((p.scheme, p.hostname, p.port))

        parsed_origin = urlparse(origin)
        origin_tuple = (parsed_origin.scheme, parsed_origin.hostname, parsed_origin.port)
        if origin_tuple not in allowed_tuples:
            logger.warning("Rejecting WS connection from disallowed origin %s (parsed=%s)", origin, origin_tuple)
            await websocket.send_json({
                "type": "SessionError",
                "error": "ForbiddenOrigin",
                "detail": f"Origin {origin} is not allowed.",
            })
            await websocket.close(code=4403, reason="Forbidden origin")
            return

    # 5. Full lifecycle wrapped in try/except/finally
    flux_client: Optional[FluxSTTClient] = None
    aura_client: Optional[AuraTTSClient] = None
    runner: Optional[SessionRunner] = None
    flux_task: Optional[asyncio.Task[None]] = None
    session: Optional[InterviewSession] = None

    try:
        # Load real session script from database with eager relationships
        session, script = await load_real_session_script(session_id)
        if not session:
            logger.warning("Session %s not found in database", session_id)
            await websocket.send_json({
                "type": "SessionError",
                "error": "SessionNotFound",
                "detail": f"Interview session {session_id} not found.",
            })
            await websocket.close(code=4004, reason="Session not found")
            return

        # 1. Ownership check: user must be candidate, recruiter, admin, or dev
        user_id = claims.get("sub") or claims.get("id")
        user_email = (claims.get("email") or "").lower()
        user_role = claims.get("role")

        is_dev = allow_dev and user_role == "dev"
        is_admin = user_role == "admin"
        is_candidate = (
            session.application
            and (
                getattr(session.application, "candidate_id", None) == user_id
                or (getattr(session.application, "email", None) and session.application.email.lower() == user_email)
            )
        )
        is_recruiter = (
            session.job
            and getattr(session.job, "recruiter_id", None) == user_id
        )

        if not (is_candidate or is_recruiter or is_admin or is_dev):
            logger.warning("User %s is not authorized for session %s", user_id, session_id)
            await websocket.send_json({
                "type": "SessionError",
                "error": "Forbidden",
                "detail": "User is not authorized for this session.",
            })
            await websocket.close(code=4403, reason="Forbidden: Not session owner")
            return

        # 2. Status validation (P1-1)
        if session.status == "completed":
            logger.info("Rejecting WS connection for already completed session %s", session_id)
            await websocket.send_json({
                "type": "SessionEnded",
                "session_id": session_id,
                "status": "completed",
                "detail": "Interview session is already completed.",
            })
            await websocket.close(code=1000, reason="Session already completed")
            return

        if session.status == "cancelled":
            logger.info("Rejecting WS connection for cancelled session %s", session_id)
            await websocket.send_json({
                "type": "SessionError",
                "error": "SessionCancelled",
                "detail": "Interview session has been cancelled.",
            })
            await websocket.close(code=4000, reason="Session cancelled")
            return

        if session.status == "scheduled" and not allow_dev:
            logger.warning("Session %s is in 'scheduled' status; client must call /start first", session_id)
            await websocket.send_json({
                "type": "SessionError",
                "error": "SessionNotStarted",
                "detail": "Interview session has not been started. Please start the interview via preflight first.",
            })
            await websocket.close(code=4000, reason="Session not started")
            return

        # 3. Validate session has questions configured
        if not script.get("questions"):
            logger.warning("Session %s has no questions in database", session_id)
            await websocket.send_json({
                "type": "SessionError",
                "error": "EmptySession",
                "detail": f"Interview session {session_id} has no questions configured.",
            })
            await websocket.close(code=4000)
            return

        # Load persisted conductor state if present
        db_conductor_state = (session.runtime_state or {}).get("conductor_v2") if isinstance(session.runtime_state, dict) else None

        # Key pool & audio clients
        key_pool = get_shared_key_pool()
        # Keyterm biasing materially improves Flux transcription accuracy on the
        # job's domain vocabulary (skills, blueprint terms). It existed for the
        # dev cockpit but was never wired into the production interview socket.
        session_keyterms: list[str] = []
        try:
            from backend.app.services.voice.gateway import get_session_keyterms
            session_keyterms = await get_session_keyterms(session_id)
        except Exception as kt_err:
            logger.warning("Could not load session keyterms for %s: %s", session_id, kt_err)
        flux_client = FluxSTTClient(
            key_pool=key_pool,
            model="flux-general-en",
            sample_rate=16000,
            encoding="linear16",
            keyterms=session_keyterms or None,
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
            await websocket.send_json({
                "type": "SessionError",
                "error": "STTInitializationFailed",
                "detail": "Failed to initialize audio transcription service.",
            })
            await websocket.close(code=4003)
            return

        # Clean up incumbent runner ONLY after authorization and connection success
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
            initial_db_state=db_conductor_state,
        )
        ACTIVE_RUNNERS[session_id] = runner

        logger.info("Client successfully initialized /ws/interview/%s (user=%s)", session_id, user_id)

        # Forward Flux events into runner queue with stream monitoring
        async def _forward_flux_loop() -> None:
            try:
                async for ev in flux_client.stream_events():
                    await runner.on_flux_event(ev)
            except (asyncio.CancelledError, Exception) as e:
                logger.debug("Flux event forwarding ended: %s", e)
                if runner and runner.running and runner.state.phase not in (ConductorPhase.COMPLETED, ConductorPhase.CLOSING):
                    try:
                        await websocket.send_json({
                            "type": "SessionError",
                            "error": "STTStreamDisconnected",
                            "detail": "Audio transcription stream disconnected.",
                            "retryable": True,
                        })
                    except Exception:
                        pass

        # Inform client of session metadata first
        await websocket.send_json({
            "type": "SessionConnected",
            "session_id": session_id,
            "question_count": len(script.get("questions", [])),
        })

        # Wait for explicit client_ready handshake event (60s timeout per P1-11)
        client_ready = False
        try:
            while not client_ready:
                msg = await asyncio.wait_for(websocket.receive(), timeout=60.0)
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
                    pass
        except asyncio.TimeoutError:
            logger.warning("Session %s: client_ready timeout after 60s", session_id)
            await websocket.send_json({
                "type": "SessionError",
                "error": "HandshakeTimeout",
                "detail": "Client audio readiness handshake timed out after 60 seconds.",
            })
            await websocket.close(code=4008)
            return

        # Notify client that handshake is complete
        await websocket.send_json({
            "type": "SessionReady",
            "session_id": session_id,
        })

        flux_task = asyncio.create_task(_forward_flux_loop())
        # Client presence gate: silence-ladder / commit-grace timers hold while
        # no client is connected so a disconnect never consumes a question.
        runner.client_connected = True
        await runner.start()

        # Inbound WebSocket message loop
        while True:
            message = await websocket.receive()

            if "bytes" in message and message["bytes"]:
                await runner.on_mic_audio(message["bytes"])

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
                    SESSION_STATE_CACHE.pop(session_id, None)
                    runner.state = ConductorState()
                    await runner.queue.put(SessionStart(session_id=session_id, plan=runner.script, now_ms=runner.now_ms()))

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong", "time": time.time()})

    except (WebSocketDisconnect, RuntimeError):
        logger.info("Interview WebSocket disconnected for session %s", session_id)
        if runner:
            runner.client_connected = False
    except Exception as e:
        logger.error("Error in Interview WebSocket lifecycle for %s: %s", session_id, e, exc_info=True)
        if runner:
            runner.client_connected = False
        try:
            await websocket.send_json({
                "type": "SessionError",
                "error": "InternalServerError",
                "detail": "Unexpected error in interview session.",
            })
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
    finally:
        # 1. Wait for in-flight finalization before stopping runner
        if runner:
            try:
                await runner.wait_for_in_flight_finalization(timeout=10.0)
            except Exception as e:
                logger.warning("Error waiting for in-flight finalization: %s", e)

        # 2. Cancel and await flux task
        if flux_task:
            flux_task.cancel()
            try:
                await flux_task
            except (asyncio.CancelledError, Exception):
                pass

        # 3. Stop Flux client
        if flux_client:
            try:
                await flux_client.stop()
            except Exception:
                pass

        # 4. Stop runner
        if runner:
            try:
                await runner.stop()
            except Exception:
                pass

        # 5. Close Aura client
        if aura_client:
            try:
                await aura_client.close()
            except Exception:
                pass

        # 6. Evict runner from active registry if this was the registered instance
        if ACTIVE_RUNNERS.get(session_id) is runner:
            ACTIVE_RUNNERS.pop(session_id, None)

        # 7. Disconnect grace finalizer for abandoned sessions (P1-2)
        # INIT is normally excluded because the runner has not started. However,
        # `/start` may already have moved the session to in_progress before a
        # handshake timeout, so an abandoned INIT session still needs cleanup.
        session_status = getattr(session, "status", None) if session else None
        should_finalize_abandoned = bool(
            runner
            and runner.state.phase != ConductorPhase.COMPLETED
            and (
                runner.state.phase != ConductorPhase.INIT
                or session_status in ("in_progress", "preflight", "paused")
            )
        )
        if should_finalize_abandoned:
            grace_seconds = float(os.getenv("INTERVIEW_DISCONNECT_GRACE_SECONDS", "120"))
            is_closing = runner.state.phase == ConductorPhase.CLOSING
            actual_grace = 5.0 if is_closing else grace_seconds

            async def _disco_finalizer(s_id: str, delay: float):
                try:
                    await asyncio.sleep(delay)
                    logger.info("Disconnect grace period (%.2fs) expired for session %s; finalizing", delay, s_id)
                    async with AsyncSessionLocal() as db:
                        await finalize_interview_session(s_id, ended_by="abandoned", db=db)
                    SESSION_STATE_CACHE.pop(s_id, None)
                except asyncio.CancelledError:
                    logger.debug("Disconnect grace cancelled for %s due to reconnect", s_id)
                except Exception as err:
                    logger.error("Failed to finalize disconnected session %s: %s", s_id, err)
                finally:
                    # A reconnect may have replaced this task with a newer one.
                    # Only remove the registry entry if it still belongs to us.
                    if PENDING_DISCONNECT_TASKS.get(s_id) is asyncio.current_task():
                        PENDING_DISCONNECT_TASKS.pop(s_id, None)

            old_task = PENDING_DISCONNECT_TASKS.pop(session_id, None)
            if old_task and not old_task.done():
                old_task.cancel()
            PENDING_DISCONNECT_TASKS[session_id] = asyncio.create_task(_disco_finalizer(session_id, actual_grace))


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
            this.isTtsDone = false;
            this.currentSpeechId = null;

            this.port.onmessage = (e) => {
              const { type, speechId, pcm16 } = e.data;
              if (type === 'chunk' && pcm16) {
                if (speechId && speechId !== this.currentSpeechId) {
                  this.currentSpeechId = speechId;
                  this.hasStarted = false;
                  this.isTtsDone = false;
                  this.readIdx = this.writeIdx;
                }
                const arr = new Int16Array(pcm16);
                for (let i = 0; i < arr.length; i++) {
                  this.ring[this.writeIdx % this.ring.length] = arr[i] / 32768.0;
                  this.writeIdx++;
                }
              } else if (type === 'tts_done') {
                this.isTtsDone = true;
                if (this.writeIdx - this.readIdx <= 0) {
                  this.hasStarted = false;
                  this.isTtsDone = false;
                  this.port.postMessage({ type: 'playback_ended', speechId: this.currentSpeechId });
                }
              } else if (type === 'flush') {
                this.readIdx = this.writeIdx;
                this.hasStarted = false;
                this.isTtsDone = false;
              }
            };
          }
          process(inputs, outputs) {
            const out = outputs[0][0];
            const buffered = this.writeIdx - this.readIdx;

            if (!this.hasStarted && (buffered >= 3600 || (this.isTtsDone && buffered > 0))) { // 150ms buffer or immediate if done
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
              if (this.readIdx >= this.writeIdx && this.isTtsDone) {
                this.hasStarted = false;
                this.isTtsDone = false;
                this.port.postMessage({ type: 'playback_ended', speechId: this.currentSpeechId });
              }
            } else {
              out.fill(0);
              if (this.hasStarted && this.isTtsDone && buffered <= 0) {
                this.hasStarted = false;
                this.isTtsDone = false;
                this.port.postMessage({ type: 'playback_ended', speechId: this.currentSpeechId });
              }
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
          } else if (msg.type === 'TTSDone') {
            if (playbackWorklet) playbackWorklet.port.postMessage({ type: 'tts_done', speechId: msg.speech_id || currentSpeechId });
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
