"""Turn and Audio Tracing for Candidly Voice Interview Sessions.

Controls:
- DEBUG_TURN_TRACE: Default ON (1) in development/local mode. Saves structured JSONL
  and human-readable turn traces in debug/sessions/<session_id>/.
- DEBUG_AUDIO_CAPTURE: Default ON (1) in development/local mode. Saves raw 16 kHz mono
  speech segments and bot audio. Automatically deletes captures older than 3 days.
  Strictly disabled in production.
"""

import json
import os
import shutil
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

BASE_DEBUG_DIR = Path("debug/sessions")


def is_turn_trace_enabled() -> bool:
    val = os.getenv("DEBUG_TURN_TRACE")
    if val is None:
        # Default ON in non-production
        return os.getenv("ENVIRONMENT", "development").lower() != "production"
    return val.strip().lower() in {"1", "true", "yes", "on"}


def is_audio_capture_enabled() -> bool:
    val = os.getenv("DEBUG_AUDIO_CAPTURE")
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        return False
    if val is None:
        # Default ON in non-production
        return True
    return val.strip().lower() in {"1", "true", "yes", "on"}


def cleanup_old_debug_sessions(max_age_days: int = 3) -> None:
    """Auto-deletes debug sessions older than max_age_days."""
    if not BASE_DEBUG_DIR.exists():
        return
    now = time.time()
    cutoff = now - (max_age_days * 86400)
    for session_dir in BASE_DEBUG_DIR.iterdir():
        if session_dir.is_dir():
            try:
                mtime = session_dir.stat().st_mtime
                if mtime < cutoff:
                    shutil.rmtree(session_dir, ignore_errors=True)
                    logger.debug(f"Pruned expired debug session: {session_dir.name}")
            except Exception as e:
                logger.warning(f"Failed to prune debug session {session_dir.name}: {e}")


class SessionTrace:
    """Manages logging of turns, events, metrics, and audio captures for a session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.trace_enabled = is_turn_trace_enabled()
        self.audio_enabled = is_audio_capture_enabled()
        self.session_dir = BASE_DEBUG_DIR / session_id
        self.audio_dir = self.session_dir / "audio"
        self.trace_file = self.session_dir / "timeline.jsonl"
        self.summary_file = self.session_dir / "summary.txt"

        if self.trace_enabled or self.audio_enabled:
            cleanup_old_debug_sessions(max_age_days=3)
            self.session_dir.mkdir(parents=True, exist_ok=True)
            if self.audio_enabled:
                self.audio_dir.mkdir(parents=True, exist_ok=True)

        self.turn_events: List[Dict[str, Any]] = []

    def _append_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.trace_enabled:
            return
        record = {
            "session_id": self.session_id,
            "timestamp": time.time(),
            "event_type": event_type,
            **payload,
        }
        self.turn_events.append(record)
        try:
            with open(self.trace_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to append to trace file: {e}")

    def log_vad(self, action: str, speech_duration_s: float = 0.0, meta: Optional[Dict] = None) -> None:
        """action: 'speech_start' | 'speech_stop'"""
        self._append_event("VAD", {
            "action": action,
            "speech_duration_s": round(speech_duration_s, 3),
            "meta": meta or {},
        })

    def log_stt(
        self,
        lane: str,
        text: str,
        is_final: bool,
        latency_ms: float = 0.0,
        seq: int = 0,
        meta: Optional[Dict] = None,
    ) -> None:
        """lane: 'lane1_streaming' | 'lane2_accuracy'"""
        self._append_event("STT", {
            "lane": lane,
            "text": text,
            "is_final": is_final,
            "seq": seq,
            "latency_ms": round(latency_ms, 1),
            "meta": meta or {},
        })

    def log_smart_turn(self, probability: float, is_complete: bool, silence_s: float) -> None:
        self._append_event("SMART_TURN", {
            "probability": round(probability, 3),
            "is_complete": is_complete,
            "silence_s": round(silence_s, 3),
        })

    def log_commit(
        self,
        turn_id: str,
        reason: str,
        full_answer: str,
        word_count: int,
        speech_duration_s: float,
        partials_text: Optional[str] = None,
        finalized_text: Optional[str] = None,
        finalize_source: Optional[str] = None,
        finalize_ms: Optional[float] = None,
        partial_count: Optional[int] = None,
        first_caption_ms: Optional[float] = None,
        avg_partial_interval_ms: Optional[float] = None,
        max_partial_interval_ms: Optional[float] = None,
    ) -> None:
        """R3.5b: COMMIT carries the text-of-record chain — live partials vs the
        analyzer's finalized text vs what was persisted — plus commit timings."""
        self._append_event("COMMIT", {
            "turn_id": turn_id,
            "reason": reason,
            "word_count": word_count,
            "speech_duration_s": round(speech_duration_s, 3),
            "full_answer": full_answer,
            "partials_text": partials_text,
            "finalized_text": finalized_text,
            "finalize_source": finalize_source,
            "finalize_ms": finalize_ms,
            "partial_count": partial_count,
            "first_caption_ms": first_caption_ms,
            "avg_partial_interval_ms": avg_partial_interval_ms,
            "max_partial_interval_ms": max_partial_interval_ms,
        })

    def log_decision(
        self,
        turn_id: str,
        action: str,
        decision_json: Dict[str, Any],
        provider: str,
        model: str,
        latency_ms: float,
        prompt_tokens: int = 0,
        thinking_tokens: int = 0,
        completion_tokens: int = 0,
        degraded: bool = False,
    ) -> None:
        self._append_event("DECISION", {
            "turn_id": turn_id,
            "action": action,
            "provider": provider,
            "model": model,
            "latency_ms": round(latency_ms, 1),
            "tokens": {
                "prompt": prompt_tokens,
                "thinking": thinking_tokens,
                "completion": completion_tokens,
            },
            "degraded": degraded,
            "decision": decision_json,
        })

    def log_tts(
        self,
        turn_id: str,
        action: str,
        text: str,
        latency_ms: float = 0.0,
        cached: bool = False,
    ) -> None:
        """action: 'start' | 'stop' | 'prewarm'"""
        self._append_event("TTS", {
            "turn_id": turn_id,
            "action": action,
            "text": text,
            "cached": cached,
            "latency_ms": round(latency_ms, 1),
        })

    def log_interruption(self, cause: str, candidate_speech_duration_ms: float, bot_text: str) -> None:
        self._append_event("INTERRUPTION", {
            "cause": cause,
            "candidate_speech_ms": round(candidate_speech_duration_ms, 1),
            "bot_text": bot_text,
        })

    def log_event_loop_lag(self, lag_ms: float, p95_ms: float, max_ms: float) -> None:
        self._append_event("EVENT_LOOP_LAG", {
            "current_lag_ms": round(lag_ms, 2),
            "p95_lag_ms": round(p95_ms, 2),
            "max_lag_ms": round(max_ms, 2),
        })

    def log_queue_metrics(self, input_queue_depth: int, dropped_frames: int, received_frames: int) -> None:
        self._append_event("QUEUE_METRICS", {
            "input_queue_depth": input_queue_depth,
            "dropped_frames": dropped_frames,
            "received_frames": received_frames,
        })

    def save_audio_segment(
        self,
        name: str,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> Optional[str]:
        if not self.audio_enabled or not pcm_bytes:
            return None
        filename = f"{name}.wav"
        filepath = self.audio_dir / filename
        try:
            with wave.open(str(filepath), "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_bytes)
            return str(filepath)
        except Exception as e:
            logger.warning(f"Failed to save audio capture {filename}: {e}")
            return None
