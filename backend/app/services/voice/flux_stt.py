"""Deepgram Flux v2 Conversational STT Client.

Provides an async streaming client for:
    wss://api.deepgram.com/v2/listen?model=flux-general-en&encoding=linear16&sample_rate=16000&eot_threshold=0.8&eot_timeout_ms=7000

Features:
- Emits typed events: StartOfTurn, Update(text), EndOfTurn(text, confidence, turn_index).
- Never merges or stitches text (verbatim model turn passthrough).
- Automatic KeepAlive management (sends KeepAlive frame during pauses).
- Reconnect with exponential backoff on network dropouts.
- Key pool of DEEPGRAM_API_KEYS with automatic rotation on 402/429.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import os
import random
import ssl
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set, Union
import urllib.parse

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

logger = logging.getLogger("candidly.voice.flux_stt")

# Defaults loaded from environment variables (0.85 / 6000ms default for 4-5s thinking pause tolerance)
DEFAULT_EOT_THRESHOLD = float(os.getenv("EOT_THRESHOLD", "0.85"))
DEFAULT_EOT_TIMEOUT_MS = int(os.getenv("EOT_TIMEOUT_MS", "6000"))
DEFAULT_EAGER_EOT_THRESHOLD = float(os.getenv("EAGER_EOT_THRESHOLD", "0.5"))


def get_ssl_context() -> ssl.SSLContext:
    """Return an SSL context configured with certifi if available."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


# -----------------------------------------------------------------------------
# Typed Events
# -----------------------------------------------------------------------------

@dataclass
class StartOfTurn:
    """Emitted when Flux detects the user began speaking."""
    transcript: str = ""
    turn_index: int = 0
    audio_window_start: float = 0.0
    audio_window_end: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Update:
    """Emitted for interim transcription hypotheses while user is speaking."""
    text: str
    turn_index: int = 0
    confidence: float = 0.0
    audio_window_start: float = 0.0
    audio_window_end: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EagerEndOfTurn:
    """Emitted when Flux indicates a high early probability of turn completion."""
    text: str
    turn_index: int = 0
    confidence: float = 0.0
    audio_window_start: float = 0.0
    audio_window_end: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnResumed:
    """Emitted when speech resumes after an EagerEndOfTurn before EndOfTurn."""
    text: str = ""
    turn_index: int = 0
    audio_window_start: float = 0.0
    audio_window_end: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


ResumedTurn = TurnResumed


@dataclass
class EndOfTurn:
    """Emitted when Flux determines the user finished speaking their turn."""
    text: str
    confidence: float
    turn_index: int
    trigger: str = "model"
    audio_window_start: float = 0.0
    audio_window_end: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


FluxEvent = Union[StartOfTurn, Update, EagerEndOfTurn, TurnResumed, EndOfTurn]


# -----------------------------------------------------------------------------
# Key Pool with 402/429 Rotation
# -----------------------------------------------------------------------------

class DeepgramKeyPool:
    """Thread/async safe pool for rotating Deepgram API keys on 402/429 errors."""

    def __init__(self, keys: Optional[List[str]] = None) -> None:
        self._keys: List[str] = []
        if keys:
            self._keys = [k.strip() for k in keys if k and k.strip()]
        else:
            self._load_from_env()

        self._current_idx: int = 0
        self._exhausted: Set[str] = set()
        self._lock = asyncio.Lock()

    def _load_from_env(self) -> None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except Exception:
            pass

        loaded: List[str] = []

        # 1. Check DEEPGRAM_API_KEYS (comma or JSON separated)
        raw_keys = os.getenv("DEEPGRAM_API_KEYS", "")
        if raw_keys:
            s = raw_keys.strip()
            if s.startswith("[") and s.endswith("]"):
                try:
                    loaded.extend(json.loads(s))
                except Exception:
                    loaded.extend(s.split(","))
            else:
                loaded.extend(s.split(","))

        # 2. Check individual key variables
        for var in [
            "DEEPGRAM_API_KEY",
            "DEEPGRAM_API_KEY1",
            "DEEPGRAM_API_KEY2",
            "DEEPGRAM_API_KEY3",
            "DEEPGRAM_KEY",
        ]:
            val = os.getenv(var)
            if val and val.strip():
                loaded.append(val.strip())

        # Deduplicate preserving order
        seen = set()
        deduped = []
        for k in loaded:
            cleaned = k.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                deduped.append(cleaned)
        self._keys = deduped

    @property
    def key_count(self) -> int:
        return len(self._keys)

    async def get_current_key(self) -> str:
        async with self._lock:
            if not self._keys:
                self._load_from_env()
            if not self._keys:
                raise ValueError(
                    "No Deepgram API keys found. Please set DEEPGRAM_API_KEY or DEEPGRAM_API_KEYS in .env."
                )
            return self._keys[self._current_idx]

    async def rotate(self, failed_key: Optional[str] = None, reason: str = "") -> str:
        async with self._lock:
            if not self._keys:
                raise ValueError("No Deepgram API keys configured.")

            current = self._keys[self._current_idx]
            target_failed = failed_key or current
            self._exhausted.add(target_failed)

            # Cycle to find next available unexhausted key
            for _ in range(len(self._keys)):
                self._current_idx = (self._current_idx + 1) % len(self._keys)
                candidate = self._keys[self._current_idx]
                if candidate not in self._exhausted:
                    logger.warning(
                        "Rotated Deepgram API key to index %d (%s...) due to: %s",
                        self._current_idx,
                        candidate[:8],
                        reason or "402/429 rate limit",
                    )
                    return candidate

            # All keys exhausted, reset exhaustion to allow retrying
            logger.warning(
                "All %d Deepgram API keys were marked exhausted. Resetting exhaustion set.",
                len(self._keys),
            )
            self._exhausted.clear()
            self._current_idx = (self._current_idx + 1) % len(self._keys)
            return self._keys[self._current_idx]


