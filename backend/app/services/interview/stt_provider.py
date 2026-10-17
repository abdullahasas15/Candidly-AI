"""R3.5: Pluggable STT provider layer for Candidly live interviews.

Providers
---------
- apple_speechanalyzer : macOS 26+ SpeechAnalyzer + SpeechTranscriber via native/apple_stt
                         Swift helper (dictation-quality streaming, partials in real time).
- apple_sfspeech       : macOS 13-25 on-device SFSpeechRecognizer via the same helper
                         (best-effort; needs a TCC-granted signed app wrapper).
- local_two_lane       : The R3.4 in-process MLX stack (Nemotron streaming + Parakeet/Whisper),
                         unchanged fallback.

Selection (STT_PROVIDER env):
    auto | apple_speechanalyzer | apple_sfspeech | local_two_lane
    auto = apple_speechanalyzer (if helper built + model installed + macOS>=26)
           -> apple_sfspeech (macOS>=13) -> local_two_lane.

The helper protocol:
    stdin : 16 kHz mono PCM16 raw audio
    stdout: JSON lines {"type": partial|final|ready|model_status|meta|error, ...}
    control TCP socket (port announced in `ready`): FLUSH | PING | EXIT commands.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import platform
import re
import subprocess
import time
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[4]
APPLE_STT_BINARY = Path(
    os.getenv("APPLE_STT_BINARY", str(REPO_ROOT / "native/apple_stt/.build/release/apple_stt"))
)
CONTEXT_TERMS_FILE = REPO_ROOT / "debug" / "stt_context_terms.txt"

SUPPORTED_PROVIDERS = ("apple_speechanalyzer", "apple_sfspeech", "local_two_lane")


def stitch_sliding_text(committed: str, incoming: str) -> str:
    """Reconstruct cumulative text from sliding volatile STT windows.

    Apple (and other dictation engines) emit volatile windows that periodically drop
    the oldest words; overlapping suffix/prefix stitching rebuilds the full utterance.
    """
    committed = (committed or "").strip()
    incoming = (incoming or "").strip()
    if not committed:
        return incoming
    if not incoming:
        return committed
    if incoming in committed:
        return committed
    if committed in incoming:
        return incoming
    max_ov = min(len(committed), len(incoming))
    for ov in range(max_ov, 4, -1):
        if incoming.startswith(committed[-ov:]):
            return (committed + incoming[ov:]).strip()
    return (committed + " " + incoming).strip()


def macos_major_version() -> int:
    try:
        out = subprocess.run(
            ["/usr/bin/sw_vers", "-productVersion"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        return int(out.split(".")[0])
    except Exception:
        try:
            version = platform.mac_ver()[0]  # e.g. "27.0.1"
            return int((version or "0").split(".")[0])
        except Exception:
            try:
                return int(platform.release().split(".")[0]) + 1  # Darwin+1 == macOS major
            except Exception:
                return 0


def helper_is_built() -> bool:
    return APPLE_STT_BINARY.exists() and os.access(APPLE_STT_BINARY, os.X_OK)


@dataclass
class SttProviderStatus:
    provider: str
    ready: bool
    locale: str = "en-US"
    detail: str = ""
    needs_download: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "ready": self.ready,
            "locale": self.locale,
            "detail": self.detail,
            "needs_download": self.needs_download,
        }


def _parse_jsonl(blob: bytes) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for line in blob.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def probe_apple_helper(provider: Optional[str], locale: Optional[str], timeout: float = 12.0) -> SttProviderStatus:
    """Run the helper in --check mode and read its readiness JSON."""
    if not helper_is_built():
        return SttProviderStatus("apple_stt", ready=False, detail="helper not built (run scripts/build_apple_stt.sh)")
    mode = provider or "speechanalyzer"
    loc = locale or os.getenv("STT_LOCALE", "en-US")
    try:
        proc = subprocess.run(
            [str(APPLE_STT_BINARY), "--check", "--mode", mode, "--locale", loc],
            capture_output=True,
            timeout=timeout,
        )
        events = _parse_jsonl(proc.stdout)
        ev = next((e for e in events if e.get("type") == "check"), None)
        if not ev:
            detail = (proc.stderr or b"").decode("utf-8", errors="replace")[:200] or "no check event"
            return SttProviderStatus(f"apple_{mode}", ready=False, locale=loc, detail=detail)
        supported = bool(ev.get("supported"))
        installed = bool(ev.get("installed"))
        needs = bool(ev.get("needs_download"))
        ready = supported and installed and not needs
        return SttProviderStatus(
            f"apple_{mode}",
            ready=ready,
            locale=loc,
            detail=str(ev.get("detail") or ""),
            needs_download=needs,
        )
    except Exception as exc:  # noqa: BLE001
        return SttProviderStatus(f"apple_{mode}", ready=False, locale=loc, detail=f"probe failed: {exc}")


def resolve_stt_provider(locale: Optional[str] = None) -> tuple[str, SttProviderStatus]:
    """Choose the STT provider per STT_PROVIDER env with the documented auto chain."""
    env_choice = (os.getenv("STT_PROVIDER", "auto") or "auto").strip().lower()
    mac_version = macos_major_version()
    status = SttProviderStatus("local_two_lane", ready=True, detail="MLX in-process")

    if env_choice not in ("", "auto"):
        return env_choice, SttProviderStatus(env_choice, ready=True, detail="explicit STT_PROVIDER")

    if mac_version >= 13 and helper_is_built():
        if mac_version >= 26:
            probe = probe_apple_helper("speechanalyzer", locale)
            if probe.ready:
                return "apple_speechanalyzer", probe
            logger.info(f"[STT] apple_speechanalyzer not ready ({probe.detail}); falling back")
        probe_sf = probe_apple_helper("sfspeech", locale)
        if probe_sf.ready:
            return "apple_sfspeech", probe_sf
        logger.info(f"[STT] apple_sfspeech not ready ({probe_sf.detail}); falling back")
    else:
        detail = f"macOS {mac_version}" + (" + helper not built" if mac_version >= 13 else "")
        status = SttProviderStatus("local_two_lane", ready=True, detail=f"auto chain bypassed: {detail}")

    return "local_two_lane", status


def get_stt_provider_status(locale: Optional[str] = None) -> Dict[str, Any]:
    """Combined status snapshot for /api/health and candidate pre-flight."""
    env_choice = (os.getenv("STT_PROVIDER", "auto") or "auto").strip().lower()
    chosen, probe = resolve_stt_provider(locale or os.getenv("STT_LOCALE"))
    return {
        "requested": env_choice,
        "resolved": chosen,
        "helper_built": helper_is_built(),
        "macos_major": macos_major_version(),
        "probe": probe.as_dict(),
        "ready": probe.ready,
    }


def write_context_terms_file(terms: List[str]) -> Optional[str]:
    """Persist caller-provided contextual strings (job skills + resume terms) for the helper."""
    clean = [t.strip() for t in (terms or []) if t and len(t.strip()) > 1][:100]
    if not clean:
        return None
    try:
        CONTEXT_TERMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONTEXT_TERMS_FILE.write_text("\n".join(clean), encoding="utf-8")
        return str(CONTEXT_TERMS_FILE)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[STT] context terms write notice: {exc}")
        return None


class AppleSpeechProcess:
    """Supervises one apple_stt helper subprocess (streaming dictation)."""

    def __init__(
        self,
        provider: str,  # "apple_speechanalyzer" | "apple_sfspeech"
        locale: str = "en-US",
        context_terms: Optional[List[str]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[str, int, float, float], None]] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.provider = provider
        self.locale = locale
        self.context_terms = context_terms or []
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_event = on_event
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._writer_task: Optional[asyncio.Task] = None
        self._write_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._control_writer: Optional[asyncio.StreamWriter] = None
        self._pending_final: asyncio.Queue = asyncio.Queue(maxsize=64)
        self.started: bool = False
        self.dropped_chunks: int = 0
        self.chunks_fed: int = 0
        self.final_count: int = 0

    # -- lifecycle ---------------------------------------------------------

    async def start(self, start_timeout: float = 20.0) -> bool:
        args = [str(APPLE_STT_BINARY), "--mode", self.provider.replace("apple_", ""), "--locale", self.locale]
        ctx_path = write_context_terms_file(self.context_terms)
        if ctx_path:
            args += ["--context", ctx_path]
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE if os.getenv("APPLE_STT_DEBUG") else asyncio.subprocess.DEVNULL,
            limit=2 ** 20,
        )
        if os.getenv("APPLE_STT_DEBUG") and self._proc.stderr:
            asyncio.create_task(self._stderr_loop())
        self._reader_task = asyncio.create_task(self._read_loop())
        self._writer_task = asyncio.create_task(self._write_loop())
        deadline = time.monotonic() + start_timeout
        while time.monotonic() < deadline:
            if self._ready_event is not None:
                # meta (with control_port) always follows ready; allow a short window.
                await asyncio.sleep(0.25)
                if self._control_port:
                    self.started = True
                    await self._connect_control(self._control_port)
                    logger.info(
                        f"[STT] Apple helper ready provider={self.provider} locale={self.locale} port={self._control_port}"
                    )
                    return True
                # No control port yet — wait for it inside the same deadline.
            if self._proc.returncode is not None:
                logger.error(f"[STT] Apple helper exited code={self._proc.returncode}")
                return False
            await asyncio.sleep(0.1)
        logger.error("[STT] Apple helper readiness timeout")
        return False

    async def stop(self) -> None:
        try:
            if self._control_writer:
                self._control_writer.write(b"EXIT\n")
                await self._control_writer.drain()
        except Exception:
            pass
        await asyncio.sleep(0.1)
        for task in (self._reader_task, self._writer_task):
            if task and not task.done():
                task.cancel()
        try:
            if self._proc and self._proc.returncode is None:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self._proc.kill()
        except Exception:
            pass
        self.started = False

    # -- audio + control ----------------------------------------------------

    async def feed(self, pcm: bytes) -> None:
        if not self.started or not pcm:
            return
        self.chunks_fed += 1
        try:
            self._write_queue.put_nowait(pcm)
        except asyncio.QueueFull:
            self.dropped_chunks += 1
            try:
                self._write_queue.get_nowait()  # drop oldest, keep stream current
                self._write_queue.put_nowait(pcm)
            except Exception:
                pass

    async def flush_and_wait(self, timeout: float = 1.0) -> Optional[str]:
        """Force-finalize transcribed audio; wait <=timeout for the last final."""
        if not self.started:
            return None
        await self._send_command(b"FLUSH\n")
        try:
            text = await asyncio.wait_for(self._pending_final.get(), timeout=timeout)
            return text
        except asyncio.TimeoutError:
            return None

    async def finalize_at_eof(self, final_wait: float = 5.0) -> None:
        """Offline tooling: close stdin EOF; helper finalizes and emits remaining finals."""
        try:
            if self._proc and self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        deadline = time.monotonic() + final_wait
        prev = self.final_count
        while time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            if self.final_count > prev:
                # quiet window after the last final
                prev = self.final_count
                deadline = min(deadline, time.monotonic() + 0.8)

    async def ping(self) -> bool:
        try:
            await self._send_command(b"PING\n")
            return True
        except Exception:
            return False

    async def _send_command(self, payload: bytes) -> None:
        if not self._control_writer:
            return
        self._control_writer.write(payload)
        await self._control_writer.drain()

    async def _connect_control(self, port: int) -> None:
        if not port:
            return
        for attempt in range(20):
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                self._control_writer = writer
                return
            except Exception:
                await asyncio.sleep(0.2)
        logger.warning("[STT] control socket connect failed (flush still works at stdin EOF)")

    # -- internals -----------------------------------------------------------

    async def _write_loop(self) -> None:
        try:
            while True:
                pcm = await self._write_queue.get()
                if pcm is None:
                    return
                if self._proc and self._proc.stdin:
                    self._proc.stdin.write(pcm)
                    await self._proc.stdin.drain()
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[STT] helper stdin writer stopped: {exc}")

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                return
            try:
                ev = json.loads(line.decode("utf-8", errors="replace"))
            except Exception:
                continue
            self._dispatch(ev)

    async def _stderr_loop(self) -> None:
        assert self._proc and self._proc.stderr
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                return
            logger.debug(f"[apple_stt] {line.decode().rstrip()}")

    def _dispatch(self, ev: Dict[str, Any]) -> None:  # noqa: C901
        ev_type = ev.get("type")
        if ev_type == "ready":
            self._ready_event = ev
        elif ev_type == "meta":
            self._control_port = int(ev.get("control_port") or 0)
        elif ev_type == "partial":
            text = (ev.get("text") or "").strip()
            if text and self.on_partial:
                try:
                    self.on_partial(text)
                except Exception:
                    pass
        elif ev_type == "final":
            text = (ev.get("text") or "").strip()
            seq = int(ev.get("seq") or 0)
            start = float(ev.get("start") or 0.0)
            end = float(ev.get("end") or 0.0)
            # Drop punctuation-only / hallucinated finals on trailing silence.
            meaningful = re.sub(r"[.\s…·]+", "", text or "")
            if text and meaningful:
                self.final_count += 1
                try:
                    self._pending_final.put_nowait(text)
                except asyncio.QueueFull:
                    pass
                if self.on_final:
                    try:
                        self.on_final(text, seq, start, end)
                    except Exception:
                        pass
        elif ev_type == "model_download":
            if self.on_event:
                try:
                    self.on_event(ev)
                except Exception:
                    pass
        elif ev_type == "error":
            logger.warning(f"[STT] helper error: {ev.get('message')}")
            if self.on_event:
                try:
                    self.on_event(ev)
                except Exception:
                    pass

    _ready_event: Optional[Dict[str, Any]] = None
    _control_port: int = 0


# ---------------------------------------------------------------------------
# Offline transcription (preflight check + captured-audio review tooling)
# ---------------------------------------------------------------------------

def _wav_to_pcm16(wav_bytes: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())
    if rate == 16000 and channels == 1:
        return frames, rate
    # Minimal conversion via numpy resample when needed.
    import numpy as np  # noqa: PLC0415

    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    target_len = int(len(samples) * 16000 / rate)
    if target_len > 0:
        x_old = np.linspace(0.0, 1.0, len(samples), endpoint=False)
        x_new = np.linspace(0.0, 1.0, target_len, endpoint=False)
        samples = np.interp(x_new, x_old, samples)
    return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes(), 16000


async def transcribe_with_provider_async(
    wav_bytes: bytes,
    provider: Optional[str] = None,
    locale: Optional[str] = None,
    final_wait: float = 6.0,
) -> Dict[str, Any]:
    """Transcribe an entire captured file with one provider (no networking, no LLM)."""
    provider = provider or (os.getenv("STT_PROVIDER", "auto") or "auto")
    if provider == "auto":
        provider, _ = resolve_stt_provider(locale)
    locale = locale or os.getenv("STT_LOCALE", "en-US")
    started = time.perf_counter()

    if provider in ("apple_speechanalyzer", "apple_sfspeech"):
        if not helper_is_built():
            return {"provider": provider, "text": "", "error": "helper not built"}
        pcm, _ = _wav_to_pcm16(wav_bytes) if wav_bytes.startswith(b"RIFF") else (wav_bytes, 16000)
        finals: List[str] = []
        partials: List[str] = []
        proc = AppleSpeechProcess(
            provider=provider,
            locale=locale,
            on_partial=lambda t: partials.append(t),
            on_final=lambda t, s, a, b: finals.append(t),
        )
        if not await proc.start():
            return {"provider": provider, "text": "", "error": "helper failed to start"}
        # Feed close to real-time pace so the on-device model receives continuous audio.
        step = 6400  # 200ms
        for i in range(0, len(pcm), step):
            await proc.feed(pcm[i : i + step])
            await asyncio.sleep(0.18)
        await asyncio.sleep(1.2)
        # Fire the finalize commands (best effort). The stitched partials below are the
        # text of record either way — identical to the live commit path.
        await proc.finalize_at_eof(final_wait=final_wait)
        await proc.stop()
        stitched = ""
        for p in partials:
            stitched = stitch_sliding_text(stitched, p)
        # Append any finalized content not already covered by the stitch.
        extra = []
        for f in finals:
            f_clean = f.strip()
            if f_clean and f_clean.lower() not in stitched.lower():
                extra.append(f_clean)
        text = (stitched if stitched else " ".join(extra)).strip()
        return {
            "provider": provider,
            "text": text,
            "finals": finals,
            "stitched": stitched,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
        }

    # local_two_lane: in-process MLX (Parakeet -> Whisper), same as live fallback.
    def _local_transcribe() -> str:
        import numpy as np

        from backend.app.services.interview.voice_pipeline import (
            filter_hallucinations,
            _load_parakeet_singleton,
            _load_whisper_singleton,
        )

        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                raw = wf.readframes(wf.getnframes())
                rate = wf.getframerate()
        except Exception:
            raw = wav_bytes
            rate = 16000
        audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if rate != 16000:
            target_len = int(len(audio_np) * 16000 / rate)
            audio_np = np.interp(
                np.linspace(0.0, 1.0, target_len, endpoint=False),
                np.linspace(0.0, 1.0, len(audio_np), endpoint=False),
                audio_np,
            )
        text = ""
        parakeet = _load_parakeet_singleton()
        if parakeet is not None:
            try:
                import mlx.core as mx
                from parakeet_mlx.audio import get_logmel

                audio_mx = mx.array(audio_np, dtype=mx.float32)
                mel = get_logmel(audio_mx, parakeet.preprocessor_config)
                res = parakeet.generate(mel)
                if res:
                    text = getattr(res[0], "text", str(res[0])).strip()
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[review] parakeet offline failed: {exc}")
        if not text:
            whisper = _load_whisper_singleton()
            if whisper is not None:
                try:
                    res = whisper.generate(audio_np)
                    text = getattr(res, "text", str(res)).strip()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"[review] whisper offline failed: {exc}")
        return filter_hallucinations(text, audio_np)

    text = await asyncio.to_thread(_local_transcribe)
    return {"provider": "local_two_lane", "text": text, "latency_ms": round((time.perf_counter() - started) * 1000.0, 1)}


def transcribe_with_provider(wav_bytes: bytes, provider: Optional[str] = None, locale: Optional[str] = None) -> Dict[str, Any]:
    """Sync wrapper used by CLI tooling."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        raise RuntimeError("Use transcribe_with_provider_async inside a running loop")
    return asyncio.run(transcribe_with_provider_async(wav_bytes, provider=provider, locale=locale))


def new_segment_id() -> str:
    return uuid.uuid4().hex[:12]
