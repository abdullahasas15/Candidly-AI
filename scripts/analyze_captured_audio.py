#!/usr/bin/env python3
"""R3.5 Part 0 — Offline diagnosis of captured debug sessions (no mic, no network).

Scans debug/sessions/*/ and parses each timeline.jsonl turn trace:

 1. STT finals latency (event_type STT + is_final): min / median / max + every final listed.
 2. Garble heuristics per final: Devanagari / other-script chars (ord > 0x1C00),
    consecutive 3x word repetition, ultra-short (<3 chars), punctuation-only.
 3. Turn chopping: number of STT final segments accumulated per COMMIT (candidate
    answers chopped into several finals inside one user speech window).
 4. Fallback / failure_safety events with their durations.
 5. Audio capture inventory: debug/sessions/*/audio/* (+ debug/audio_capture*) with
    size and duration (16 kHz mono s16le: bytes / 32000 = seconds). Reports if none.

Usage:
    .venv/bin/python scripts/analyze_captured_audio.py                 # readable summary
    .venv/bin/python scripts/analyze_captured_audio.py summary         # same
    .venv/bin/python scripts/analyze_captured_audio.py --json review/timeline_analysis.json

This module is import-safe: scripts/build_stt_review.py imports analyze_sessions()
to auto-fill its Findings section.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import unicodedata
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSIONS_DIR = REPO_ROOT / "debug" / "sessions"

REPEAT_3X = re.compile(r"\b(\w+)(?:[\s,.:;!?…-]+)\1(?:[\s,.:;!?…-]+)\1\b", re.IGNORECASE)
REPEAT_2X = re.compile(r"\b(\w+)(?:[\s,.:;!?…-]+)\1\b", re.IGNORECASE)
PUNCT_ONLY = re.compile(r"[\s\W_]+", re.UNICODE)


def _median(values: List[float]) -> Optional[float]:
    return round(statistics.median(values), 1) if values else None


def _latency_stats(values: List[float]) -> Dict[str, Any]:
    values = [v for v in values if v is not None and v > 0]
    if not values:
        return {"count": 0, "min": None, "median": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 1),
        "median": _median(values),
        "max": round(max(values), 1),
        "mean": round(sum(values) / len(values), 1),
    }


def _iter_events(timeline_path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    try:
        for line in timeline_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    except FileNotFoundError:
        pass
    return events


def _non_latin_hits(text: str) -> List[Dict[str, Any]]:
    """Detect Devanagari (U+0900-97F), chars with ord > 0x1C00, and any non-Latin letters."""
    hits: List[Dict[str, Any]] = []
    seen: Dict[str, Dict[str, Any]] = {}
    for ch in text or "":
        o = ord(ch)
        reason = None
        if 0x0900 <= o <= 0x097F:
            reason = "devanagari"
        elif o > 0x1C00:
            reason = f"ord>0x1C00 (U+{o:04X})"
        else:
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = ""
            if ch.isalpha() and name and not name.startswith("LATIN") and unicodedata.category(ch).startswith("L"):
                reason = name.split()[0].lower()  # e.g. cyrillic, arabic, greek
        if reason:
            key = f"{reason}:{ch}"
            if key not in seen:
                seen[key] = {"char": ch, "codepoint": f"U+{o:04X}", "reason": reason, "count": 0}
            seen[key]["count"] += 1
    hits = list(seen.values())
    return hits


def _garble_flags(text: str) -> List[Dict[str, Any]]:
    """Garble heuristics for one STT transcript. Returns a list of flags with detail."""
    flags: List[Dict[str, Any]] = []
    clean = (text or "").strip()
    if not clean:
        return [{"flag": "empty", "detail": "empty transcript"}]

    scripts = _non_latin_hits(clean)
    if scripts:
        sample = ", ".join(f"{h['char']} x{h['count']}" for h in scripts[:6])
        flags.append({"flag": "other_script_chars", "detail": sample})

    m = REPEAT_3X.search(clean)
    if m:
        flags.append({"flag": "word_repeated_3x", "detail": f"'{m.group(1)}' repeated 3x consecutively"})
    else:
        # Soft signal: consecutive word repeated 2x (stutter/restart behaviour),
        # weaker than the 3x garble rule above but very visible in real captures.
        for m2 in REPEAT_2X.finditer(clean):
            flags.append({"flag": "word_repeated_2x", "detail": f"'{m2.group(1)}' repeated 2x consecutively"})

    if len(clean) < 3:
        flags.append({"flag": "ultra_short", "detail": f"len={len(clean)} chars (<3)"})

    if PUNCT_ONLY.sub("", clean) == "":
        flags.append({"flag": "punctuation_only", "detail": "no letters/digits"})

    return flags


def _analyze_session(session_dir: Path) -> Dict[str, Any]:
    timeline_path = session_dir / "timeline.jsonl"
    events = _iter_events(timeline_path)

    first_ts: Optional[float] = min((e.get("timestamp") for e in events if isinstance(e.get("timestamp"), (int, float))), default=None)
    last_ts: Optional[float] = max((e.get("timestamp") for e in events if isinstance(e.get("timestamp"), (int, float))), default=None)
    event_counts: Dict[str, int] = {}
    for e in events:
        t = str(e.get("event_type", "?"))
        event_counts[t] = event_counts.get(t, 0) + 1

    # -- 1. STT finals -----------------------------------------------------
    finals: List[Dict[str, Any]] = []
    interims: List[Dict[str, Any]] = []
    for e in events:
        et = str(e.get("event_type", "")).upper()
        stage = str(e.get("stage", "")).upper()
        lane = str(e.get("lane", ""))
        is_stt = "STT" in et or "STT" in stage
        if not is_stt:
            continue
        is_final = e.get("is_final")
        if is_final is None:
            is_final = any(str(k).lower() == "final" for k in e.keys() if e.get(k))
            stage_has_final = "FINAL" in stage or "FINAL" in str(e.get("status", "")).upper()
            is_final = is_final or stage_has_final
        item = {
            "ts": e.get("timestamp"),
            "lane": lane or None,
            "text": str(e.get("text", "")),
            "latency_ms": e.get("latency_ms"),
            "seq": e.get("seq"),
        }
        if bool(is_final):
            finals.append(item)
        else:
            interims.append(item)

    final_latencies = [f["latency_ms"] for f in finals if isinstance(f.get("latency_ms"), (int, float))]
    by_lane: Dict[str, Dict[str, Any]] = {}
    for f in finals:
        lane_key = f["lane"] or "unknown"
        entry = by_lane.setdefault(lane_key, {"count": 0, "latency_ms": {"count": 0, "min": None, "median": None, "max": None, "mean": None}, "latencies": []})
        entry["count"] += 1
        if isinstance(f.get("latency_ms"), (int, float)):
            entry["latencies"].append(f["latency_ms"])
    for lane_key, entry in by_lane.items():
        entry["latency_ms"] = _latency_stats(entry.pop("latencies"))

    # -- 2. Garble heuristics per final ------------------------------------
    garbled_flags: Dict[str, List[Dict[str, Any]]] = {}
    garbled_final_count = 0
    garbled_finals: List[Dict[str, Any]] = []
    for idx, f in enumerate(finals):
        flags = _garble_flags(f["text"])
        if flags:
            garbled_final_count += 1
            garbled_finals.append({"index": idx, "text": f["text"], "lane": f["lane"], "latency_ms": f["latency_ms"], "flags": flags})
            for fl in flags:
                garbled_flags.setdefault(fl["flag"], []).append({"text": f["text"], "index": idx, "detail": fl["detail"]})

    interim_script_hits: List[Dict[str, Any]] = []
    for item in interims:
        hits = _non_latin_hits(item["text"])
        if hits:
            interim_script_hits.append({"text": item["text"], "lane": item["lane"], "scripts": [h["reason"] for h in hits]})

    # -- 3. Turn chopping: finals per commit window ------------------------
    # Walk chronologically; STT finals accumulate between COMMITS and are then
    # attributed to the commit that closes the user speech window.
    finals_per_commit: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    for e in events:
        et = str(e.get("event_type", "")).upper()
        if et == "STT" and e.get("is_final") is True:
            pending.append({"seq": e.get("seq"), "text": str(e.get("text", "")), "latency_ms": e.get("latency_ms")})
        elif et == "COMMIT":
            finals_per_commit.append({
                "turn_id": e.get("turn_id"),
                "reason": e.get("reason"),
                "commit_ts": e.get("timestamp"),
                "word_count": e.get("word_count"),
                "full_answer": str(e.get("full_answer", "")),
                "final_count": len(pending),
                "seqs": [f["seq"] for f in pending],
                "final_latency_ms": [f["latency_ms"] for f in pending],
                "finals": pending,
            })
            pending = []
    if pending:
        finals_per_commit.append({"turn_id": None, "reason": "no_commit_after", "commit_ts": None, "word_count": None, "full_answer": None,
                                  "final_count": len(pending), "seqs": [f["seq"] for f in pending],
                                  "final_latency_ms": [f["latency_ms"] for f in pending], "finals": pending})

    committed_groups = [g for g in finals_per_commit if g.get("reason") != "no_commit_after"]
    with_finals = [g for g in committed_groups if g["final_count"] > 0]
    chopped = [g for g in with_finals if g["final_count"] > 1]
    max_in_one = max((g["final_count"] for g in with_finals), default=0)

    # -- 4. Fallback / failure_safety events --------------------------------
    LOOKUP_FIELDS = ("event_type", "stage", "provider", "model", "lane", "action", "reason", "status", "degraded", "meta")
    fallbacks: List[Dict[str, Any]] = []
    for e in events:
        hay = " ".join(str(e.get(f, "")) for f in LOOKUP_FIELDS).lower()
        if "fallback" in hay or "failure_safety" in hay or e.get("degraded") is True:
            fallbacks.append({
                "ts": e.get("timestamp"),
                "event_type": e.get("event_type"),
                "provider": e.get("provider"),
                "model": e.get("model"),
                "latency_ms": e.get("latency_ms"),
                "degraded": e.get("degraded"),
                "action": e.get("reason") or e.get("action"),
                "spoken_reply": (e.get("decision") or {}).get("spoken_reply") if isinstance(e.get("decision"), dict) else None,
            })
    fallback_total_ms = sum(float(f.get("latency_ms") or 0) for f in fallbacks)

    # -- 5. Audio capture inventory ----------------------------------------
    audio_files: List[Dict[str, Any]] = []
    audio_dir = session_dir / "audio"
    if audio_dir.exists():
        for p in sorted(audio_dir.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() == ".wav":
                try:
                    with wave.open(str(p), "rb") as wf:
                        dur = wf.getnframes() / max(wf.getframerate(), 1)
                        size = p.stat().st_size
                except Exception:
                    dur = p.stat().st_size / 32000.0
                    size = p.stat().st_size
            else:
                size = p.stat().st_size
                dur = size / 32000.0  # 16 kHz mono s16le: bytes/32000 = seconds
            audio_files.append({"file": p.name, "bytes": size, "duration_s": round(dur, 2)})

    return {
        "session_id": session_dir.name,
        "dir": str(session_dir),
        "timeline_exists": timeline_path.exists(),
        "timeline_lines": len(events),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "duration_s": round(last_ts - first_ts, 1) if (first_ts is not None and last_ts is not None) else None,
        "event_counts": event_counts,
        "stt_interims": {
            "count": len(interims),
            "items": interims,
        },
        "stt_finals": {
            "count": len(finals),
            "latency_ms": _latency_stats(final_latencies),
            "by_lane": by_lane,
            "items": finals,
        },
        "garble": {
            "garbled_final_count": garbled_final_count,
            "garbled_final_rate": round(garbled_final_count / len(finals), 3) if finals else 0.0,
            "flags": garbled_flags,
            "garbled_finals": garbled_finals,
            "garbled_interim_script_examples": interim_script_hits,
        },
        "turn_chopping": {
            "commit_count": len(committed_groups),
            "groups": finals_per_commit,
            "commits_with_finals": len(with_finals),
            "chopped_commit_count": len(chopped),
            "chopped_commit_ratio": round(len(chopped) / len(with_finals), 3) if with_finals else 0.0,
            "max_finals_in_one_commit": max_in_one,
            "avg_finals_per_commit": round(sum(g["final_count"] for g in with_finals) / len(with_finals), 2) if with_finals else 0.0,
        },
        "fallbacks": {
            "count": len(fallbacks),
            "total_ms": round(fallback_total_ms, 1),
            "events": fallbacks,
        },
        "audio": {
            "files": audio_files,
            "count": len(audio_files),
            "total_bytes": sum(a["bytes"] for a in audio_files),
            "total_duration_s": round(sum(a["duration_s"] for a in audio_files), 2),
            "capture_wired": len(audio_files) > 0,
        },
    }


def analyze_sessions(sessions_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Analyze all sessions under sessions_dir (import-safe main entry point)."""
    base = Path(sessions_dir) if sessions_dir else DEFAULT_SESSIONS_DIR
    session_dirs = sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []
    sessions = [_analyze_session(p) for p in session_dirs]

    # Extra legacy capture locations (debug/audio_capture* anywhere under debug/).
    extras: List[Dict[str, Any]] = []
    debug_root = base.parent if base.name == "sessions" else base
    audiocap_paths = list(debug_root.glob("audio_capture*/")) if debug_root.exists() else []
    for d in audiocap_paths:
        for p in sorted(d.iterdir()):
            if p.is_file():
                dur = p.stat().st_size / 32000.0
                extras.append({"path": str(p), "bytes": p.stat().st_size, "duration_s": round(dur, 2)})

    tot_finals = sum(s["stt_finals"]["count"] for s in sessions)
    tot_audio = sum(s["audio"]["count"] for s in sessions) + len(extras)
    aggregate = {
        "sessions_scanned": len(sessions),
        "sessions_with_timeline": sum(1 for s in sessions if s["timeline_exists"]),
        "timeline_events_total": sum(s["timeline_lines"] for s in sessions),
        "stt_finals_total": tot_finals,
        "stt_final_latency_ms": _latency_stats([f["latency_ms"] for s in sessions for f in s["stt_finals"]["items"] if isinstance(f.get("latency_ms"), (int, float))]),
        "garbled_finals_total": sum(s["garble"]["garbled_final_count"] for s in sessions),
        "chopped_commits_total": sum(s["turn_chopping"]["chopped_commit_count"] for s in sessions),
        "fallback_events_total": sum(s["fallbacks"]["count"] for s in sessions),
        "fallback_total_ms": round(sum(s["fallbacks"]["total_ms"] for s in sessions), 1),
        "audio_files_total": tot_audio,
        "extra_capture_files": extras,
    }
    return {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "base_dir": str(base), "totals": aggregate, "sessions": sessions}


