"""Local Mac voice-pipeline integration for Candidly AI.

Stack components:
- Orchestration: Pipecat
- Transport: SmallWebRTCTransport (WebRTC via aiortc)
- VAD: Silero VAD (interview-tuned endpointing)
- End-of-turn detection: Smart Turn v3 (LocalSmartTurnAnalyzerV3)
- STT: Parakeet TDT 0.6B via parakeet-mlx (shared warm singleton)
- LLM: Gemini Live model (GEMINI_MODEL_LIVE)
- TTS: Kokoro-82M via mlx-audio (shared warm singleton + pre-synthesized phrase cache)
- Avatar: voqalize-avatar (AvatarProcessor) driving @voqalize/avatar
"""

import asyncio
import collections
import io
import os
import re
import threading
import time
import wave
from collections.abc import AsyncGenerator
from typing import Any, Callable, Optional, Tuple

import numpy as np
from loguru import logger

from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.aggregators.sentence import SentenceAggregator
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frameworks.rtvi.observer import RTVIObserver
from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_processor import UserTurnProcessor
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from backend.app.services.interview.followup_policy import ACK_POOL
from backend.app.services.question_generation.provider import (
    LIVE_MODEL_NAME,
    validate_configured_models,
)

try:
    from voqalize_avatar import AvatarProcessor
except ImportError:
    AvatarProcessor = None

GEMINI_MODEL_NAME = LIVE_MODEL_NAME

# Process-wide warm singletons & MLX lock (Apple Silicon GPU safety)
_MLX_LOCK = threading.Lock()
_SHARED_PARAKEET_MODEL: Any = None
_PARAKEET_LOAD_ATTEMPTED: bool = False
_SHARED_WHISPER_MODEL: Any = None
_WHISPER_LOAD_ATTEMPTED: bool = False
_SHARED_KOKORO_MODEL: Any = None
_KOKORO_LOAD_ATTEMPTED: bool = False
_SHARED_SMART_TURN: Optional[LocalSmartTurnAnalyzerV3] = None


def _load_whisper_singleton(model_name: str = "mlx-community/whisper-large-v3-turbo") -> Any:
    global _SHARED_WHISPER_MODEL, _WHISPER_LOAD_ATTEMPTED
    if os.getenv("VOICE_MOCK", "").lower() in {"1", "true", "yes"}:
        return None
    with _MLX_LOCK:
        if _SHARED_WHISPER_MODEL is not None or _WHISPER_LOAD_ATTEMPTED:
            return _SHARED_WHISPER_MODEL
        _WHISPER_LOAD_ATTEMPTED = True
        try:
            from mlx_audio.stt.utils import load_model
            t0 = time.perf_counter()
            logger.info(f"Loading Whisper Large v3 Turbo model: {model_name}...")
            _SHARED_WHISPER_MODEL = load_model(model_name)
            logger.info(f"Whisper loaded in {(time.perf_counter() - t0)*1000:.0f}ms")
        except Exception as e:
            logger.warning(f"Whisper model load deferred / fallback: {e}")
            _SHARED_WHISPER_MODEL = None
        return _SHARED_WHISPER_MODEL

# Pre-synthesized PCM audio cache: key = (normalized_text, round(speed, 2)) -> (pcm_bytes, sample_rate)
_STATIC_TTS_CACHE: dict[tuple[str, float], tuple[bytes, int]] = {}

STATIC_PREWARM_PHRASES: list[str] = [
    p for p in ACK_POOL if p
] + [
    "Of course, take a moment.",
    "No problem at all, let's move on.",
    "Take your time—whenever you're ready, feel free to share your thoughts.",
    "Would you like me to rephrase the question or approach it from a different angle?",
    "I'm not hearing any audio from your microphone. Please check if your mic is muted or select another input device.",
    "Welcome back! Let's pick up right where we left off.",
    "Thank you for sharing your background. Let's dive into our technical questions.",
    "Before we wrap up, do you have any questions for me about the role or team?",
]


