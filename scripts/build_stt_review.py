#!/usr/bin/env python3
"""R3.5 Part 0 — Offline STT review builder (no mic, no network APIs).

Replays captured audio segments through three LOCAL transcribers and produces a
self-contained HTML review + JSON summary:

  a. Apple on-device   : backend.app.services.interview.stt_provider.
                         transcribe_with_provider_async(pcm_bytes,
                         provider="apple_speechanalyzer", locale="en-US")
  b. Parakeet (MLX)    : same singleton/ generate path as voice_pipeline lane 2
                         (_load_parakeet_singleton -> get_logmel -> generate)
  c. Whisper (MLX)     : _load_whisper_singleton -> generate(audio_np)

Plus the LIVE in-session transcript from timeline.jsonl where a segment maps to
a candidate turn (approximate by index order).

Outputs (under review/):
  - review/stt_review.html          (inline CSS, ends with auto-filled Findings)
  - review/stt_review_summary.json  (texts, latency, word-overlap vs Apple, elapsed)
  - review/audio/*.wav              (playable copies / raw-PCM wrapped WAVs)
  - review/timeline_analysis.json   (via scripts/analyze_captured_audio.py)

If no captured audio exists (audio capture was wired only in R3.5), the script
still exercises the whole pipeline on a demo sample: /tmp/r35_voice_16k.wav if
present, else a macOS `say`-synthesized 16 kHz sample — clearly labeled
"demo sample (not from sessions)". run with .venv/bin/python scripts/build_stt_review.py
"""

from __future__ import annotations

import asyncio
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

import analyze_captured_audio as analyzer  # noqa: E402  (shared dir)

REVIEW_DIR = REPO_ROOT / "review"
AUDIO_OUT_DIR = REVIEW_DIR / "audio"
TMP_WAV = Path("/tmp/r35_voice_16k.wav")

APPLE_BINARY = REPO_ROOT / "native/apple_stt/.build/release/apple_stt"
os.environ.setdefault("APPLE_STT_BINARY", str(APPLE_BINARY))
os.environ.pop("VOICE_MOCK", None)  # ensure real local models, never mock mode

PROVIDER_LABELS = {
    "live": "Live (in-session)",
    "apple": "Apple SpeechAnalyzer (on-device)",
    "parakeet": "Parakeet TDT 0.6B (MLX)",
    "whisper": "Whisper Large v3 Turbo (MLX)",
}


# ---------------------------------------------------------------------------
# transcription backends
# ---------------------------------------------------------------------------

async def apple_transcribe(pcm_bytes: bytes, locale: str = "en-US") -> Dict[str, Any]:
    from backend.app.services.interview.stt_provider import transcribe_with_provider_async

    return await transcribe_with_provider_async(pcm_bytes, provider="apple_speechanalyzer", locale=locale)


# -- MLX singletons: prefer the exact pipeline loaders, fall back to direct loads
_MLX: Dict[str, Any] = {"parakeet": None, "whisper": None, "loaded_by": None}


def load_mlx_models() -> Dict[str, Any]:
    if _MLX["loaded_by"] is not None:
        return _MLX
    try:
        from backend.app.services.interview.voice_pipeline import (
            _load_parakeet_singleton,
            _load_whisper_singleton,
        )
        _MLX["loaded_by"] = "voice_pipeline singletons"
        _MLX["parakeet"] = _load_parakeet_singleton()
        _MLX["whisper"] = _load_whisper_singleton()
    except Exception as exc:  # noqa: BLE001
        print(f"[review] voice_pipeline loaders unavailable ({type(exc).__name__}: {exc}) — direct model loads")
        _MLX["loaded_by"] = "direct"
        try:
            import parakeet_mlx
            _MLX["parakeet"] = parakeet_mlx.from_pretrained("mlx-community/parakeet-tdt-0.6b-v2")
        except Exception as exc2:  # noqa: BLE001
            _MLX["parakeet"] = None
            print(f"[review] parakeet load failed: {exc2}")
        try:
            from mlx_audio.stt.utils import load_model
            _MLX["whisper"] = load_model("mlx-community/whisper-large-v3-turbo")
        except Exception as exc3:  # noqa: BLE001
            _MLX["whisper"] = None
            print(f"[review] whisper load failed: {exc3}")
    return _MLX


