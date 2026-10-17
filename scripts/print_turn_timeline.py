#!/usr/bin/env python3
"""Print human-readable timeline for a voice interview session.

Usage:
    ./scripts/print_turn_timeline.py <session_id>
"""

import json
import sys
import time
from pathlib import Path


def format_rel_time(t: float, start_t: float) -> str:
    diff = t - start_t
    mins = int(diff // 60)
    secs = diff % 60
    return f"{mins:02d}:{secs:05.2f}"


def print_timeline(session_id: str):
    session_dir = Path("debug/sessions") / session_id
    timeline_file = session_dir / "timeline.jsonl"

    if not timeline_file.exists():
        print(f"Error: Timeline file not found: {timeline_file}")
        print("Available sessions:")
        if Path("debug/sessions").exists():
            for d in sorted(Path("debug/sessions").iterdir()):
                if d.is_dir():
                    print(f"  - {d.name}")
        sys.exit(1)

    records = []
    with open(timeline_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

    if not records:
        print(f"Timeline is empty for session {session_id}")
        return

    start_time = records[0]["timestamp"]

    print("=" * 80)
    print(f"CANDIDLY TURN TIMELINE - SESSION: {session_id}")
    print(f"Total events: {len(records)} | Start: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")
    print("=" * 80)
    print(f"{'TIME':<10} | {'EVENT':<16} | {'DETAILS'}")
    print("-" * 80)

    for r in records:
        t_str = f"+{format_rel_time(r['timestamp'], start_time)}"
        etype = r.get("event_type", "UNKNOWN")

        if etype == "VAD":
            action = r.get("action", "")
            dur = r.get("speech_duration_s", 0)
            details = f"VAD {action.upper()}" + (f" (duration: {dur:.2f}s)" if dur > 0 else "")
            print(f"{t_str:<10} | \033[94m{etype:<16}\033[0m | {details}")

        elif etype == "STT":
            lane = r.get("lane", "")
            is_final = r.get("is_final", False)
            text = r.get("text", "")
            seq = r.get("seq", 0)
            lat = r.get("latency_ms", 0)
            tag = "FINAL" if is_final else "INTERIM"
            color = "\033[92m" if is_final else "\033[90m"
            print(f"{t_str:<10} | {color}{f'STT [{lane}]':<16}\033[0m | [{tag} #{seq} {lat}ms] \"{text}\"")

        elif etype == "SMART_TURN":
            prob = r.get("probability", 0)
            comp = r.get("is_complete", False)
            sil = r.get("silence_s", 0)
            status = "COMPLETE" if comp else "INCOMPLETE"
            print(f"{t_str:<10} | \033[95m{etype:<16}\033[0m | p(complete)={prob:.3f} [{status}] silence={sil:.2f}s")

        elif etype == "COMMIT":
            turn_id = r.get("turn_id", "")
            reason = r.get("reason", "")
            wc = r.get("word_count", 0)
            dur = r.get("speech_duration_s", 0)
            ans = r.get("full_answer", "")
            print("-" * 80)
            print(f"{t_str:<10} | \033[1;93mCOMMIT_TURN\033[0m    | Turn {turn_id} committed ({reason})")
            print(f"{' ':<10} | {' ':<16} | Words: {wc} | Speech: {dur:.2f}s | Full Answer: \"{ans}\"")
            print("-" * 80)

        elif etype == "DECISION":
            turn_id = r.get("turn_id", "")
            action = r.get("action", "")
            provider = r.get("provider", "")
            model = r.get("model", "")
            lat = r.get("latency_ms", 0)
            degraded = r.get("degraded", False)
            toks = r.get("tokens", {})
            p_tok = toks.get("prompt", 0)
            th_tok = toks.get("thinking", 0)
            c_tok = toks.get("completion", 0)
            deg_str = " [DEGRADED/FALLBACK]" if degraded else ""
            print(f"{t_str:<10} | \033[1;96mDECISION\033[0m       | Turn {turn_id}: {action} via {provider}/{model}{deg_str} in {lat:.1f}ms (in:{p_tok}, think:{th_tok}, out:{c_tok})")
            dec = r.get("decision", {})
            if dec:
                if dec.get("free_probe_text"):
                    print(f"{' ':<10} | {' ':<16} | Free probe: \"{dec.get('free_probe_text')}\"")
                if dec.get("probe_id"):
                    print(f"{' ':<10} | {' ':<16} | Stored probe ID: {dec.get('probe_id')}")

        elif etype == "TTS":
            action = r.get("action", "")
            turn_id = r.get("turn_id", "")
            cached = r.get("cached", False)
            lat = r.get("latency_ms", 0)
            text = r.get("text", "")
            cache_str = " (CACHED)" if cached else ""
            print(f"{t_str:<10} | \033[33mTTS {action.upper()}{cache_str}\033[0m    | Turn {turn_id} ({lat}ms): \"{text[:70]}{'...' if len(text)>70 else ''}\"")

        elif etype == "INTERRUPTION":
            cause = r.get("cause", "")
            cand_ms = r.get("candidate_speech_ms", 0)
            bot_text = r.get("bot_text", "")
            print(f"{t_str:<10} | \033[1;91mINTERRUPTION\033[0m   | Cause: {cause} (after {cand_ms:.0f}ms speech) cut off bot: \"{bot_text[:60]}...\"")

        elif etype == "EVENT_LOOP_LAG":
            cur = r.get("current_lag_ms", 0)
            p95 = r.get("p95_lag_ms", 0)
            m = r.get("max_lag_ms", 0)
            warn = " \033[91m[HIGH LAG > 50ms]\033[0m" if p95 > 50 else ""
            print(f"{t_str:<10} | \033[90mLAG_SAMPLE\033[0m     | current={cur:.1f}ms, p95={p95:.1f}ms, max={m:.1f}ms{warn}")

        elif etype == "QUEUE_METRICS":
            depth = r.get("input_queue_depth", 0)
            dropped = r.get("dropped_frames", 0)
            rec = r.get("received_frames", 0)
            print(f"{t_str:<10} | \033[90mQUEUE_METRICS\033[0m  | depth={depth}, dropped={dropped}, received={rec}")

        else:
            print(f"{t_str:<10} | {etype:<16} | {json.dumps(r)}")

    print("=" * 80)
    print(f"End of timeline for session {session_id}")
    print("=" * 80)


def get_latest_session_id() -> str:
    sessions_dir = Path("debug/sessions")
    if not sessions_dir.exists():
        print("Error: debug/sessions does not exist.")
        sys.exit(1)
    session_dirs = [
        d for d in sessions_dir.iterdir()
        if d.is_dir() and (d / "timeline.jsonl").exists()
    ]
    if not session_dirs:
        print("Error: No sessions with timeline.jsonl found in debug/sessions.")
        sys.exit(1)
    latest = max(session_dirs, key=lambda d: (d / "timeline.jsonl").stat().st_mtime)
    return latest.name


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/print_turn_timeline.py <session_id | --last>")
        sys.exit(1)

    target_id = sys.argv[1]
    if target_id == "--last":
        target_id = get_latest_session_id()
        print(f"Targeting latest session: {target_id}")

    print_timeline(target_id)
