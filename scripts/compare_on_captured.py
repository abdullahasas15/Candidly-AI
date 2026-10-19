#!/usr/bin/env python3
"""scripts/compare_on_captured.py

Run Parakeet and Whisper on captured audio segments from a real session (or test directory)
and print both transcripts side by side with disagreements highlighted.

Usage:
    ./.venv/bin/python scripts/compare_on_captured.py --session-id <session_id>
    ./.venv/bin/python scripts/compare_on_captured.py --audio-dir debug/test_audio/
    ./.venv/bin/python scripts/compare_on_captured.py --wav-file debug/test_audio/technical_tradeoffs_samantha.wav
"""

import argparse
import difflib
import glob
import os
import sys
import time
from pathlib import Path
import numpy as np
import scipy.io.wavfile as wav

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
GRAY = "\033[90m"


def highlight_diff(text1: str, text2: str) -> tuple[str, str]:
    """Highlight disagreements between two strings using ANSI colors."""
    w1 = text1.split()
    w2 = text2.split()
    matcher = difflib.SequenceMatcher(None, w1, w2)

    diff1 = []
    diff2 = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            diff1.append(" ".join(w1[i1:i2]))
            diff2.append(" ".join(w2[j1:j2]))
        elif tag == "replace":
            diff1.append(f"{RED}{BOLD}{' '.join(w1[i1:i2])}{RESET}")
            diff2.append(f"{GREEN}{BOLD}{' '.join(w2[j1:j2])}{RESET}")
        elif tag == "delete":
            diff1.append(f"{RED}{BOLD}{' '.join(w1[i1:i2])}{RESET}")
        elif tag == "insert":
            diff2.append(f"{GREEN}{BOLD}{' '.join(w2[j1:j2])}{RESET}")

    return " ".join(diff1), " ".join(diff2)


