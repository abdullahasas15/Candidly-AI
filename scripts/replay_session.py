#!/usr/bin/env python3
"""Replay and offline comparison for a recorded voice interview session.

Usage:
    ./scripts/replay_session.py <session_id>

Re-runs STT and turn detection on saved audio segments offline,
comparing what happened live against offline Whisper and Parakeet models.
"""

import difflib
import json
import sys
from pathlib import Path

def replay_session(session_id: str):
    session_dir = Path("debug/sessions") / session_id
    timeline_file = session_dir / "timeline.jsonl"
    audio_dir = session_dir / "audio"

    if not timeline_file.exists():
        print(f"Error: Timeline file not found at {timeline_file}")
        sys.exit(1)

    print("=" * 80)
    print(f"REPLAY & OFFLINE VERIFICATION - SESSION: {session_id}")
    print("=" * 80)

    # Read live events
    events = []
    with open(timeline_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass

    live_commits = [e for e in events if e.get("event_type") == "COMMIT"]
    live_stt_finals = [e for e in events if e.get("event_type") == "STT" and e.get("is_final")]

    print(f"Live session recorded {len(live_commits)} commits and {len(live_stt_finals)} final STT segments.")

    if not audio_dir.exists() or not list(audio_dir.glob("*.wav")):
        print("Note: No audio segments found in audio/ directory (DEBUG_AUDIO_CAPTURE may have been off).")
        print("Showing live transcript commits:")
        for i, c in enumerate(live_commits, 1):
            print(f"  Turn {c.get('turn_id', i)}: \"{c.get('full_answer', '')}\" ({c.get('word_count')} words)")
        return

    wav_files = sorted(audio_dir.glob("*.wav"))
    print(f"Found {len(wav_files)} audio segment(s). Loading offline ASR engine...")

    # Load ASR model for offline replay
    try:
        from mlx_audio.stt.utils import load_model
        import mlx_audio.stt.generate as generate
        print("Loading Whisper model (mlx-community/whisper-large-v3-turbo)...")
        whisper_model = load_model("mlx-community/whisper-large-v3-turbo")
    except Exception as e:
        print(f"Warning: Could not load Whisper offline ({e}), falling back to Parakeet...")
        whisper_model = None
        try:
            import parakeet_mlx
            parakeet_model = parakeet_mlx.from_pretrained("mlx-community/parakeet-tdt-0.6b-v2")
        except Exception as pe:
            print(f"Error: Could not load offline models: {pe}")
            return

    print("\n" + "-" * 80)
    print(f"{'FILE / TURN':<25} | {'ORIGINAL LIVE':<30} | {'OFFLINE REPLAY':<30}")
    print("-" * 80)

    for wav_path in wav_files:
        name = wav_path.stem
        # Transcribe offline
        replay_text = ""
        try:
            if whisper_model is not None:
                res = whisper_model.generate(str(wav_path))
                replay_text = res.text.strip()
            else:
                import parakeet_mlx
                from parakeet_mlx.audio import get_logmel
                import mlx.core as mx
                import numpy as np
                import wave
                with wave.open(str(wav_path), "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    arr = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                mel = get_logmel(mx.array(arr), parakeet_model.preprocessor_config)
                replay_text = parakeet_model.generate(mel).text.strip()
        except Exception as e:
            replay_text = f"[Transcribe error: {e}]"

        # Match with original if possible
        orig_match = ""
        for c in live_commits:
            if c.get("turn_id") in name:
                orig_match = c.get("full_answer", "")
                break
        if not orig_match and live_stt_finals:
            orig_match = live_stt_finals[0].get("text", "")

        print(f"{name:<25} | {orig_match[:28]:<30} | {replay_text[:28]:<30}")
        if orig_match and replay_text and orig_match != replay_text:
            diff = difflib.ndiff(orig_match.split(), replay_text.split())
            diff_str = " ".join([d for d in diff if d.startswith("+") or d.startswith("-")])
            print(f"    Diff: {diff_str}")

    print("=" * 80)
    print("Replay comparison complete.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/replay_session.py <session_id>")
        sys.exit(1)
    replay_session(sys.argv[1])
