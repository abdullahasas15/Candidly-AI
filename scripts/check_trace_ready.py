#!/usr/bin/env python3
"""scripts/check_trace_ready.py

Checks development debug trace and audio capture flag status and output directories.
Auto-deletes captured audio older than 3 days as per development privacy policy.

Usage:
    python scripts/check_trace_ready.py
"""

import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

# ANSI formatting
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"


def check_and_cleanup_old_sessions(base_dir: Path, max_age_days: float = 3.0) -> int:
    """Auto-deletes audio and trace sessions older than max_age_days."""
    if not base_dir.exists():
        return 0
    now = time.time()
    max_age_secs = max_age_days * 86400
    cleaned_count = 0

    for item in base_dir.iterdir():
        if item.is_dir():
            mtime = item.stat().st_mtime
            if (now - mtime) > max_age_secs:
                for subfile in item.rglob("*"):
                    if subfile.is_file():
                        try:
                            subfile.unlink()
                        except Exception:
                            pass
                try:
                    item.rmdir()
                    cleaned_count += 1
                except Exception:
                    pass
    return cleaned_count


def main():
    turn_trace_env = os.getenv("DEBUG_TURN_TRACE", "0")
    audio_capture_env = os.getenv("DEBUG_AUDIO_CAPTURE", "0")

    turn_trace_ready = turn_trace_env in ("1", "true", "True", "yes")
    audio_capture_ready = audio_capture_env in ("1", "true", "True", "yes")

    sessions_dir = Path("debug/sessions").resolve()
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Run auto-delete for sessions older than 3 days
    cleaned = check_and_cleanup_old_sessions(sessions_dir, max_age_days=3.0)

    print("=" * 80)
    print(f"{BOLD}{CYAN}CANDIDLY DEV DEBUG TRACE & AUDIO CAPTURE STATUS{RESET}")
    print("=" * 80)
    print(f"DEBUG_TURN_TRACE   : {GREEN + 'ENABLED (1)' if turn_trace_ready else YELLOW + 'DISABLED (0)'}{RESET}")
    print(f"DEBUG_AUDIO_CAPTURE: {GREEN + 'ENABLED (1)' if audio_capture_ready else YELLOW + 'DISABLED (0)'}{RESET}")
    print(f"Output Directory   : {sessions_dir}")
    print(f"Directory Exists   : {GREEN + 'YES' if sessions_dir.exists() else YELLOW + 'NO'}{RESET}")
    
    existing_sessions = [d.name for d in sessions_dir.iterdir() if d.is_dir()]
    print(f"Active Sessions    : {len(existing_sessions)}")
    if existing_sessions:
        for s in existing_sessions[-5:]:
            print(f"  - {s}")
    if cleaned > 0:
        print(f"Auto-deleted       : {cleaned} session(s) older than 3 days")
    print(f"Retention Policy   : Local only, 3 days max retention, strict zero production deployment")
    print("=" * 80)


if __name__ == "__main__":
    main()
