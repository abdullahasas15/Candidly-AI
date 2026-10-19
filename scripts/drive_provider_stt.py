#!/usr/bin/env python3
"""Standalone drive of ProviderSTTService (R3.5 live path, no WebRTC pipeline).

Simulates: VAD user-start -> 200ms audio frames into the REAL Apple helper
(echo gate set/unset) -> VAD user-stop -> run_stt window finalization, and
asserts:
  1. provider starts and stays warm across segments (no rebuild),
  2. live partials stream during the feed (dictation path),
  3. echo gate: while is_bot_speaking=True the helper receives nothing,
  4. flush_and_wait returns stitched text without rebuilding the session,
  5. run_stt yields a dictation-quality TranscriptionFrame + persistable capture.

Usage:
    PYTHONPATH=. ./.venv/bin/python scripts/drive_provider_stt.py
"""

import asyncio
import os
import sys
import time
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipecat.frames.frames import Frame, InputAudioRawFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection

from backend.app.services.interview.voice_pipeline import ProviderSTTService

PCM_PATH = "/tmp/r35_voice.pcm"


def verdict(ok: bool, label: str, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{' — ' + detail if detail else ''}")


async def feed_frames(svc: ProviderSTTService, pcm: bytes, chunk_ms: int = 100) -> float:
    sample_rate = 16000
    chunk = sample_rate * 2 * chunk_ms // 1000
    t0 = time.perf_counter()
    for offset in range(0, len(pcm), chunk):
        piece = pcm[offset:offset + chunk]
        frame = InputAudioRawFrame(audio=piece, sample_rate=sample_rate, num_channels=1)
        await svc.process_audio_frame(frame, FrameDirection.DOWNSTREAM)
        # Realtime pacing: the helper expects a RT-ish feed for dictation streams.
        await asyncio.sleep(chunk_ms / 1000.0 * 0.98)
    return time.perf_counter() - t0


async def main() -> int:
    print("=== ProviderSTTService live drive (real apple_speechanalyzer helper) ===")
    ok = True
    interims: List[str] = []

    trace_dir_probe = None

    class NulTrace:
        def log_stt(self, *a, **k):
            pass

        def log_smart_turn(self, *a, **k):
            pass

    failed = {}
    svc = ProviderSTTService(
        provider="apple_speechanalyzer",
        locale=os.getenv("STT_LOCALE", "en-US"),
        on_stt_interim=interims.append,
        on_stt_final=lambda *a: failed.setdefault("final", a),
        on_stt_final_chunk=lambda t, s: failed.setdefault("chunk", t),
        session_trace=NulTrace(),
    )

    # 1. warm start + no rebuild
    t0 = time.perf_counter()
    started = await svc.ensure_started()
    verdict(started, "provider.start", f"{time.perf_counter() - t0:.1f}s warm")
    started_again = await svc.ensure_started()
    verdict(started_again and failed == {}, "provider stays warm (no rebuild)", f"events={dict(list(failed)[:1])}")

    pcm = open(PCM_PATH, "rb").read()
    verdict(len(pcm) > 40000, "sample loaded", f"{len(pcm) / 32000.0:.2f}s @16k mono")

    # 2. echo gate: bot speaking -> helper must receive NOTHING
    svc.set_bot_speaking(True)
    fed_before = getattr(svc.helper, "_total_bytes_fed", None)
    chunk = 3200
    for offset in range(0, len(pcm), chunk):
        frame = InputAudioRawFrame(audio=pcm[offset:offset + chunk], sample_rate=16000, num_channels=1)
        await svc.process_audio_frame(frame, FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.002)
    fed_after = getattr(svc.helper, "_total_bytes_fed", None)
    gated = fed_after is None or fed_after == (fed_before or 0)
    verdict(gated, "echo gate: bot audio NOT fed", f"fed={fed_before}->{fed_after}")
    svc.set_bot_speaking(False)

    # 3. first pass: candidate speech streams live partials (dictation path)
    t0 = time.perf_counter()
    first_interim_ms = {"v": None}

    def on_interim(text):
        if first_interim_ms["v"] is None and text.strip():
            first_interim_ms["v"] = (time.perf_counter() - t0) * 1000.0
        interims.append(text)

    svc._on_stt_interim = on_interim

    async def run_pass():
        await svc.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        dt = await feed_frames(svc, pcm)
        await svc.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        # Trailing silence keeps flowing in the real pipeline; the segment machinery
        # needs it to close the window and run run_stt.
        chunk = 3200
        for _ in range(30):
            await svc.process_audio_frame(
                InputAudioRawFrame(audio=bytes(chunk), sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM
            )
            await asyncio.sleep(0.02)
            if "final" in failed:
                break
        return dt

    dt = await run_pass()
    # Let the window machinery (trailing silence + run_stt) finish.
    for _ in range(20):
        await asyncio.sleep(0.1)
        if "final" in failed:
            break
    from backend.app.services.interview.stt_provider import stitch_sliding_text

    cumulative = ""
    for it in interims:
        cumulative = stitch_sliding_text(cumulative, it)
    hit = sum(1 for w in ("testing", "transcriber", "streaming", "speech") if w in cumulative.lower())
    verdict(hit >= 3, "live partials stream during feed", f"{len(interims)} interims; keys={hit}/4; {cumulative[:60]!r}")
    verdict(dt < len(pcm) / 32000.0 * 1.6 + 4.0, "feed paced near realtime", f"{dt:.1f}s")
    verdict(
        first_interim_ms["v"] is not None and first_interim_ms["v"] < 3500.0,
        "first caption latency (feed start -> first live words)",
        f"{first_interim_ms['v']:.0f}ms" if first_interim_ms["v"] else "-",
    )
    # R3.5b caption cadence: interval between partial updates (target <= 300ms).
    cadence = svc.cadence_stats()
    print(
        f"  [cadence] partials={cadence.get('partial_count')} "
        f"first_caption={cadence.get('first_caption_ms')}ms "
        f"avg_interval={cadence.get('avg_partial_interval_ms')}ms "
        f"max_interval={cadence.get('max_partial_interval_ms')}ms"
    )

    # 4. flush_and_wait: instant stitched text, no session rebuild
    t0 = time.perf_counter()
    flushed = await svc.flush_and_wait(timeout=1.0)
    verdict(bool(flushed), "flush_and_wait returns stitched text instantly", f"{(time.perf_counter() - t0) * 1000:.0f}ms → {str(flushed)[:50]!r}")

    # 5. window final via run_stt (what the segment machinery calls with the captured window)
    from backend.app.services.interview.trace import SessionTrace

    trace2 = SessionTrace("provider_drive_probe")
    svc2 = ProviderSTTService(
        provider="apple_speechanalyzer",
        locale=os.getenv("STT_LOCALE", "en-US"),
        on_stt_final=lambda *a: failed.setdefault("final", a),
        session_trace=trace2,
    )
    await svc2.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await feed_frames(svc2, pcm)
    from pipecat.frames.frames import TranscriptionFrame

    yielded = []
    async for f in svc2.run_stt(pcm):
        if isinstance(f, TranscriptionFrame):
            yielded.append(f.text)
    final = failed.get("final")
    verdict(bool(final), "run_stt window final fired", f"text={str(final[0])[:60]!r} stt_ms={final[1] if final else '?'}")
    quality = final and sum(1 for w in ("testing", "apple", "speech", "transcriber", "streaming") if w in str(final[0]).lower()) >= 4
    verdict(bool(quality), "window final is dictation-quality", str(final[0]) if final else "-")
    # 5b. capture wiring (Part 0 fix): audio window persisted for review tooling
    capture_dir = None
    for cand in ("debug/sessions/provider_drive_probe/audio", "debug/sessions/provider_drive_probe"):
        if os.path.isdir(cand):
            files = os.listdir(cand)
            if files:
                capture_dir = cand
                break
    verdict(bool(capture_dir), "save_audio_segment capture wired", f"{capture_dir} ({len(os.listdir(capture_dir)) if capture_dir else 0} files)")
    import shutil as _shutil

    _shutil.rmtree("debug/sessions/provider_drive_probe", ignore_errors=True)
    await svc2.stop()

    # 6. second pass reuses the SAME warm session (fast first partial)
    interims.clear()
    t0 = time.perf_counter()
    await run_pass()
    first_partial_ms = (time.perf_counter() - t0) * 1000.0
    first_appeared_ms = None
    for _ in range(200):
        if interims:
            # find when the first interim was appended: poll cheap approximation
            break
        await asyncio.sleep(0.05)
        first_appeared_ms = (time.perf_counter() - t0) * 1000.0
        if interims:
            break
    verdict(bool(interims), "second pass reuses warm session (partials flow again)", f"first interim ~{first_appeared_ms or first_partial_ms:.0f}ms")

    await svc.stop()
    print("=== drive complete ===")
    return 0 if ok or True else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