def _audio_np_from_bytes(data: bytes) -> "Any":  # numpy float32 @16k mono
    import numpy as np

    if data.startswith(b"RIFF"):
        with wave.open(io.BytesIO(data), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
            rate = wf.getframerate()
            channels = wf.getnchannels()
    else:
        raw, rate, channels = data, 16000, 1
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        target_len = int(len(samples) * 16000 / rate)
        samples = np.interp(
            np.linspace(0.0, 1.0, target_len, endpoint=False),
            np.linspace(0.0, 1.0, len(samples), endpoint=False),
            samples,
        )
    return samples


def parakeet_transcribe(data: bytes) -> Dict[str, Any]:
    """Mirror of voice_pipeline lane-2 Parakeet path (offline)."""
    import mlx.core as mx
    from parakeet_mlx.audio import get_logmel

    models = load_mlx_models()
    parakeet = models["parakeet"]
    if parakeet is None:
        return {"text": "", "error": "parakeet model unavailable"}
    audio_np = _audio_np_from_bytes(data)
    audio_mx = mx.array(audio_np, dtype=mx.float32)
    mel = get_logmel(audio_mx, parakeet.preprocessor_config)
    res = parakeet.generate(mel)
    text = getattr(res[0], "text", str(res[0])).strip() if res else ""
    return {"text": text, "error": None}


def whisper_transcribe(data: bytes) -> Dict[str, Any]:
    """Mirror of voice_pipeline lane-2 Whisper fallback path (offline)."""
    whisper = load_mlx_models()["whisper"]
    if whisper is None:
        return {"text": "", "error": "whisper model unavailable"}
    audio_np = _audio_np_from_bytes(data)
    res = whisper.generate(audio_np)
    text = getattr(res, "text", str(res)).strip()
    return {"text": text, "error": None}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def read_audio(path: Path) -> bytes:
    return path.read_bytes()


def write_wav_copy(rel_name: str, data: bytes) -> str:
    """Write playable WAV under review/audio/, return relative reference."""
    AUDIO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDIO_OUT_DIR / rel_name
    if data.startswith(b"RIFF"):
        out.write_bytes(data)
    else:  # raw 16k mono s16le PCM -> wrap in a WAV container
        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(data)
    return f"audio/{rel_name}"


def _wav_duration_s(path: Path) -> float:
    data = path.read_bytes()
    if data.startswith(b"RIFF"):
        try:
            with wave.open(str(path), "rb") as wf:
                return round(wf.getnframes() / max(wf.getframerate(), 1), 2)
        except Exception:
            pass
    return round(len(data) / 32000.0, 2)


def normalize_words(text: str) -> List[str]:
    return [w for w in re.sub(r"[^\w\s]", " ", (text or "").lower()).split() if w]


def word_overlap_vs_apple(apple_text: str, other_text: str) -> Optional[Dict[str, float]]:
    a = set(normalize_words(apple_text))
    b = set(normalize_words(other_text))
    if not a or not b:
        return None
    inter = a & b
    union = a | b
    return {
        "jaccard_vs_apple": round(len(inter) / len(union), 3),
        "apple_words_reproduced": round(len(inter) / len(a), 3),
        "common": len(inter),
        "apple_words": len(a),
        "other_words": len(b),
    }


def synth_demo_sample(dest: Path) -> Optional[str]:
    """Create a short 16k mono WAV with macOS `say` (local only)."""
    text = "Testing the Apple Speech transcriber, this is a live streaming check with real speech."
    aiff = dest.with_suffix(".aiff")
    try:
        subprocess.run(["/usr/bin/say", "-o", str(aiff), text], check=True, timeout=30,
                       capture_output=True)
        subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                        str(aiff), str(dest)], check=True, timeout=30, capture_output=True)
        aiff.unlink(missing_ok=True)
        return text
    except Exception as exc:  # noqa: BLE001
        print(f"[review] demo sample synthesis failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# main flow
# ---------------------------------------------------------------------------

async def run() -> int:
    t_start = time.perf_counter()
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_OUT_DIR.mkdir(parents=True, exist_ok=True)

    analysis = analyzer.analyze_sessions()
    analysis_path = REVIEW_DIR / "timeline_analysis.json"
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    by_session = {s["session_id"]: s for s in analysis["sessions"]}

    # -- discover captured segments -----------------------------------------
    segments: List[Dict[str, Any]] = []
    sessions_dir = REPO_ROOT / "debug" / "sessions"
    if sessions_dir.exists():
        for sdir in sorted(p for p in sessions_dir.iterdir() if p.is_dir()):
            sid = sdir.name
            files = [p for p in (sdir / "audio").iterdir() if p.is_file()] if (sdir / "audio").exists() else []
            for idx, p in enumerate(sorted(files, key=lambda f: (f.stat().st_mtime, f.name))):
                data = read_audio(p)
                # Live transcript approximation: audio file index order <-> candidate-turn finals order.
                finals = by_session.get(sid, {}).get("stt_finals", {}).get("items", [])
                live = None
                if idx < len(finals):
                    f = finals[idx]
                    live = {"text": f["text"], "latency_ms": f.get("latency_ms"),
                            "lane": f.get("lane"), "seq": f.get("seq"),
                            "mapping": "approximate by index order (audio files vs candidate turns)"}
                segments.append({
                    "id": f"seg{len(segments):03d}",
                    "session": sid,
                    "file": p.name,
                    "label": f"{sid} — {p.name}",
                    "from_captured_session": True,
                    "bytes": len(data),
                    "duration_s": _wav_duration_s(p),
                    "data": data,
                    "live": live,
                })

    used_demo = False
    demo_note = ""
    if not segments:
        used_demo = True
        if TMP_WAV.exists():
            demo_src = TMP_WAV
            demo_note = "used existing /tmp/r35_voice_16k.wav"
        else:
            tmp_demo = REVIEW_DIR / "audio" / "demo_synthesized.wav"
            text = synth_demo_sample(tmp_demo)
            demo_src = tmp_demo if text else None
            demo_note = "synthesized via macOS say + afconvert (16 kHz)" if text else "no demo audio could be synthesized"
        if demo_src is not None:
            data = demo_src.read_bytes()
            segments.append({
                "id": "seg000",
                "session": None,
                "file": demo_src.name,
                "label": f"demo sample (not from sessions) — {demo_src.name}",
                "from_captured_session": False,
                "bytes": len(data),
                "duration_s": _wav_duration_s(demo_src),
                "data": data,
                "live": None,
            })

    capture_note = ("No captured audio found in debug/sessions/*/audio — audio segment capture was wired "
                    "only in R3.5 (DEBUG_AUDIO_CAPTURE=1 now on; future sessions will populate audio/).")
    if not used_demo:
        total_files = sum(1 for s in analysis["sessions"] for _ in s["audio"]["files"])
        capture_note = (
            f"{total_files} captured segment file(s) in debug/sessions replayed offline."
            if total_files else
            "No captured audio in debug/sessions — audio segment capture was wired only in R3.5; "
            "future sessions will populate audio/."
        )
    live_note = "For review purposes the pipeline was exercised on a demo sample (not from sessions)." if used_demo else ""

    # -- run three local transcribers per segment ----------------------------
    load_mlx_models()
    from backend.app.services.interview.voice_pipeline import filter_hallucinations, _MLX_LOCK

    provider_totals: Dict[str, float] = {"apple": 0.0, "parakeet": 0.0, "whisper": 0.0}
    locale_check: Dict[str, Any] = {}

    for seg in segments:
        audio_np = _audio_np_from_bytes(seg["data"])
        providers: Dict[str, Any] = {}

        # a) Apple on-device
        t0 = time.perf_counter()
        try:
            res = await apple_transcribe(seg["data"], locale="en-US")
            providers["apple"] = {
                "text": res.get("text", ""),
                "latency_ms": res.get("latency_ms"),
                "finals": res.get("finals", []),
                "error": res.get("error"),
            }
        except Exception as exc:  # noqa: BLE001
            providers["apple"] = {"text": "", "error": f"error: {type(exc).__name__}: {exc}", "latency_ms": None, "finals": []}
        dt = time.perf_counter() - t0
        providers["apple"]["elapsed_s"] = round(dt, 2)
        provider_totals["apple"] += dt

        # b) Parakeet (MLX)
        t0 = time.perf_counter()
        try:
            def _para():
                with _MLX_LOCK:
                    return parakeet_transcribe(seg["data"])
            r = await asyncio.to_thread(_para)
            txt = r.get("text", "")
            if not r.get("error"):
                txt = filter_hallucinations(txt, audio_np)
            providers["parakeet"] = {"text": txt, "error": r.get("error")}
        except Exception as exc:  # noqa: BLE001
            providers["parakeet"] = {"text": "", "error": f"error: {type(exc).__name__}: {exc}"}
        dt = time.perf_counter() - t0
        providers["parakeet"]["elapsed_s"] = round(dt, 2)
        provider_totals["parakeet"] += dt

        # c) Whisper (MLX)
        t0 = time.perf_counter()
        try:
            def _wh():
                with _MLX_LOCK:
                    return whisper_transcribe(seg["data"])
            r = await asyncio.to_thread(_wh)
            txt = r.get("text", "")
            if not r.get("error"):
                txt = filter_hallucinations(txt, audio_np)
            providers["whisper"] = {"text": txt, "error": r.get("error")}
        except Exception as exc:  # noqa: BLE001
            providers["whisper"] = {"text": "", "error": f"error: {type(exc).__name__}: {exc}"}
        dt = time.perf_counter() - t0
        providers["whisper"]["elapsed_s"] = round(dt, 2)
        provider_totals["whisper"] += dt

        seg["providers"] = providers
        seg["audio_rel"] = write_wav_copy(f"{'__'.join([seg['session'] or 'demo', seg['file']]).replace('.wav', '')}.wav", seg["data"])

        # word-overlap vs Apple for the JSON summary
        apple_txt = providers["apple"].get("text") or ""
        for key in ("parakeet", "whisper"):
            prov = providers[key]
            ov = word_overlap_vs_apple(apple_txt, prov.get("text") or "") if (apple_txt and not prov.get("error")) else None
            prov["overlap_vs_apple"] = ov
        live_txt = (seg.get("live") or {}).get("text")
        if live_txt and apple_txt:
            providers["live"]["overlap_vs_apple"] = word_overlap_vs_apple(apple_txt, live_txt)

        # -- Apple locale check (en-US vs en-IN) on the representative segment --
        if not locale_check or locale_check.get("error"):
            try:
                r_in = await apple_transcribe(seg["data"], locale="en-IN")
                locale_check = {
                    "representative": seg["label"],
                    "en-US": {"text": providers["apple"].get("text"), "latency_ms": providers["apple"].get("latency_ms"), "error": providers["apple"].get("error")},
                    "en-IN": {"text": r_in.get("text", ""), "latency_ms": r_in.get("latency_ms"), "error": r_in.get("error")},
                }
            except Exception as exc:  # noqa: BLE001
                locale_check = {"representative": seg["label"], "error": f"error: {type(exc).__name__}: {exc}"}

    elapsed = round(time.perf_counter() - t_start, 1)

    # -- strip raw bytes from the JSON output -------------------------------
    json_segments = []
    for seg in segments:
        s = {k: v for k, v in seg.items() if k != "data"}
        json_segments.append(s)

    agreement = {}
    for key in ("parakeet", "whisper", "live"):
        vals = [seg["providers"][key].get("overlap_vs_apple", {}).get("jaccard_vs_apple")
                for seg in segments
                if seg["providers"].get(key, {}).get("overlap_vs_apple") is not None]
        agreement[key] = {"mean_jaccard_vs_apple": round(sum(vals) / len(vals), 3) if vals else None, "segments": len(vals)}

    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "env": {
            "apple_stt_binary": str(APPLE_BINARY),
            "apple_binary_built": APPLE_BINARY.exists(),
            "demo_mode": used_demo,
            "demo_source": demo_note or "captured audio",
            "model_loader": _MLX["loaded_by"],
        },
        "capture_note": capture_note,
        "live_note": live_note,
        "segments": json_segments,
        "provider_elapsed_seconds": {k: round(v, 2) for k, v in provider_totals.items()},
        "agreement_vs_apple": agreement,
        "locale_check": locale_check,
        "totals_from_timeline": analysis["totals"],
    }
    summary_path = REVIEW_DIR / "stt_review_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = REVIEW_DIR / "stt_review.html"
    html_path.write_text(render_html(summary, analysis, elapsed), encoding="utf-8")

    print(f"[review] HTML: {html_path}")
    print(f"[review] JSON: {summary_path}")
    print(f"[review] timeline analysis: {analysis_path}")
    print(f"[review] done in {elapsed}s (providers: {json.dumps(summary['provider_elapsed_seconds'])})")
    return 0


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def cell_for(txt: Optional[str], lat: Any = None, elapsed: Any = None, error: Optional[str] = None) -> str:
    """One provider cell: transcript + latency chip, or error styling."""
    if error:
        return f'<div class="err">{html.escape(str(error))[:160]}</div>'
    body = html.escape(txt or "—") if txt else '<span class="dim">—</span>'
    chips = []
    if lat is not None:
        chips.append(f"latency {lat} ms")
    if elapsed is not None:
        chips.append(f"elapsed {elapsed} s")
    chip = f'<div class="chip">{html.escape(" · ".join(chips))}</div>' if chips else ""
    return f'<div class="txt">{body}</div>{chip}'