def _load_parakeet_singleton(model_name: str = "mlx-community/parakeet-tdt-0.6b-v2") -> Any:
    global _SHARED_PARAKEET_MODEL, _PARAKEET_LOAD_ATTEMPTED
    if os.getenv("VOICE_MOCK", "").lower() in {"1", "true", "yes"}:
        return None
    with _MLX_LOCK:
        if _SHARED_PARAKEET_MODEL is not None or _PARAKEET_LOAD_ATTEMPTED:
            return _SHARED_PARAKEET_MODEL
        _PARAKEET_LOAD_ATTEMPTED = True
        try:
            import parakeet_mlx
            import mlx.core as mx
            from parakeet_mlx.audio import get_logmel

            t0 = time.perf_counter()
            logger.info(f"Loading Parakeet TDT model: {model_name}...")
            _SHARED_PARAKEET_MODEL = parakeet_mlx.from_pretrained(model_name)
            dummy = mx.array(np.zeros(8000, dtype=np.float32), dtype=mx.float32)
            mel = get_logmel(dummy, _SHARED_PARAKEET_MODEL.preprocessor_config)
            _SHARED_PARAKEET_MODEL.generate(mel)
            logger.info(f"Parakeet TDT loaded & dummy inference complete in {(time.perf_counter() - t0)*1000:.0f}ms")
        except Exception as e:
            logger.warning(f"Parakeet model load deferred / fallback: {e}")
            _SHARED_PARAKEET_MODEL = None
        return _SHARED_PARAKEET_MODEL


_SHARED_NEMOTRON_MODEL = None
_NEMOTRON_LOAD_ATTEMPTED = False


def _load_nemotron_singleton(
    model_name: str = "mlx-community/nemotron-3.5-asr-streaming-0.6b",
) -> Any:
    global _SHARED_NEMOTRON_MODEL, _NEMOTRON_LOAD_ATTEMPTED
    if os.getenv("VOICE_MOCK", "").lower() in {"1", "true", "yes"}:
        return None
    with _MLX_LOCK:
        if _SHARED_NEMOTRON_MODEL is not None or _NEMOTRON_LOAD_ATTEMPTED:
            return _SHARED_NEMOTRON_MODEL
        _NEMOTRON_LOAD_ATTEMPTED = True
        try:
            import mlx_audio.stt as stt
            t0 = time.perf_counter()
            logger.info(f"Loading Nemotron 3.5 Streaming ASR model: {model_name}...")
            _SHARED_NEMOTRON_MODEL = stt.load_model(model_name)
            logger.info(f"Nemotron 3.5 Streaming loaded in {(time.perf_counter() - t0)*1000:.0f}ms")
        except Exception as e:
            logger.warning(f"Nemotron streaming load deferred / fallback: {e}")
            _SHARED_NEMOTRON_MODEL = None
        return _SHARED_NEMOTRON_MODEL


def _load_kokoro_singleton(
    model_name: str = "mlx-community/Kokoro-82M-bf16",
    voice: str = "af_heart",
) -> Any:
    global _SHARED_KOKORO_MODEL, _KOKORO_LOAD_ATTEMPTED
    if os.getenv("VOICE_MOCK", "").lower() in {"1", "true", "yes"}:
        return None
    with _MLX_LOCK:
        if _SHARED_KOKORO_MODEL is not None or _KOKORO_LOAD_ATTEMPTED:
            return _SHARED_KOKORO_MODEL
        _KOKORO_LOAD_ATTEMPTED = True
        try:
            from mlx_audio.tts.utils import load_model
            import mlx.core as mx

            t0 = time.perf_counter()
            logger.info(f"Loading Kokoro TTS model: {model_name}...")
            _SHARED_KOKORO_MODEL = load_model(model_name)
            for seg in _SHARED_KOKORO_MODEL.generate(text="Ready.", voice=voice, speed=1.0):
                mx.eval(seg.audio)
            logger.info(f"Kokoro TTS loaded & dummy inference complete in {(time.perf_counter() - t0)*1000:.0f}ms")
        except Exception as e:
            logger.warning(f"Kokoro model load deferred / fallback: {e}")
            _SHARED_KOKORO_MODEL = None
        return _SHARED_KOKORO_MODEL