def print_report(analysis: Dict[str, Any]) -> None:
    t = analysis["totals"]
    line = "=" * 78
    print(line)
    print("CAPTURED-SESSION OFFLINE DIAGNOSIS (Part 0)  —  offline, no mic, no network")
    print(f"base: {analysis['base_dir']}   generated: {analysis['generated_at']}")
    print(line)
    print(f"sessions scanned: {t['sessions_scanned']} (with timeline: {t['sessions_with_timeline']}) | "
          f"timeline events: {t['timeline_events_total']} | audio files: {t['audio_files_total']}")
    if t["stt_final_latency_ms"]["count"]:
        lat = t["stt_final_latency_ms"]
        print(f"STT finals: {t['stt_finals_total']} | latency ms  min {lat['min']} / median {lat['median']} / max {lat['max']}")
    if t["extra_capture_files"]:
        print("extra capture dirs found:")
        for f in t["extra_capture_files"]:
            print(f"    {f['path']}  {f['bytes']}B  {f['duration_s']}s")
    print()

    for s in analysis["sessions"]:
        print("-" * 78)
        print(f"SESSION {s['session_id']}")
        print("-" * 78)
        if not s["timeline_exists"]:
            print("  timeline.jsonl missing — nothing to analyze.")
        counts = "  ".join(f"{k}:{v}" for k, v in sorted(s["event_counts"].items())) or "-"
        print(f"  events ({s['timeline_lines']}): {counts}")

        sf = s["stt_finals"]
        print(f"\n  1) STT finals: {sf['count']}")
        if sf["count"]:
            lat = sf["latency_ms"]
            print(f"     latency ms: min {lat['min']} / median {lat['median']} / max {lat['max']} (mean {lat['mean']})")
            for lane, le in sorted((sf.get("by_lane") or {}).items()):
                l2 = le["latency_ms"]
                print(f"       {lane}: {le['count']} finals, latency median {l2['median']} ms, max {l2['max']}")
            for f in sf["items"]:
                print(f"       seq={f['seq']} lane={f['lane']} lat={f['latency_ms']}ms  \"{f['text']}\"")

        g = s["garble"]
        print(f"\n  2) Garble: {g['garbled_final_count']}/{sf['count']} finals flagged")
        for flag, entries in sorted(g["flags"].items()):
            first = entries[0]
            print(f"       {flag}: {len(entries)}  e.g. \"{first['text'][:60]}\" ({first['detail']})")
        for ex in g["garbled_interim_script_examples"]:
            print(f"       (interim w/ non-Latin script, lane={ex['lane']}): \"{ex['text'][:60]}\"")

        ch = s["turn_chopping"]
        print(f"\n  3) Turn chopping: commits={ch['commit_count']} commits_with_finals={ch['commits_with_finals']} "
              f"chopped(>1 final)={ch['chopped_commit_count']} max_finals_in_one_commit={ch['max_finals_in_one_commit']} "
              f"avg={ch['avg_finals_per_commit']}")
        for gp in ch["groups"]:
            mark = "  <-- chopped" if gp["final_count"] > 1 and gp.get("turn_id") else ""
            print(f"       turn {gp.get('turn_id')} ({gp.get('reason') or 'no_commit_after'}): {gp['final_count']} final(s), seqs={gp['seqs']}{mark}")

        fb = s["fallbacks"]
        print(f"\n  4) Fallback / failure_safety: {fb['count']} events, total {fb['total_ms']} ms")
        for f in fb["events"]:
            print(f"       {f['event_type']}: provider={f['provider']} model={f['model']} latency={f['latency_ms']}ms degraded={f['degraded']}")

        a = s["audio"]
        print(f"\n  5) Audio capture: {a['count']} file(s), {a['total_duration_s']}s, {a['total_bytes']}B")
        for f in a["files"]:
            print(f"       {f['file']}: {f['bytes']}B  {f['duration_s']}s")
        if a["count"] == 0:
            print("       NOTE: no captured audio — audio segment capture was wired only in R3.5;")
        print()
    print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline diagnosis of captured debug sessions.")
    parser.add_argument("command", nargs="?", default="summary", choices=["summary"], help="summary (default) prints the report")
    parser.add_argument("--json", metavar="PATH", help="also dump the analysis as JSON to PATH")
    parser.add_argument("--sessions-dir", default=str(DEFAULT_SESSIONS_DIR), help="override sessions base dir")
    args = parser.parse_args()

    analysis = analyze_sessions(Path(args.sessions_dir))
    if args.command == "summary":
        print_report(analysis)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON analysis written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