_shared_key_pool: Optional[DeepgramKeyPool] = None


def get_shared_key_pool() -> DeepgramKeyPool:
    global _shared_key_pool
    if _shared_key_pool is None:
        _shared_key_pool = DeepgramKeyPool()
    return _shared_key_pool


# -----------------------------------------------------------------------------
# Flux STT Client
# -----------------------------------------------------------------------------

class FluxSTTClient:
    """Async client streaming PCM16 16k audio to Deepgram Flux v2.

    Emits typed events without merging or stitching text.
    """

    def __init__(
        self,
        key_pool: Optional[DeepgramKeyPool] = None,
        model: str = "flux-general-en",
        sample_rate: int = 16000,
        encoding: str = "linear16",
        eot_threshold: Optional[float] = None,
        eot_timeout_ms: Optional[int] = None,
        eager_eot_threshold: Optional[float] = None,
        keyterms: Optional[List[str]] = None,
        on_event: Optional[Callable[[FluxEvent], Any]] = None,
    ) -> None:
        self.key_pool = key_pool or get_shared_key_pool()
        self.model = model
        self.sample_rate = sample_rate
        self.encoding = encoding
        self.eot_threshold = DEFAULT_EOT_THRESHOLD if eot_threshold is None else float(eot_threshold)
        self.eot_timeout_ms = DEFAULT_EOT_TIMEOUT_MS if eot_timeout_ms is None else int(eot_timeout_ms)
        self.eager_eot_threshold = DEFAULT_EAGER_EOT_THRESHOLD if eager_eot_threshold is None else float(eager_eot_threshold)
        self.keyterms: List[str] = list(keyterms) if keyterms else []
        self.on_event = on_event

        self._audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=1000)
        self._event_queue: asyncio.Queue[FluxEvent] = asyncio.Queue()

        self._ws: Optional[Any] = None
        self._running: bool = False
        self._connected: bool = False
        self._last_send_time: float = 0.0

        self._eager_eot_count: int = 0
        self._turn_resumed_count: int = 0
        self._eager_pending: bool = False
        self._bot_speaking: bool = False
        self._silence_task: Optional[asyncio.Task[None]] = None

        self._main_task: Optional[asyncio.Task[None]] = None
        self._send_task: Optional[asyncio.Task[None]] = None
        self._keepalive_task: Optional[asyncio.Task[None]] = None

    @property
    def eager_eot_count(self) -> int:
        return self._eager_eot_count

    @property
    def turn_resumed_count(self) -> int:
        return self._turn_resumed_count

    @property
    def bot_speaking(self) -> bool:
        return self._bot_speaking

    def set_bot_speaking(self, speaking: bool) -> None:
        """Toggle bot speaking state. While True, zero-filled PCM frames flow continuously to keep connection alive."""
        self._bot_speaking = speaking
        if speaking:
            if self._silence_task is None or self._silence_task.done():
                self._silence_task = asyncio.create_task(self._silence_loop())
        else:
            if self._silence_task and not self._silence_task.done():
                self._silence_task.cancel()
                self._silence_task = None

    async def _silence_loop(self) -> None:
        """Continuously push 30ms zero-filled PCM frames (960 bytes at 16kHz linear16) while bot is speaking."""
        zero_frame = b"\x00" * 960
        try:
            while self._running and self._bot_speaking:
                await self.send_audio(zero_frame)
                await asyncio.sleep(0.030)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Flux silence generator loop error: %s", e)

    def _build_url(self) -> str:
        params = [
            f"model={self.model}",
            f"encoding={self.encoding}",
            f"sample_rate={self.sample_rate}",
            f"eot_threshold={self.eot_threshold}",
            f"eot_timeout_ms={self.eot_timeout_ms}",
        ]
        if self.eager_eot_threshold is not None:
            params.append(f"eager_eot_threshold={self.eager_eot_threshold}")
        for term in self.keyterms:
            cleaned = term.strip()
            if cleaned:
                params.append(f"keyterm={urllib.parse.quote(cleaned)}")
        return f"wss://api.deepgram.com/v2/listen?{'&'.join(params)}"

    async def start(self) -> None:
        """Start the background connection and streaming tasks."""
        if self._running:
            return
        self._running = True
        self._main_task = asyncio.create_task(self._run_lifecycle())

    async def stop(self) -> None:
        """Stop streaming and close the connection cleanly."""
        self._running = False
        if self._silence_task and not self._silence_task.done():
            self._silence_task.cancel()
            self._silence_task = None
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Queue raw 16kHz linear16 PCM audio bytes for streaming."""
        if not self._running:
            return
        # If bot is speaking and incoming chunk contains non-zero data, zero-fill it
        if self._bot_speaking and any(pcm_bytes):
            pcm_bytes = b"\x00" * len(pcm_bytes)
        try:
            self._audio_queue.put_nowait(pcm_bytes)
        except asyncio.QueueFull:
            # Drop oldest audio chunk to avoid latency buildup
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._audio_queue.put_nowait(pcm_bytes)

    async def stream_events(self) -> AsyncIterator[FluxEvent]:
        """Async generator yielding incoming Flux events."""
        while self._running:
            try:
                event = await self._event_queue.get()
                yield event
            except asyncio.CancelledError:
                break

    async def _emit_event(self, event: FluxEvent) -> None:
        """Enqueue event and call on_event callback if registered."""
        await self._event_queue.put(event)
        if self.on_event:
            try:
                res = self.on_event(event)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error("Error in on_event callback: %s", e)

    async def _run_lifecycle(self) -> None:
        """Main connection supervisor with exponential backoff and 402/429 key rotation."""
        backoff = 0.5
        max_backoff = 10.0
        ssl_ctx = get_ssl_context()

        while self._running:
            current_key = await self.key_pool.get_current_key()
            url = self._build_url()
            headers = {"Authorization": f"Token {current_key}"}

            try:
                logger.info("Connecting to Deepgram Flux endpoint (%s...)", current_key[:8])
                async with websockets.connect(
                    url,
                    additional_headers=headers,
                    ssl=ssl_ctx,
                    open_timeout=8.0,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    backoff = 0.5  # Reset backoff on successful connect
                    logger.info("Deepgram Flux connection established.")

                    # Start sender and keepalive tasks
                    self._send_task = asyncio.create_task(self._send_loop(ws))
                    self._keepalive_task = asyncio.create_task(self._keepalive_loop(ws))

                    # Process incoming messages
                    await self._recv_loop(ws)

            except InvalidStatus as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                logger.warning("Deepgram connection HTTP error: %s (status %s)", exc, status_code)
                if status_code in (402, 429) or "402" in str(exc) or "429" in str(exc):
                    await self.key_pool.rotate(
                        failed_key=current_key,
                        reason=f"HTTP {status_code or exc}",
                    )
            except ConnectionClosed as exc:
                logger.info("Deepgram Flux connection closed: %s", exc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                err_str = str(exc)
                if "402" in err_str or "429" in err_str:
                    await self.key_pool.rotate(
                        failed_key=current_key,
                        reason=f"Exception status in {err_str}",
                    )
                logger.warning("Flux connection error: %s", exc)
            finally:
                self._connected = False
                if self._send_task and not self._send_task.done():
                    self._send_task.cancel()
                if self._keepalive_task and not self._keepalive_task.done():
                    self._keepalive_task.cancel()

            if not self._running:
                break

            jitter = random.uniform(0, 0.3)
            sleep_time = min(backoff + jitter, max_backoff)
            logger.info("Reconnecting to Flux in %.2fs...", sleep_time)
            await asyncio.sleep(sleep_time)
            backoff = min(backoff * 2.0, max_backoff)

    async def _send_loop(self, ws: Any) -> None:
        """Streams audio chunks from the queue into the WebSocket."""
        try:
            while self._running:
                chunk = await self._audio_queue.get()
                if chunk is None:
                    break
                await ws.send(chunk)
                self._last_send_time = time.monotonic()
        except (asyncio.CancelledError, ConnectionClosed):
            pass
        except Exception as e:
            logger.warning("Flux send error: %s", e)

    async def _keepalive_loop(self, ws: Any) -> None:
        """Periodically sends WebSocket protocol ping frames to keep connection alive."""
        try:
            while self._running:
                await asyncio.sleep(3.0)
                # If no audio sent for > 3.0s, send standard WS ping frame
                if time.monotonic() - self._last_send_time >= 3.0:
                    try:
                        pong_waiter = await ws.ping()
                        await asyncio.wait_for(pong_waiter, timeout=2.0)
                        self._last_send_time = time.monotonic()
                    except (asyncio.TimeoutError, ConnectionClosed):
                        break
        except (asyncio.CancelledError, ConnectionClosed):
            pass
        except Exception as e:
            logger.warning("Flux KeepAlive ping error: %s", e)

    async def _recv_loop(self, ws: Any) -> None:
        """Receives and dispatches Deepgram Flux messages."""
        while self._running:
            try:
                msg = await ws.recv()
            except ConnectionClosed:
                break

            if isinstance(msg, bytes):
                continue

            try:
                data = json.loads(msg)
            except Exception as e:
                logger.warning("Failed to decode Flux message JSON: %s", e)
                continue

            msg_type = data.get("type")
            event_name = data.get("event") or msg_type

            # Check for error frames with 402/429
            if msg_type == "Error":
                err_code = data.get("status_code") or data.get("code")
                logger.error("Flux server error payload: %s", data)
                if err_code in (402, 429):
                    current_key = await self.key_pool.get_current_key()
                    await self.key_pool.rotate(failed_key=current_key, reason=f"Deepgram Error {err_code}")
                    break

            if event_name == "StartOfTurn":
                event = StartOfTurn(
                    transcript=data.get("transcript", ""),
                    turn_index=data.get("turn_index", 0),
                    audio_window_start=data.get("audio_window_start", 0.0),
                    audio_window_end=data.get("audio_window_end", 0.0),
                    raw=data,
                )
                await self._emit_event(event)

            elif event_name == "Update":
                # Never merge or stitch: emit the raw hypothesis string
                event = Update(
                    text=data.get("transcript", ""),
                    turn_index=data.get("turn_index", 0),
                    confidence=data.get("end_of_turn_confidence", 0.0),
                    audio_window_start=data.get("audio_window_start", 0.0),
                    audio_window_end=data.get("audio_window_end", 0.0),
                    raw=data,
                )
                await self._emit_event(event)

            elif event_name == "EagerEndOfTurn":
                self._eager_eot_count += 1
                self._eager_pending = True
                raw_conf = data.get("end_of_turn_confidence", data.get("confidence", 0.0))
                try:
                    conf = float(raw_conf)
                except (TypeError, ValueError):
                    conf = 0.0
                logger.info(
                    "EagerEndOfTurn received (total_eager=%d, followed_by_resumed=%d): %s",
                    self._eager_eot_count,
                    self._turn_resumed_count,
                    data.get("transcript", ""),
                )
                event = EagerEndOfTurn(
                    text=data.get("transcript", ""),
                    turn_index=int(data.get("turn_index", 0)),
                    confidence=conf,
                    audio_window_start=float(data.get("audio_window_start", 0.0)),
                    audio_window_end=float(data.get("audio_window_end", 0.0)),
                    raw=data,
                )
                await self._emit_event(event)

            elif event_name in ("TurnResumed", "ResumedTurn"):
                if self._eager_pending:
                    self._turn_resumed_count += 1
                    self._eager_pending = False
                logger.info(
                    "TurnResumed received explicitly (resumed_count=%d, total_eager=%d)",
                    self._turn_resumed_count,
                    self._eager_eot_count,
                )
                event = TurnResumed(
                    text=data.get("transcript", ""),
                    turn_index=int(data.get("turn_index", 0)),
                    audio_window_start=float(data.get("audio_window_start", 0.0)),
                    audio_window_end=float(data.get("audio_window_end", 0.0)),
                    raw=data,
                )
                await self._emit_event(event)

            elif event_name == "EndOfTurn":
                self._eager_pending = False
                # Never merge or stitch: emit the full turn final transcript
                raw_conf = data.get("end_of_turn_confidence", data.get("confidence", 0.0))
                try:
                    conf = float(raw_conf)
                except (TypeError, ValueError):
                    conf = 0.0

                event = EndOfTurn(
                    text=data.get("transcript", ""),
                    confidence=conf,
                    turn_index=int(data.get("turn_index", 0)),
                    trigger=data.get("trigger", "model"),
                    audio_window_start=data.get("audio_window_start", 0.0),
                    audio_window_end=data.get("audio_window_end", 0.0),
                    raw=data,
                )
                await self._emit_event(event)