def synthesize_to_cache_sync(
    text: str,
    speed: float = 1.0,
    voice: str = "af_heart",
) -> Optional[tuple[bytes, int]]:
    """Pre-synthesize a phrase into `_STATIC_TTS_CACHE` so playback starts in <1ms."""
    clean = (text or "").strip()
    if not clean:
        return None
    key = (clean, round(float(speed), 2))
    if key in _STATIC_TTS_CACHE:
        return _STATIC_TTS_CACHE[key]

    if os.getenv("VOICE_MOCK", "").lower() in {"1", "true", "yes"}:
        sr = 24000
        samples = int(0.15 * sr)
        pcm = np.zeros(samples, dtype=np.int16).tobytes()
        _STATIC_TTS_CACHE[key] = (pcm, sr)
        return _STATIC_TTS_CACHE[key]

    model = _load_kokoro_singleton(voice=voice)
    if model is None:
        return None

    try:
        import mlx.core as mx

        chunks: list[bytes] = []
        sample_rate = 24000
        with _MLX_LOCK:
            for segment in model.generate(
                text=clean,
                voice=voice,
                speed=float(speed),
                split_pattern=r"(?<=[.!?])\s+",
            ):
                mx.eval(segment.audio)
                sample_rate = int(getattr(segment, "sample_rate", 24000) or 24000)
                audio_data = np.array(segment.audio, dtype=np.float32)
                audio_int16 = np.clip(audio_data * 32767.0, -32768, 32767).astype(np.int16)
                chunks.append(audio_int16.tobytes())
        if chunks:
            full_pcm = b"".join(chunks)
            _STATIC_TTS_CACHE[key] = (full_pcm, sample_rate)
            return _STATIC_TTS_CACHE[key]
    except Exception as exc:
        logger.debug(f"Pre-synthesis notice for '{clean[:30]}': {exc}")
    return None


async def pre_synthesize_phrase(text: str, speed: float = 1.0) -> bool:
    """Async helper to pre-render a greeting or static phrase into the TTS cache."""
    res = await asyncio.to_thread(synthesize_to_cache_sync, text, speed)
    return res is not None


