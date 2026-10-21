"""Deepgram Aura-2 WebSocket Text-to-Speech Client.

Provides an async streaming TTS client for:
    wss://api.deepgram.com/v1/speak?model={voice}&encoding=linear16&sample_rate=24000

Features:
- Voice configurable from environment (`AURA_VOICE` or `DEEPGRAM_AURA_VOICE`, default: `aura-2-thalia-en`).
- `speak(text) -> AsyncIterator[bytes]`: yields raw PCM16 24k audio chunks.
- `cancel()` support: sends `{"type": "Clear"}` over WebSocket and aborts current stream.
- Timing metrics: records Time-to-First-Byte / First-Audio latency (`first_audio_ms`).
- Key pool rotation on 402/429.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Dict, Optional

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from backend.app.services.voice.flux_stt import DeepgramKeyPool, get_shared_key_pool, get_ssl_context

logger = logging.getLogger("candidly.voice.aura_tts")


class AuraTTSClient:
    """Async streaming client for Deepgram Aura-2 WebSocket TTS."""

    def __init__(
        self,
        key_pool: Optional[DeepgramKeyPool] = None,
        voice: Optional[str] = None,
        sample_rate: int = 24000,
        encoding: str = "linear16",
    ) -> None:
        self.key_pool = key_pool or get_shared_key_pool()
        self.voice = voice or os.getenv("AURA_VOICE") or os.getenv("DEEPGRAM_AURA_VOICE", "aura-2-thalia-en")
        self.sample_rate = sample_rate
        self.encoding = encoding

        self.last_first_audio_ms: Optional[float] = None
        self.last_total_duration_ms: Optional[float] = None
        self.last_audio_bytes: int = 0

        self._ws: Optional[Any] = None
        self._ws_lock = asyncio.Lock()
        self._active_speak_lock = asyncio.Lock()
        self._is_speaking = False
        self._cancel_requested = False

    def _build_url(self) -> str:
        return (
            f"wss://api.deepgram.com/v1/speak?"
            f"model={self.voice}&"
            f"encoding={self.encoding}&"
            f"sample_rate={self.sample_rate}"
        )

    async def _ensure_connected(self) -> Any:
        """Connect or reconnect to the Deepgram Aura-2 WebSocket endpoint."""
        if self._ws is not None:
            try:
                state = getattr(self._ws, "state", None)
                if state is not None and getattr(state, "name", "") == "OPEN" and not getattr(self._ws, "closed", False):
                    return self._ws
            except Exception:
                pass
            self._ws = None

        ssl_ctx = get_ssl_context()
        url = self._build_url()

        for attempt in range(max(1, self.key_pool.key_count)):
            current_key = await self.key_pool.get_current_key()
            headers = {"Authorization": f"Token {current_key}"}
            try:
                logger.info("Connecting to Deepgram Aura-2 WS (%s..., voice=%s)", current_key[:8], self.voice)
                ws = await websockets.connect(
                    url,
                    additional_headers=headers,
                    ssl=ssl_ctx,
                    open_timeout=8.0,
                )
                self._ws = ws
                return ws
            except InvalidStatus as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                logger.warning("Aura-2 HTTP status error: %s (status %s)", exc, status_code)
                if status_code in (402, 429) or "402" in str(exc) or "429" in str(exc):
                    await self.key_pool.rotate(
                        failed_key=current_key,
                        reason=f"Aura-2 connect HTTP {status_code or exc}",
                    )
                else:
                    raise
            except Exception as exc:
                err_str = str(exc)
                if "402" in err_str or "429" in err_str:
                    await self.key_pool.rotate(
                        failed_key=current_key,
                        reason=f"Aura-2 error {err_str}",
                    )
                else:
                    logger.error("Failed connecting to Aura-2 WS: %s", exc)
                    raise

        raise RuntimeError("Failed to connect to Deepgram Aura-2 with available keys.")

    async def speak(self, text: str) -> AsyncIterator[bytes]:
        """Synthesize text to raw PCM16 24k audio chunks.

        Yields binary chunks as they arrive.
        Measures `first_audio_ms` on the first chunk.
        """
        clean_text = (text or "").strip()
        if not clean_text:
            return

        async with self._active_speak_lock:
            self._cancel_requested = False
            self._is_speaking = True
            self.last_first_audio_ms = None
            self.last_audio_bytes = 0
            t_start = time.perf_counter()

            try:
                for attempt in range(2):
                    if self._cancel_requested:
                        break

                    ws = await self._ensure_connected()
                    t_utterance_start = time.perf_counter()

                    try:
                        # 1. Send Speak text command
                        await ws.send(json.dumps({"type": "Speak", "text": clean_text}))
                        # 2. Send Flush command to finalize current utterance
                        await ws.send(json.dumps({"type": "Flush"}))
                    except (ConnectionClosed, Exception) as exc:
                        logger.warning("Failed sending text to Aura WS: %s, reconnecting...", exc)
                        self._ws = None
                        if attempt == 0:
                            continue
                        break

                    first_chunk_received = False
                    stream_failed = False

                    while True:
                        if self._cancel_requested:
                            logger.info("Aura-2 speak cancelled by user")
                            break

                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=8.0)
                        except asyncio.TimeoutError:
                            logger.warning("Timeout waiting for Aura-2 audio chunk (attempt %d)", attempt + 1)
                            self._ws = None
                            stream_failed = True
                            break
                        except ConnectionClosed:
                            self._ws = None
                            stream_failed = True
                            break

                        if isinstance(msg, bytes):
                            if not first_chunk_received:
                                first_chunk_received = True
                                self.last_first_audio_ms = (time.perf_counter() - t_utterance_start) * 1000.0
                                logger.info(
                                    "Aura-2 first audio metric: %.2fms (voice=%s)",
                                    self.last_first_audio_ms,
                                    self.voice,
                                )

                            self.last_audio_bytes += len(msg)
                            yield msg

                        else:
                            try:
                                ctrl = json.loads(msg)
                            except Exception:
                                continue

                            ctrl_type = ctrl.get("type")
                            if ctrl_type == "Flushed":
                                break
                            elif ctrl_type == "Cleared":
                                break
                            elif ctrl_type == "Error":
                                logger.error("Aura-2 error message from server: %s", ctrl)
                                break

                    # If audio was yielded or utterance completed normally, stop retry loop
                    if first_chunk_received or not stream_failed:
                        break
                    logger.warning("Aura-2 produced no audio on attempt %d, retrying...", attempt + 1)

            finally:
                self._is_speaking = False
                self.last_total_duration_ms = (time.perf_counter() - t_start) * 1000.0

    async def cancel(self) -> None:
        """Cancel active synthesis by sending Clear to Deepgram and aborting generation."""
        self._cancel_requested = True
        if self._ws is not None and self._is_speaking:
            try:
                await self._ws.send(json.dumps({"type": "Clear"}))
                logger.info("Sent Clear signal to Deepgram Aura-2 WS")
            except Exception as e:
                logger.warning("Failed to send Clear to Aura-2 WS: %s", e)

    @property
    def metrics(self) -> Dict[str, Any]:
        """Return timing metrics from the last synthesis invocation."""
        return {
            "first_audio_ms": self.last_first_audio_ms,
            "total_duration_ms": self.last_total_duration_ms,
            "audio_bytes": self.last_audio_bytes,
            "voice": self.voice,
            "sample_rate": self.sample_rate,
        }

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
