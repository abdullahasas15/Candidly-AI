"""Print latency statistics (count, min, p50, p90, p95, max) per stage for live interview turns.

Usage:
    PYTHONPATH=. ./.venv/bin/python scripts/print_latency_stats.py [--session-id <UUID>]
"""

import argparse
import asyncio
import numpy as np
from sqlalchemy import select

from backend.app.database import AsyncSessionLocal
from backend.app.models import InterviewTranscriptTurn


def _calc_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "min": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}
    arr = np.array(values, dtype=float)
    return {
        "count": len(arr),
        "min": float(np.min(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(np.max(arr)),
    }


async def main(session_id: str | None = None) -> None:
    async with AsyncSessionLocal() as session:
        query = select(InterviewTranscriptTurn)
        if session_id:
            query = query.where(InterviewTranscriptTurn.session_id == session_id)
        result = await session.execute(query)
        turns = result.scalars().all()

    stt_vals = [t.stt_final_ms for t in turns if t.stt_final_ms is not None]
    llm_vals = [t.llm_ttft_ms for t in turns if t.llm_ttft_ms is not None]
    tts_vals = [t.tts_first_audio_ms for t in turns if t.tts_first_audio_ms is not None]
    tot_vals = [t.total_response_ms for t in turns if t.total_response_ms is not None]

    print("=========================================================================")
    print(f"  CANDIDLY INTERVIEW LATENCY REPORT (Total recorded turns: {len(turns)})")
    if session_id:
        print(f"  Filtered by Session ID: {session_id}")
    print("=========================================================================")
    print(f"{'Stage':<22} | {'Count':<6} | {'Min (ms)':<9} | {'p50 (ms)':<9} | {'p90 (ms)':<9} | {'p95 (ms)':<9} | {'Max (ms)':<9}")
    print("-" * 85)

    stages = [
        ("STT Final", stt_vals),
        ("LLM TTFT", llm_vals),
        ("TTS First Audio", tts_vals),
        ("Total Response", tot_vals),
    ]

    for stage_name, vals in stages:
        s = _calc_stats(vals)
        print(
            f"{stage_name:<22} | {s['count']:<6} | {s['min']:<9.1f} | {s['p50']:<9.1f} | {s['p90']:<9.1f} | {s['p95']:<9.1f} | {s['max']:<9.1f}"
        )

    print("=========================================================================")
    tot_s = _calc_stats(tot_vals)
    target_p50 = 1000.0
    target_p95 = 1800.0
    if tot_s["count"] > 0:
        p50_status = "PASS" if tot_s["p50"] <= target_p50 else "EXCEEDS TARGET"
        p95_status = "PASS" if tot_s["p95"] <= target_p95 else "EXCEEDS TARGET"
        print(f"Target Evaluation (Total Response: confirmed end-of-turn -> first bot audio):")
        print(f"  p50 <= 1000ms: {tot_s['p50']:.1f}ms [{p50_status}]")
        print(f"  p95 <= 1800ms: {tot_s['p95']:.1f}ms [{p95_status}]")
    else:
        print("No turn latency data recorded yet in interview_transcript_turns.")
    print("=========================================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print latency percentiles for live interview turns")
    parser.add_argument("--session-id", type=str, default=None, help="Filter by session ID")
    args = parser.parse_args()
    asyncio.run(main(args.session_id))