async def warmup_voice_models(prewarm_static_phrases: bool = True) -> dict[str, Any]:
    """Warm up Parakeet STT, Kokoro TTS, Silero VAD, Smart Turn v3, and Gemini client at startup (Part A4)."""
    global _SHARED_SMART_TURN
    t_start = time.perf_counter()
    status: dict[str, Any] = {}

    # 1. Validate Gemini models & warm client
    model_check = await asyncio.to_thread(validate_configured_models)
    status["gemini_models"] = model_check

    # 2. Silero VAD + Smart Turn v3 dummy init
    try:
        vad = SileroVADAnalyzer(
            params=VADParams(confidence=0.75, start_secs=0.25, stop_secs=0.55, min_volume=0.55)
        )
        _SHARED_SMART_TURN = LocalSmartTurnAnalyzerV3()
        status["vad_and_smart_turn"] = "ready"
    except Exception as exc:
        status["vad_and_smart_turn"] = f"warning: {exc}"

    # 3. Parakeet STT + Kokoro TTS
    await asyncio.to_thread(_load_parakeet_singleton)
    await asyncio.to_thread(_load_kokoro_singleton)
    status["parakeet_loaded"] = _SHARED_PARAKEET_MODEL is not None
    status["kokoro_loaded"] = _SHARED_KOKORO_MODEL is not None

    # 4. Pre-synthesize static phrases (acks, nudges, closing)
    if prewarm_static_phrases and _SHARED_KOKORO_MODEL is not None:
        def _prewarm_phrases():
            count = 0
            for phrase in STATIC_PREWARM_PHRASES:
                if synthesize_to_cache_sync(phrase, speed=1.0) is not None:
                    count += 1
            return count

        cached_count = await asyncio.to_thread(_prewarm_phrases)
        status["cached_phrases"] = cached_count

    status["warmup_total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 1)
    logger.info(f"Voice pipeline warmup finished: {status}")
    return status


def clean_resample_16k_mono(raw_pcm: bytes, from_sample_rate: int) -> bytes:
    """Cleanly resample 16-bit PCM audio to 16kHz mono without chunk-boundary artifacts."""
    if not raw_pcm or from_sample_rate == 16000:
        return raw_pcm
    samples = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
    num_16k = int(len(samples) * 16000 / from_sample_rate)
    resampled = np.interp(
        np.linspace(0, len(samples), num_16k, endpoint=False),
        np.arange(len(samples)),
        samples,
    )
    return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()


def filter_hallucinations(text: str, audio_np: np.ndarray) -> str:
    """Filter ASR hallucinations on silence or repeated phrase loops."""
    clean = (text or "").strip()
    if not clean:
        return ""
    rms = float(np.sqrt(np.mean(np.square(audio_np)))) if len(audio_np) > 0 else 0.0
    if rms < 0.005:
        # RMS silence: suppress transcript
        return ""
    # Filter repeated n-grams (common hallucination on trailing silence)
    words = clean.split()
    if len(words) >= 4:
        for n in (1, 2, 3):
            chunks = [" ".join(words[i : i + n]).lower() for i in range(0, len(words) - n + 1, n)]
            if len(chunks) >= 3 and all(c == chunks[0] for c in chunks):
                return ""
    return clean


def is_acoustic_echo(candidate_text: str, last_ai_speech: str) -> bool:
    """Detect if candidate transcript is acoustic echo of bot's own speaker output."""
    c_clean = re.sub(r"[^\w\s]", "", (candidate_text or "").lower()).strip()
    a_clean = re.sub(r"[^\w\s]", "", (last_ai_speech or "").lower()).strip()
    if not c_clean or not a_clean:
        return False
    if c_clean in a_clean:
        return True
    c_words = set(c_clean.split())
    a_words = set(a_clean.split())
    if len(c_words) >= 3 and len(c_words.intersection(a_words)) / len(c_words) > 0.85:
        return True
    return False


class EventLoopLagMonitor:
    """Monitors asyncio event-loop lag to detect UI or frame processing stalls (Part 2)."""

    def __init__(self, sample_interval_s: float = 0.05, max_history: int = 100):
        self.sample_interval_s = sample_interval_s
        self.max_history = max_history
        self._samples: collections.deque[float] = collections.deque(maxlen=max_history)
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self.current_lag_ms: float = 0.0
        self.p95_lag_ms: float = 0.0
        self.max_lag_ms: float = 0.0

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        if self._running:
            return
        self._running = True
        try:
            loop = loop or asyncio.get_running_loop()
            self._task = loop.create_task(self._monitor_loop())
        except RuntimeError:
            pass

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _monitor_loop(self) -> None:
        while self._running:
            t0 = time.perf_counter()
            try:
                await asyncio.sleep(self.sample_interval_s)
            except asyncio.CancelledError:
                break
            elapsed = time.perf_counter() - t0
            lag = max(0.0, (elapsed - self.sample_interval_s) * 1000.0)
            self._samples.append(lag)
            self.current_lag_ms = lag
            if len(self._samples) >= 10:
                self.p95_lag_ms = float(np.percentile(list(self._samples), 95))
                self.max_lag_ms = float(max(self._samples))
                if self.p95_lag_ms > 50.0:
                    logger.warning(
                        f"EVENT LOOP LAG HIGH: p95={self.p95_lag_ms:.1f}ms, max={self.max_lag_ms:.1f}ms. "
                        f"Active tasks count={len(asyncio.all_tasks())}"
                    )

    def get_stats(self) -> dict[str, float]:
        return {
            "current_lag_ms": round(self.current_lag_ms, 2),
            "p95_lag_ms": round(self.p95_lag_ms, 2),
            "max_lag_ms": round(self.max_lag_ms, 2),
        }


class TwoLaneSTTService(SegmentedSTTService):
    """Two-Lane STT service for Candidly AI (Part 2):
    - Lane 1 (Interim): Fast streaming captions emitted every ~400ms while user speaks.
    - Lane 2 (Accuracy): Segmented ASR on VAD stop with 500ms pre-roll + 300ms post-roll.
      Uses Parakeet TDT 0.6B or Whisper Large v3 Turbo via MLX in background threads.
      Tags each segment with monotonic sequence ID `seq`.
      Includes RMS silence check, hallucination guard, and acoustic echo cancellation.
    """

    def __init__(
        self,
        *,
        model_name: str = "mlx-community/parakeet-tdt-0.6b-v2",
        sample_rate: int = 16000,
        trailing_silence_secs: float = 0.30,
        on_stt_interim: Optional[Callable[[str], None]] = None,
        on_stt_final: Optional[Callable[[str, float, Optional[float], int], None]] = None,
        session_trace: Optional[Any] = None,
        **kwargs,
    ):
        super().__init__(
            sample_rate=sample_rate,
            trailing_silence_secs=trailing_silence_secs,
            **kwargs,
        )
        self._model_name = model_name
        self._mock_mode = os.getenv("VOICE_MOCK", "").lower() in {"1", "true", "yes"}
        self._on_stt_interim = on_stt_interim
        self._on_stt_final = on_stt_final
        self._session_trace = session_trace

        # Models
        self._nemotron = _SHARED_NEMOTRON_MODEL
        self._parakeet = _SHARED_PARAKEET_MODEL
        self._whisper = _SHARED_WHISPER_MODEL

        # Echo gate & bot speaking tracking (R3.4b)
        self.is_bot_speaking: bool = False
        self._segment_started_while_bot_speaking: bool = False
        self._pre_flight_noise_floor: float = float(os.getenv("STT_NOISE_FLOOR", "0.005"))

        # Pre-roll circular frame buffer (500 ms @ 16kHz 16-bit mono = 16000 bytes)
        self._pre_roll_bytes = int(sample_rate * 2 * 0.50)
        self._pre_roll_buffer = bytearray()

        # Speech tracking & monotonic sequence
        self._segment_seq: int = 0
        self.last_stt_final_ms: Optional[float] = None
        self.last_stt_confidence: Optional[float] = None
        self.audio_segments_received: int = 0
        self.last_ai_speech: str = ""

        # Lane 1 interim task
        self._interim_task: Optional[asyncio.Task] = None
        self._interim_last_text: str = ""

    @property
    def wants_wav_segments(self) -> bool:
        return False

    def set_bot_speaking(self, is_speaking: bool) -> None:
        """Explicitly set bot speaking status for echo suppression gating."""
        self.is_bot_speaking = is_speaking

    def _ensure_models(self):
        if self._mock_mode:
            return
        if self._nemotron is None:
            self._nemotron = _load_nemotron_singleton()
        if self._parakeet is None:
            self._parakeet = _load_parakeet_singleton()
        if self._whisper is None:
            self._whisper = _load_whisper_singleton()

    async def process_frame(self, frame: Frame, direction: Any):
        # Track bot speaking status from pipeline frames
        if isinstance(frame, (TTSStartedFrame, BotStartedSpeakingFrame)):
            self.is_bot_speaking = True
        elif isinstance(frame, (TTSStoppedFrame, BotStoppedSpeakingFrame)):
            self.is_bot_speaking = False
        await super().process_frame(frame, direction)

    async def process_audio_frame(self, frame: InputAudioRawFrame, direction: Any):
        # Continuous circular pre-roll buffer when user is not speaking (500ms pre-roll)
        if not self._user_speaking:
            self._pre_roll_buffer += frame.audio
            if len(self._pre_roll_buffer) > self._pre_roll_bytes:
                discarded = len(self._pre_roll_buffer) - self._pre_roll_bytes
                self._pre_roll_buffer = self._pre_roll_buffer[discarded:]

        await super().process_audio_frame(frame, direction)

    async def _handle_user_started_speaking(self, frame: VADUserStartedSpeakingFrame):
        self._user_speaking = True
        # Gating rule (R3.4b): Record whether this speech segment began while bot was speaking
        self._segment_started_while_bot_speaking = self.is_bot_speaking
        # Prepend 500ms pre-roll audio so first syllable is never clipped
        if self._pre_roll_buffer:
            self._audio_buffer = bytearray(self._pre_roll_buffer) + self._audio_buffer
            self._pre_roll_buffer.clear()

        # Start Lane 1 periodic interim transcription
        if self._interim_task and not self._interim_task.done():
            self._interim_task.cancel()
        self._interim_task = asyncio.create_task(self._lane1_interim_loop())

    async def _handle_user_stopped_speaking(self, frame: VADUserStoppedSpeakingFrame):
        # Stop Lane 1
        if self._interim_task and not self._interim_task.done():
            self._interim_task.cancel()
            self._interim_task = None
        await super()._handle_user_stopped_speaking(frame)

    async def _lane1_interim_loop(self):
        """Lane 1: fast streaming captions every ~400ms for live visual feedback."""
        try:
            while self._user_speaking:
                await asyncio.sleep(0.40)
                if not self._user_speaking or len(self._audio_buffer) < 4800:
                    continue
                # Fast transcribe current speech buffer snapshot
                buf_snap = bytes(self._audio_buffer)
                audio_np = np.frombuffer(buf_snap, dtype=np.int16).astype(np.float32) / 32768.0
                if len(audio_np) > 1600:
                    text = await asyncio.to_thread(self._fast_transcribe, audio_np)
                    if text and text != self._interim_last_text:
                        self._interim_last_text = text
                        if self._on_stt_interim:
                            try:
                                self._on_stt_interim(text)
                            except Exception:
                                pass
                        if self._session_trace:
                            self._session_trace.log_stt(
                                lane="lane1_streaming",
                                text=text,
                                is_final=False,
                            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Lane 1 interim exception: {e}")

    def _fast_transcribe(self, audio_np: np.ndarray) -> str:
        self._ensure_models()
        if self._mock_mode:
            return "Speaking..."
        # 1. Prefer Nemotron 3.5 streaming for fast interim tokens
        if self._nemotron is not None:
            try:
                with _MLX_LOCK:
                    res = self._nemotron.generate(audio_np)
                    if hasattr(res, "text") and res.text:
                        return res.text.strip()
                    elif isinstance(res, list) and len(res) > 0:
                        t = getattr(res[0], "text", str(res[0])).strip()
                        if t:
                            return t
            except Exception as ne:
                logger.debug(f"Nemotron fast transcribe fallback: {ne}")

        # 2. Fallback to Parakeet
        if self._parakeet is not None:
            try:
                import mlx.core as mx
                from parakeet_mlx.audio import get_logmel
                with _MLX_LOCK:
                    audio_mx = mx.array(audio_np, dtype=mx.float32)
                    mel = get_logmel(audio_mx, self._parakeet.preprocessor_config)
                    res = self._parakeet.generate(mel)
                    if res:
                        return getattr(res[0], "text", str(res[0])).strip()
            except Exception:
                pass
        return ""

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        """Lane 2: Accuracy segmented ASR on VAD stop with sequence tagging and guards."""
        t0 = time.perf_counter()
        self._ensure_models()
        text = ""

        if audio.startswith(b"RIFF"):
            with io.BytesIO(audio) as bio:
                with wave.open(bio, "rb") as wf:
                    raw_pcm = wf.readframes(wf.getnframes())
        else:
            raw_pcm = audio

        audio_np = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(audio_np)))) if len(audio_np) > 0 else 0.0

        if rms > 0.005:
            self.audio_segments_received += 1

            if not self._mock_mode:
                def _do_accuracy_transcribe():
                    with _MLX_LOCK:
                        # 1. Prefer Parakeet (lower WER, lower latency, 5.4% average WER)
                        if self._parakeet is not None:
                            try:
                                import mlx.core as mx
                                from parakeet_mlx.audio import get_logmel
                                audio_mx = mx.array(audio_np, dtype=mx.float32)
                                mel = get_logmel(audio_mx, self._parakeet.preprocessor_config)
                                res = self._parakeet.generate(mel)
                                if res:
                                    return getattr(res[0], "text", str(res[0])).strip()
                            except Exception as pe:
                                logger.debug(f"Parakeet ASR fallback: {pe}")

                        # 2. Whisper fallback
                        if self._whisper is not None:
                            try:
                                res = self._whisper.generate(audio_np)
                                return getattr(res, "text", str(res)).strip()
                            except Exception as we:
                                logger.debug(f"Whisper ASR fallback: {we}")

                        return ""

                text = await asyncio.to_thread(_do_accuracy_transcribe)
            else:
                text = "Thank you for the question. In my previous role I built scalable real-time systems with React and Python."

        # Guard 1: Hallucination guard
        text = filter_hallucinations(text, audio_np)

        # Guard 2: Acoustic echo guard (R3.4b)
        # Apply ONLY if segment started while bot was speaking. Never drop soft speech if bot was silent.
        if self._segment_started_while_bot_speaking:
            if is_acoustic_echo(text, self.last_ai_speech):
                logger.info(f"Acoustic echo detected during bot speech and suppressed: '{text}'")
                text = ""

        stt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        self.last_stt_final_ms = stt_ms

        clean_text = text.strip()
        if clean_text:
            self._segment_seq += 1
            seq = self._segment_seq
            logger.info(f"STT Accuracy Transcript (seq={seq}, {stt_ms:.1f}ms): '{clean_text}'")

            # Evaluate Smart Turn v3 on the speech segment (R3.4c Smart Turn Gating)
            smart_prob = 1.0
            smart_complete = True
            if not self._mock_mode and len(audio_np) > 0:
                try:
                    st_analyzer = _SHARED_SMART_TURN or LocalSmartTurnAnalyzerV3()
                    res_endpoint = st_analyzer._predict_endpoint(audio_np)
                    smart_prob = float(res_endpoint.get("probability", 1.0))
                    smart_complete = (res_endpoint.get("prediction", 1) == 1)
                except Exception as ste:
                    logger.debug(f"Smart turn evaluation: {ste}")

            # Trailing conjunction/filler or punctuation override
            if bool(re.search(r"(?i)\b(because|and|or|so|like|which|but|if|when|also|uh|um)\s*$", clean_text) or clean_text.endswith(",") or clean_text.endswith("...")):
                smart_complete = False

            if self._on_stt_final:
                try:
                    self._on_stt_final(clean_text, stt_ms, smart_prob, seq, smart_complete)
                except TypeError:
                    try:
                        self._on_stt_final(clean_text, stt_ms, smart_prob, seq)
                    except TypeError:
                        self._on_stt_final(clean_text, stt_ms, smart_prob)
                except Exception:
                    pass

            if self._session_trace:
                self._session_trace.log_smart_turn(
                    probability=smart_prob,
                    is_complete=smart_complete,
                    silence_s=0.0,
                )
                self._session_trace.log_stt(
                    lane="lane2_accuracy",
                    text=clean_text,
                    is_final=True,
                    latency_ms=stt_ms,
                    seq=seq,
                )

            yield TranscriptionFrame(
                text=clean_text,
                user_id="candidate",
                timestamp=str(time.time()),
            )