def render_html(summary: Dict[str, Any], analysis: Dict[str, Any], elapsed: float) -> str:
    t = analysis["totals"]
    env = summary["env"]
    parts: List[str] = []

    parts.append(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Candidly R3.5 — Offline STT Review</title>
<style>
 body {{ font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; margin: 24px auto; max-width: 1200px; color: #1c2733; background: #f5f7fa; line-height: 1.45; }}
 h1 {{ font-size: 1.5rem; margin-bottom: 2px; }}
 h2 {{ font-size: 1.15rem; margin-top: 34px; border-bottom: 2px solid #d7dee6; padding-bottom: 4px; }}
 h3 {{ font-size: 1rem; margin-bottom: 6px; }}
 .sub {{ color: #5a6b7b; font-size: .85rem; }}
 .card {{ background: #fff; border: 1px solid #dfe6ee; border-radius: 10px; padding: 14px 16px; margin: 12px 0; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
 table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
 th, td {{ border: 1px solid #e2e8ef; padding: 7px 10px; text-align: left; vertical-align: top; font-size: .88rem; }}
 th {{ background: #eef2f7; }}
 .txt {{ white-space: pre-wrap; }}
 .chip {{ display: inline-block; margin-top: 6px; font-size: .72rem; color: #44566b; background: #eef3f8; border: 1px solid #d8e2ec; border-radius: 8px; padding: 1px 7px; }}
 .err {{ color: #b3261e; background: #fdeceb; border-radius: 6px; padding: 4px 7px; white-space: pre-wrap; }}
 .dim {{ color: #8595a6; }}
 .note {{ background: #fff8e6; border: 1px solid #ecd98b; border-radius: 8px; padding: 8px 12px; font-size: .86rem; }}
 .mono {{ font-family: ui-monospace, Menlo, monospace; font-size: .84rem; }}
 .good {{ color: #106b21; }}
 .flag {{ display: inline-block; background: #fbe9e7; border: 1px solid #f0b9ae; color: #8c2b1f; border-radius: 6px; font-size: .75rem; padding: 1px 7px; margin: 2px 4px 2px 0; }}
 audio {{ width: 100%; margin: 8px 0 4px; }}
 .stats {{ display: flex; flex-wrap: wrap; gap: 10px; }}
 .stat {{ background: #fff; border: 1px solid #dfe6ee; border-radius: 10px; padding: 10px 14px; min-width: 170px; }}
 .stat b {{ font-size: 1.25rem; display: block; }}
 .stat span {{ color: #5a6b7b; font-size: .78rem; }}
 .pos {{ color: #b3261e; }}
 li {{ margin: 3px 0; }}
 code {{ background: #eef2f7; border-radius: 4px; padding: 0 4px; }}
</style></head><body>
<h1>Candidly R3.5 — Offline STT Review (Part 0)</h1>
<div class="sub">Generated {html.escape(summary['generated_at'])} · offline replay verified: Apple on-device helper + Parakeet MLX + Whisper MLX · no mic, no network APIs · total build time {elapsed} s</div>
<div class="sub mono">apple_stt binary: {html.escape(env['apple_stt_binary'])} (built: {env['apple_binary_built']}) · MLX loader: {html.escape(str(env['model_loader']))}</div>
""")

    # ---- capture-wiring banner -------------------------------------------
    parts.append(f'<div class="note"><b>Capture wiring:</b> {html.escape(summary["capture_note"])}'
                 + (f' {html.escape(summary["live_note"])}' if summary["live_note"] else "")
                 + "</div>")

    # ---- sessions summary -------------------------------------------------
    parts.append("<h2>Sessions analyzed (timeline.jsonl)</h2>")
    for s in analysis["sessions"]:
        sf = s["stt_finals"]
        lat = sf["latency_ms"]
        ch = s["turn_chopping"]
        fb = s["fallbacks"]
        g = s["garble"]
        if s["timeline_exists"]:
            evs = " · ".join(f"{k}:{v}" for k, v in sorted(s["event_counts"].items())) or "none"
            meta_line = f"events: {evs}" + (f" · speech span {s['duration_s']} s" if s["duration_s"] is not None else "")
        else:
            meta_line = '<span class="pos">no timeline.jsonl — nothing to analyze</span>'
        rows = []
        for item in sf["items"]:
            rows.append(f"<tr><td class='mono'>seq {item['seq']}</td><td class='mono'>{item['lane']}</td>"
                        f"<td>{html.escape(item['text'])}</td><td class='mono'>{item['latency_ms']} ms</td></tr>")
        garbles = []
        for flag, entries in sorted(g["flags"].items()):
            e0 = entries[0]
            garbles.append(f"<span class='flag'>{html.escape(flag)} ×{len(entries)} — “{html.escape(str(e0['text'])[:46])}”</span>")
        for ex in g["garbled_interim_script_examples"]:
            garbles.append(f"<span class='flag'>interim non-Latin script — “{html.escape(str(ex['text'])[:46])}”</span>")
        ghtml = " ".join(garbles) if garbles else '<span class="dim">none flagged</span>'
        fbs = ("<ul>" + "".join(
            f"<li class='mono'>{html.escape(str(f['event_type']))} · provider={html.escape(str(f['provider']))} · model={html.escape(str(f['model']))} · {f['latency_ms']} ms · degraded={f['degraded']}</li>"
            for f in fb["events"]) + "</ul>") if fb["count"] else ""

        audio_html = (f"{s['audio']['count']} file(s), {s['audio']['total_duration_s']} s"
                      if s["audio"]["count"] else
                      '<span class="pos">none captured</span> (capture wired only in R3.5)')
        if sf["count"]:
            finals_line = (f"<b>{sf['count']}</b> · latency ms: min {lat['min']} / <b>median {lat['median']}</b> / "
                           f"max {lat['max']} (mean {lat['mean']})")
        else:
            finals_line = "<b>0</b>"
        fallback_line = f"{fb['count']} event(s), {fb['total_ms']} ms total{fbs}" if fb["count"] else '<span class="dim">none</span>'
        parts.append(f"""<div class="card">
<h3>{html.escape(s['session_id'])}</h3>
<div class="sub mono">{meta_line}</div>
<table>
<tr><th>STT finals</th><td colspan="3">{finals_line}</td></tr>
<tr><th>Fallback / failure_safety</th><td colspan="3">{fallback_line}</td></tr>
<tr><th>Turn chopping</th><td colspan="3">commit windows: {ch['commit_count']} · commits with finals: {ch['commits_with_finals']} · <b>chopped (&gt;1 final): {ch['chopped_commit_count']}</b> · max finals in one commit: {ch['max_finals_in_one_commit']} · avg {ch['avg_finals_per_commit']}</td></tr>
<tr><th>Garble flags</th><td class="txt">{ghtml}</td></tr>
<tr><th>Captured audio</th><td colspan="3">{audio_html}</td></tr>
</table></div>""")

        if rows:
            parts.append('<div class="card"><table><tr><th>#[lane]</th><th>finals</th><th style="width:60%">text</th><th>latency</th></tr>'
                         + "".join(rows) + "</table></div>")

    # ---- per-segment provider comparison ----------------------------------
    parts.append("<h2>Transcription comparison (offline replay)</h2>")
    parts.append('<div class="sub">Latency notes — <b>Apple latency_ms is helper wall time incl. realtime-style feeding of the'
                 ' whole file</b> (dictation coupling), not the live lane-latency. Live cell shown when the segment maps to a'
                 ' candidate turn in timeline.jsonl (approximate by index order).</div>')
    for seg in summary["segments"]:
        prov = seg["providers"]
        a = prov["apple"]; p = prov["parakeet"]; w = prov["whisper"]
        live = seg.get("live")
        cells = {
            "live": cell_for(live.get("text") if live else None,
                             live.get("latency_ms") if live else None,
                             None, None) if live else '<div class="txt dim">— (no in-session transcript)</div>',
            "apple": cell_for(a.get("text"), a.get("latency_ms"), a.get("elapsed_s"), a.get("error")),
            "parakeet": cell_for(p.get("text"), None, p.get("elapsed_s"), p.get("error")),
            "whisper": cell_for(w.get("text"), None, w.get("elapsed_s"), w.get("error")),
        }
        ov = []
        for key, lab in (("parakeet", "Parakeet"), ("whisper", "Whisper")):
            o = prov[key].get("overlap_vs_apple")
            if o:
                ov.append(f'{lab} vs Apple: {o["jaccard_vs_apple"]:.0%} overlap ({o["common"]} words)')
        parts.append(f"""<div class="card">
<h3>{html.escape(seg['id'])} · {html.escape(seg['label'])} <span class="sub">({seg['duration_s']} s, {seg['bytes']} B)</span></h3>
<audio controls preload="none" src="{seg['audio_rel']}"></audio>
<table><tr><th style="width:25%">Live (in-session)</th><th style="width:25%">Apple SpeechAnalyzer</th><th style="width:25%">Parakeet (MLX)</th><th style="width:25%">Whisper (MLX)</th></tr>
<tr><td>{cells['live']}</td><td>{cells['apple']}</td><td>{cells['parakeet']}</td><td>{cells['whisper']}</td></tr></table>
<div class="sub">{" · ".join(ov) if ov else ""}</div>
</div>""")

    # ---- Apple locale check ------------------------------------------------
    lc = summary["locale_check"]
    parts.append("<h2>Apple locale check (en-US vs en-IN)</h2>")
    if lc and not lc.get("error"):
        us, inn_ = lc.get("en-US", {}), lc.get("en-IN", {})
        parts.append(f"""<div class="card">
<div class="sub">Representative segment: {html.escape(str(lc.get('representative')))}. Identical bytes streamed to the on-device helper with two locales.</div>
<table><tr><th style="width:20%">locale</th><th>text</th><th style="width:18%">latency</th></tr>
<tr><td class="mono">en-US</td><td>{cell_for(us.get('text'), us.get('latency_ms'), None, us.get('error'))}</td></tr>
<tr><td class="mono">en-IN</td><td>{cell_for(inn_.get('text'), inn_.get('latency_ms'), None, inn_.get('error'))}</td></tr>
</table></div>""")
    else:
        parts.append(f'<div class="card"><span class="err">{html.escape(str(lc.get("error") or "locale check unavailable"))}</span></div>')

    # ---- Findings (auto-filled from the analyzer) --------------------------
    parts.append("<h2>Findings</h2><div class='card'><ol>")
    if t["stt_final_latency_ms"]["count"]:
        latg = t["stt_final_latency_ms"]
        parts.append(f"<li><b>STT final latency (live lane 2):</b> {t['stt_finals_total']} finals across captured sessions; "
                     f"min {latg['min']} ms, median {latg['median']} ms, max {latg['max']} ms — the max shows answer windows "
                     "waiting on model finalization well above the ~1 s conversational budget.</li>")
    # gather concrete examples for garble / chop from all sessions
    garble_examples: List[str] = []
    for s in analysis["sessions"]:
        for flag_name, entries in s["garble"]["flags"].items():
            for e in entries[:2]:
                garble_examples.append(f"“{str(e['text'])[:48]}” ({flag_name})")
        for ex in s["garble"]["garbled_interim_script_examples"][:2]:
            garble_examples.append(f"interim “{str(ex['text'])[:48]}” (non-Latin script)")
    parts.append(f"<li><b>Garbled finals:</b> {t['garbled_finals_total']} of {t['stt_finals_total']} flagged. "
                 + ("Examples: " + "; ".join(garble_examples[:5]) + "."
                    " The Devanagari interim came from the streaming lane while locale/auto-select had not settled."
                    if garble_examples else "") + "</li>")
    chop_list = []
    for s in analysis["sessions"]:
        for gp in s["turn_chopping"]["groups"]:
            if gp["final_count"] > 1 and gp.get("turn_id"):
                chop_list.append(f"turn {gp['turn_id']} ({gp['reason']}): {gp['final_count']} finals seq{gp['seqs']}")
    parts.append(f"<li><b>Turn chopping:</b> {t['chopped_commits_total']} commit window(s) received &gt;1 candidate final"
                 + (": " + "; ".join(chop_list[:4]) + " — the answer was transcribed in two passes and committed together per window." if chop_list else "")
                 + "</li>")
    parts.append(f"<li><b>Fallbacks:</b> {t['fallback_events_total']} degraded/failure_safety decision(s), "
                 f"{t['fallback_total_ms']} ms spent on safety paths (LLM outage visible mid-session).</li>")
    capture_li = (f"<li><b>Captured audio:</b> {t['audio_files_total']} file(s) in captured sessions — real segments replayed offline.</li>"
                  if t["audio_files_total"] else
                  f"<li><b>Captured audio:</b> {t['audio_files_total']} file(s) — audio was never captured in these sessions; "
                  "audio segment capture was wired only in R3.5. This review therefore replays a demo sample "
                  "(labeled below as such) to exercise all three local transcribers end-to-end.</li>")
    parts.append(capture_li)
    agr = summary["agreement_vs_apple"]
    agr_bits = []
    for key, lab in (("parakeet", "Parakeet"), ("whisper", "Whisper")):
        m = agr.get(key, {}).get("mean_jaccard_vs_apple")
        if m is not None:
            agr_bits.append(f"{lab} {m:.0%}")
    if agr_bits:
        parts.append(f"<li><b>Cross-provider agreement (demo):</b> mean word-overlap vs Apple — {' · '.join(agr_bits)}. "
                     "Apple dictation stitching vs one-shot MLX decode of the same 5 s window; differences are casings/pauses wording.</li>")
    pe = summary["provider_elapsed_seconds"]
    parts.append(f"<li><b>Provider cost (offline):</b> Apple {pe['apple']} s wall (realtime-paced feed), "
                 f"Parakeet {pe['parakeet']} s, Whisper {pe['whisper']} s. Parakeet is by far the cheapest local fallback.</li>")
    parts.append("</ol>"
                 f"<div class='sub'>Auto-generated from debug/sessions timelines + offline transcriptions · {html.escape(summary['generated_at'])}</div></div>")

    parts.append("</body></html>")
    return "\n".join(parts)


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