def main():
    parser = argparse.ArgumentParser(description="Compare Parakeet vs Whisper transcripts on captured audio segments.")
    parser.add_argument("--session-id", help="Session ID in debug/sessions/<session_id>")
    parser.add_argument("--audio-dir", help="Directory containing .wav audio files")
    parser.add_argument("--wav-file", help="Single .wav audio file to compare")
    args = parser.parse_args()

    files = []
    if args.wav_file:
        files = [Path(args.wav_file)]
    elif args.audio_dir:
        files = sorted(Path(args.audio_dir).glob("*.wav"))
    elif args.session_id:
        p = Path(f"debug/sessions/{args.session_id}/audio")
        if not p.exists():
            p = Path(f"debug/sessions/{args.session_id}")
        files = sorted(p.glob("*.wav"))
    else:
        # Default fallback to test audio
        p = Path("debug/test_audio")
        if p.exists():
            files = sorted(p.glob("*.wav"))

    if not files:
        print(f"{YELLOW}No .wav files found for comparison.{RESET}")
        sys.exit(0)

    print(f"{BOLD}{CYAN}=== Parakeet vs. Whisper Comparative Benchmark on Captured Audio ==={RESET}")
    print(f"Found {len(files)} audio segment(s). Loading MLX models...")

    import mlx.core as mx
    import parakeet_mlx
    from parakeet_mlx.audio import get_logmel

    t0 = time.perf_counter()
    print("Loading Parakeet TDT 0.6B...")
    parakeet = parakeet_mlx.from_pretrained("mlx-community/parakeet-tdt-0.6b-v2")
    p_load_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    print("Loading Whisper Large v3 Turbo...")
    import mlx_audio.stt as stt
    whisper = stt.load_model("mlx-community/whisper-large-v3-turbo")
    w_load_ms = (time.perf_counter() - t1) * 1000

    print(f"Parakeet loaded in {p_load_ms:.0f}ms | Whisper loaded in {w_load_ms:.0f}ms\n")

    total_parakeet_time = 0.0
    total_whisper_time = 0.0
    total_duration = 0.0

    print(f"{'Segment':<35} | {'Parakeet Time':<13} | {'Whisper Time':<13} | WER Disagreement")
    print("-" * 90)

    results = []

    for f in files:
        sr, audio_raw = wav.read(f)
        if audio_raw.dtype == np.int16:
            audio_np = audio_raw.astype(np.float32) / 32768.0
        elif audio_raw.dtype == np.float32:
            audio_np = audio_raw
        else:
            audio_np = audio_raw.astype(np.float32)

        # Ensure mono
        if len(audio_np.shape) > 1:
            audio_np = audio_np.mean(axis=1)

        dur_s = len(audio_np) / float(sr)
        total_duration += dur_s

        # 1. Transcribe Parakeet
        tp0 = time.perf_counter()
        audio_mx = mx.array(audio_np, dtype=mx.float32)
        mel = get_logmel(audio_mx, parakeet.preprocessor_config)
        p_res = parakeet.generate(mel)
        p_time = (time.perf_counter() - tp0) * 1000.0
        p_text = getattr(p_res[0], "text", str(p_res[0])).strip() if p_res else ""
        total_parakeet_time += p_time

        # 2. Transcribe Whisper
        tw0 = time.perf_counter()
        w_res = whisper.generate(audio_np)
        w_time = (time.perf_counter() - tw0) * 1000.0
        w_text = getattr(w_res, "text", str(w_res)).strip()
        total_whisper_time += w_time

        diff_p, diff_w = highlight_diff(p_text, w_text)
        disagreement = p_text.lower() != w_text.lower()
        disag_label = f"{RED}DIFF{RESET}" if disagreement else f"{GREEN}MATCH{RESET}"

        print(f"{f.name:<35} | {p_time:8.1f} ms    | {w_time:8.1f} ms    | {disag_label}")
        results.append((f.name, dur_s, p_time, w_time, p_text, w_text, diff_p, diff_w))

    print("\n" + "=" * 90)
    print(f"{BOLD}DETAILED SIDE-BY-SIDE TRANSCRIPTS (Red: Parakeet diff, Green: Whisper diff){RESET}")
    print("=" * 90)

    for name, dur, pt, wt, p_raw, w_raw, p_diff, w_diff in results:
        print(f"\n{BOLD}File:{RESET} {name} ({dur:.2f}s)")
        print(f"  {CYAN}Parakeet ({pt:.0f}ms):{RESET} {p_diff}")
        print(f"  {GREEN}Whisper  ({wt:.0f}ms):{RESET} {w_diff}")

    print("\n" + "=" * 90)
    print(f"{BOLD}SUMMARY & RTF (Real-Time Factor){RESET}")
    print(f"Total Audio Duration: {total_duration:.2f} s")
    print(f"Total Parakeet Time:  {total_parakeet_time/1000.0:.2f} s (RTF = {total_parakeet_time/(total_duration*1000):.3f})")
    print(f"Total Whisper Time:   {total_whisper_time/1000.0:.2f} s (RTF = {total_whisper_time/(total_duration*1000):.3f})")
    print(f"Parakeet Speedup vs Whisper: {total_whisper_time / max(1e-3, total_parakeet_time):.2f}x faster")
    print("=" * 90)

    # Term hints capability check
    print(f"\n{BOLD}TERM HINTS SUPPORT IN PARAKEET-MLX:{RESET}")
    import inspect
    sig = inspect.signature(parakeet.generate)
    print(f"parakeet.generate signature: {sig}")
    has_term_hints = any(param in sig.parameters for param in ("prompt", "prefix", "hints", "vocabulary", "hotwords"))
    if has_term_hints:
        print("parakeet-mlx supports prefix/term hints via parameters.")
    else:
        print("parakeet-mlx does NOT support term hints or hotword biasing in its current public MLX release.")
        print("(Whisper supports `initial_prompt` or phrase prompting; Parakeet MLX currently uses greedy RNNT/TDT decoding only.)")


if __name__ == "__main__":
    main()