# Backward-compatible alias
ParakeetSTTService = TwoLaneSTTService


class KokoroTTSService(TTSService):
    """TTS service utilizing Kokoro-82M via mlx-audio on Apple Silicon with static phrase cache."""

    def __init__(
        self,
        *,
        model_name: str = "mlx-community/Kokoro-82M-bf16",
        voice: str = "af_heart",
        sample_rate: int = 24000,
        speed: float = 1.0,
        on_first_audio: Optional[Callable[[float], None]] = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._model_name = model_name
        self._voice = voice
        self._speed = max(0.7, min(1.4, float(speed)))
        self._model = _SHARED_KOKORO_MODEL
        self._mock_mode = os.getenv("VOICE_MOCK", "").lower() in {"1", "true", "yes"}
        self._on_first_audio = on_first_audio
        self.last_tts_first_audio_ms: Optional[float] = None

    def set_speed(self, speed: float) -> None:
        self._speed = max(0.7, min(1.4, float(speed)))

    def _ensure_model(self):
        if self._model is None and not self._mock_mode:
            self._model = _load_kokoro_singleton(self._model_name, self._voice)

    def _generate_synthetic_pcm(self, duration_secs: float, sample_rate: int) -> bytes:
        """Generate smooth synthetic audio frames for mock mode / lipsync timing."""
        total_samples = int(duration_secs * sample_rate)
        t = np.linspace(0, duration_secs, total_samples, endpoint=False)
        audio = 0.15 * np.sin(2 * np.pi * 220 * t) * (0.8 + 0.2 * np.sin(2 * np.pi * 4 * t))
        audio_int16 = (audio * 32767).astype(np.int16)
        return audio_int16.tobytes()

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        """Synthesize text into raw PCM audio chunks with cache lookup & first-audio latency tracking."""
        t0 = time.perf_counter()
        first_audio_recorded = False

        def _mark_first_audio():
            nonlocal first_audio_recorded
            if not first_audio_recorded:
                first_audio_recorded = True
                ms = round((time.perf_counter() - t0) * 1000.0, 2)
                self.last_tts_first_audio_ms = ms
                if self._on_first_audio:
                    try:
                        self._on_first_audio(ms)
                    except Exception:
                        pass

        clean_text = (text or "").strip()
        if not clean_text:
            return

        yield TTSStartedFrame(context_id=context_id)

        # 1. Fast path: check pre-synthesized phrase cache first!
        cache_key = (clean_text, round(self._speed, 2))
        cached = _STATIC_TTS_CACHE.get(cache_key)
        if cached is not None:
            pcm_bytes, sr = cached
            _mark_first_audio()
            chunk_size = int(sr * 2 * 0.04)  # 40ms chunks
            for offset in range(0, len(pcm_bytes), chunk_size):
                chunk = pcm_bytes[offset : offset + chunk_size]
                yield TTSAudioRawFrame(
                    audio=chunk,
                    sample_rate=sr,
                    num_channels=1,
                    context_id=context_id,
                )
                await asyncio.sleep(0.001)
            yield TTSStoppedFrame(context_id=context_id)
            return

        if self._model is None and not self._mock_mode:
            await asyncio.to_thread(self._ensure_model)

        logger.info(f"=== [Kokoro TTS Engine] Synthesizing speech (speed={self._speed:.2f}): '{clean_text[:75]}...' ===")

        generated_audio = False
        if self._model is not None and not self._mock_mode:
            try:
                import mlx.core as mx

                loop = asyncio.get_running_loop()
                queue: asyncio.Queue[Optional[Tuple[bytes, int]]] = asyncio.Queue()

                def _producer():
                    try:
                        with _MLX_LOCK:
                            for segment in self._model.generate(
                                text=clean_text,
                                voice=self._voice,
                                speed=self._speed,
                                split_pattern=r"(?<=[.!?,;:])\s+",
                            ):
                                mx.eval(segment.audio)
                                audio_data = np.array(segment.audio, dtype=np.float32)
                                audio_int16 = np.clip(audio_data * 32767.0, -32768, 32767).astype(np.int16)
                                loop.call_soon_threadsafe(
                                    queue.put_nowait, (audio_int16.tobytes(), segment.sample_rate)
                                )
                    except Exception as err:
                        logger.error(f"Error in Kokoro segment generator: {err}")
                    finally:
                        loop.call_soon_threadsafe(queue.put_nowait, None)

                t = threading.Thread(target=_producer, daemon=True)
                t.start()

                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    pcm_bytes, sr = item
                    _mark_first_audio()
                    chunk_size = int(sr * 2 * 0.04)  # 40ms chunks for fast first audio
                    for offset in range(0, len(pcm_bytes), chunk_size):
                        chunk = pcm_bytes[offset : offset + chunk_size]
                        yield TTSAudioRawFrame(
                            audio=chunk,
                            sample_rate=sr,
                            num_channels=1,
                            context_id=context_id,
                        )
                        await asyncio.sleep(0.001)
                    generated_audio = True
            except Exception as e:
                logger.error(f"Error in Kokoro streaming audio generation: {e}")

        if not generated_audio:
            _mark_first_audio()
            word_count = max(1, len(clean_text.split()))
            duration = (0.15 if self._mock_mode else min(8.0, max(0.6, word_count * 0.22)))
            pcm = self._generate_synthetic_pcm(duration, self.sample_rate)
            chunk_size = 4800
            for offset in range(0, len(pcm), chunk_size):
                chunk = pcm[offset : offset + chunk_size]
                yield TTSAudioRawFrame(
                    audio=chunk,
                    sample_rate=self.sample_rate,
                    num_channels=1,
                    context_id=context_id,
                )
                await asyncio.sleep(0.001 if self._mock_mode else 0.04)

        yield TTSStoppedFrame(context_id=context_id)


def build_voice_pipeline_components(
    connection: SmallWebRTCConnection,
    api_key: Optional[str] = None,
    speech_speed: float = 1.0,
    on_stt_interim: Optional[Callable[[str], None]] = None,
    on_stt_final: Optional[Callable[[str, float, Optional[float], int], None]] = None,
    on_tts_first_audio: Optional[Callable[[float], None]] = None,
    session_trace: Optional[Any] = None,
):
    """Constructs the configured voice components for Pipecat with Two-Lane STT and lag monitor."""
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            camera_in_enabled=True,
            camera_out_enabled=False,
        ),
    )

    # Interview-tuned endpointing: tolerates natural thinking pauses while detecting turn end crisply
    vad_analyzer = SileroVADAnalyzer(
        params=VADParams(
            confidence=0.75,
            start_secs=0.25,
            stop_secs=0.55,
            min_volume=0.55,
        )
    )
    vad = VADProcessor(vad_analyzer=vad_analyzer)

    smart_turn = _SHARED_SMART_TURN or LocalSmartTurnAnalyzerV3()
    turn_strategies = UserTurnStrategies(
        stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=smart_turn)]
    )
    turn_analyzer = UserTurnProcessor(user_turn_strategies=turn_strategies)
    stt = TwoLaneSTTService(
        on_stt_interim=on_stt_interim,
        on_stt_final=on_stt_final,
        session_trace=session_trace,
    )
    tts = KokoroTTSService(speed=speech_speed, on_first_audio=on_tts_first_audio)
    sentence_aggregator = SentenceAggregator()

    gemini_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "mock-key"
    llm = GoogleLLMService(
        api_key=gemini_key,
        settings=GoogleLLMService.Settings(model=GEMINI_MODEL_NAME),
    )

    avatar = AvatarProcessor() if AvatarProcessor is not None else None
    rtvi = RTVIProcessor()
    rtvi_observer = RTVIObserver(rtvi=rtvi)
    lag_monitor = EventLoopLagMonitor()

    if avatar is not None:
        @rtvi.event_handler("on_client_ready")
        async def _on_client_ready(proc):
            try:
                await avatar.on_client_ready()
            except Exception as exc:
                logger.debug(f"Avatar on_client_ready notice: {exc}")

    return {
        "transport": transport,
        "vad": vad,
        "turn_analyzer": turn_analyzer,
        "stt": stt,
        "tts": tts,
        "sentence_aggregator": sentence_aggregator,
        "llm": llm,
        "avatar": avatar,
        "rtvi": rtvi,
        "rtvi_observer": rtvi_observer,
        "lag_monitor": lag_monitor,
    }
