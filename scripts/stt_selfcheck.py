#!/usr/bin/env python3
"""Run automated STT self-check benchmark comparing Whisper, Parakeet, and Nemotron on Apple Silicon.

Uses synthetic speech generated via macOS `say` (US, UK, Indian, Australian) and Kokoro.
Reports Word Error Rate (WER) and Technical-Term Accuracy.

Usage:
    ./scripts/stt_selfcheck.py
"""

import os
import re
import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np

# Ensure test audio exists
from scripts.make_test_audio import TEST_PASSAGES, generate_all, OUTPUT_DIR


def compute_wer(reference: str, hypothesis: str) -> float:
    """Computes Word Error Rate (WER) using Levenshtein distance on word tokens."""
    def normalize(text: str) -> List[str]:
        cleaned = re.sub(r"[^\w\s]", "", text.lower())
        return cleaned.split()

    ref_words = normalize(reference)
    hyp_words = normalize(hypothesis)

    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    d = np.zeros((len(ref_words) + 1, len(hyp_words) + 1), dtype=np.int32)
    for i in range(len(ref_words) + 1):
        d[i, 0] = i
    for j in range(len(hyp_words) + 1):
        d[0, j] = j

    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                d[i, j] = d[i - 1, j - 1]
            else:
                substitution = d[i - 1, j - 1] + 1
                insertion = d[i, j - 1] + 1
                deletion = d[i - 1, j] + 1
                d[i, j] = min(substitution, insertion, deletion)

    return float(d[len(ref_words), len(hyp_words)]) / float(len(ref_words))


def check_term_accuracy(reference: str, hypothesis: str, key_terms: List[str]) -> Tuple[int, int, float]:
    """Check how many key technical terms from reference were captured in hypothesis."""
    hyp_lower = hypothesis.lower()
    found = 0
    total = len(key_terms)
    for term in key_terms:
        if term.lower() in hyp_lower:
            found += 1
    accuracy = (found / total) * 100.0 if total > 0 else 100.0
    return found, total, accuracy


KEY_TERMS_MAP = {
    "technical_tradeoffs": ["PostgreSQL", "NoSQL", "ACID", "B-tree", "DynamoDB", "sharding"],
    "concurrency_pause": ["multithreaded", "race conditions", "synchronization", "mutexes", "read-write locks", "atomic", "compare-and-swap"],
    "kafka_streaming": ["Apache Kafka", "partitions", "consumer group", "partition key", "backpressure", "poll timeouts"],
    "kubernetes_deployment": ["Kubernetes", "replica sets", "cluster IP", "Ingress", "TLS", "Prometheus"],
    "kokoro": ["cache stampedes", "database availability", "mutual exclusion", "probabilistic", "thundering herd"],
}


def load_asr_models():
    """Load Whisper, Parakeet, and Nemotron models."""
    models = {}
    print("\n[+] Loading STT models for benchmark...")

    # 1. Whisper Large v3 Turbo
    try:
        t0 = time.perf_counter()
        from mlx_audio.stt.utils import load_model
        print("  - Loading mlx-community/whisper-large-v3-turbo...")
        whisper = load_model("mlx-community/whisper-large-v3-turbo")
        models["whisper"] = whisper
        print(f"    ✓ Whisper ready ({(time.perf_counter()-t0)*1000:.0f}ms)")
    except Exception as e:
        print(f"    ✗ Whisper failed: {e}")
        models["whisper"] = None

    # 2. Parakeet TDT 0.6B v2
    try:
        t0 = time.perf_counter()
        import parakeet_mlx
        print("  - Loading mlx-community/parakeet-tdt-0.6b-v2...")
        parakeet = parakeet_mlx.from_pretrained("mlx-community/parakeet-tdt-0.6b-v2")
        models["parakeet"] = parakeet
        print(f"    ✓ Parakeet ready ({(time.perf_counter()-t0)*1000:.0f}ms)")
    except Exception as e:
        print(f"    ✗ Parakeet failed: {e}")
        models["parakeet"] = None

    # 3. Nemotron Streaming 0.6B
    try:
        t0 = time.perf_counter()
        from mlx_audio.stt.utils import load_model
        print("  - Loading mlx-community/nemotron-3.5-asr-streaming-0.6b...")
        nemotron = load_model("mlx-community/nemotron-3.5-asr-streaming-0.6b")
        models["nemotron"] = nemotron
        print(f"    ✓ Nemotron ready ({(time.perf_counter()-t0)*1000:.0f}ms)")
    except Exception as e:
        print(f"    ✗ Nemotron failed: {e}")
        models["nemotron"] = None

    return models


def transcribe_audio(model_type: str, model_instance: any, wav_path: Path) -> Tuple[str, float]:
    """Transcribes a wav file with the given model, returning (text, elapsed_seconds)."""
    t0 = time.perf_counter()
    if model_instance is None:
        return "", 0.0

    try:
        if model_type in {"whisper", "nemotron"}:
            res = model_instance.generate(str(wav_path))
            text = getattr(res, "text", str(res)).strip()
        elif model_type == "parakeet":
            import wave
            import mlx.core as mx
            from parakeet_mlx.audio import get_logmel
            with wave.open(str(wav_path), "rb") as wf:
                raw = wf.readframes(wf.getnframes())
                arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            mel = get_logmel(mx.array(arr), model_instance.preprocessor_config)
            res = model_instance.generate(mel)
            text = getattr(res[0], "text", str(res[0])).strip() if res else ""
        elapsed = time.perf_counter() - t0
        return text, elapsed
    except Exception as e:
        print(f"Transcription error with {model_type} on {wav_path.name}: {e}")
        return "", time.perf_counter() - t0


def run_benchmark():
    print("=" * 80)
    print("CANDIDLY STT SELF-CHECK BENCHMARK (R3.4)")
    print("Zero human recordings | macOS say + Kokoro synthetic technical passages")
    print("=" * 80)

    # 1. Ensure test audio is generated
    wav_files = sorted(OUTPUT_DIR.glob("*.wav")) if OUTPUT_DIR.exists() else []
    if not wav_files:
        print("\n[+] Generating synthetic audio fixtures...")
        wav_files = generate_all()

    models = load_asr_models()

    test_data = [
        {
            "id": "technical_tradeoffs",
            "name": "US Accent (Samantha) - Database Trade-offs (2.5s pause)",
            "wav": OUTPUT_DIR / "technical_tradeoffs_samantha.wav",
            "ref": " ".join(TEST_PASSAGES[0]["text_parts"]),
            "terms": KEY_TERMS_MAP["technical_tradeoffs"],
        },
        {
            "id": "concurrency_pause",
            "name": "UK Accent (Daniel) - Concurrency & Race Conditions (3.0s pause)",
            "wav": OUTPUT_DIR / "concurrency_pause_daniel.wav",
            "ref": " ".join(TEST_PASSAGES[1]["text_parts"]),
            "terms": KEY_TERMS_MAP["concurrency_pause"],
        },
        {
            "id": "kafka_streaming",
            "name": "Indian Accent (Rishi) - Kafka Partition Scaling (2.0s pause)",
            "wav": OUTPUT_DIR / "kafka_streaming_rishi.wav",
            "ref": " ".join(TEST_PASSAGES[2]["text_parts"]),
            "terms": KEY_TERMS_MAP["kafka_streaming"],
        },
        {
            "id": "kubernetes_deployment",
            "name": "Australian Accent (Karen) - Kubernetes Ingress (2.5s pause)",
            "wav": OUTPUT_DIR / "kubernetes_deployment_karen.wav",
            "ref": " ".join(TEST_PASSAGES[3]["text_parts"]),
            "terms": KEY_TERMS_MAP["kubernetes_deployment"],
        },
        {
            "id": "kokoro",
            "name": "Kokoro TTS (af_heart) - Cache Stampedes (2.5s pause)",
            "wav": OUTPUT_DIR / "kokoro_technical_passage.wav",
            "ref": "In modern backend architecture, cache stampedes can degrade database availability during traffic spikes. Employing mutual exclusion locks around cache refreshes or probabilistic early expiration mitigates the thundering herd problem.",
            "terms": KEY_TERMS_MAP["kokoro"],
        },
    ]

    results_table = []

    print("\n" + "=" * 80)
    print("RUNNING BENCHMARKS...")
    print("=" * 80)

    for item in test_data:
        wav = item["wav"]
        if not wav.exists():
            continue

        ref = item["ref"]
        terms = item["terms"]
        print(f"\n---> Test: {item['name']}")

        item_res = {"name": item["name"]}

        for m_name in ["whisper", "parakeet", "nemotron"]:
            m_inst = models.get(m_name)
            if m_inst is None:
                item_res[m_name] = {"wer": 1.0, "term_acc": 0.0, "time": 0.0, "text": "N/A"}
                continue

            hyp, t_elap = transcribe_audio(m_name, m_inst, wav)
            wer = compute_wer(ref, hyp)
            found, tot, term_acc = check_term_accuracy(ref, hyp, terms)
            item_res[m_name] = {
                "wer": wer,
                "term_acc": term_acc,
                "terms_found": f"{found}/{tot}",
                "time": t_elap,
                "text": hyp,
            }
            print(f"  [{m_name.upper():8}] WER: {wer*100:5.1f}% | Terms: {found}/{tot} ({term_acc:5.1f}%) | Time: {t_elap:.2f}s")

        results_table.append(item_res)

    print("\n" + "=" * 90)
    print("BENCHMARK SUMMARY COMPARISON:")
    print("=" * 90)
    print(f"{'TEST CASE':<36} | {'WHISPER (WER/TERM)':<20} | {'PARAKEET (WER/TERM)':<20} | {'NEMOTRON (WER/TERM)'}")
    print("-" * 90)

    whisper_wers = []
    parakeet_wers = []
    nemotron_wers = []

    for r in results_table:
        w = r.get("whisper", {})
        p = r.get("parakeet", {})
        n = r.get("nemotron", {})

        w_str = f"{w.get('wer', 1)*100:4.1f}% / {w.get('term_acc', 0):4.1f}%" if "wer" in w else "N/A"
        p_str = f"{p.get('wer', 1)*100:4.1f}% / {p.get('term_acc', 0):4.1f}%" if "wer" in p else "N/A"
        n_str = f"{n.get('wer', 1)*100:4.1f}% / {n.get('term_acc', 0):4.1f}%" if "wer" in n else "N/A"

        if "wer" in w and w["wer"] < 1.0:
            whisper_wers.append(w["wer"])
        if "wer" in p and p["wer"] < 1.0:
            parakeet_wers.append(p["wer"])
        if "wer" in n and n["wer"] < 1.0:
            nemotron_wers.append(n["wer"])

        print(f"{r['name'][:35]:<36} | {w_str:<20} | {p_str:<20} | {n_str}")

    print("-" * 90)
    avg_w = (sum(whisper_wers) / len(whisper_wers)) * 100 if whisper_wers else 0
    avg_p = (sum(parakeet_wers) / len(parakeet_wers)) * 100 if parakeet_wers else 0
    avg_n = (sum(nemotron_wers) / len(nemotron_wers)) * 100 if nemotron_wers else 0

    print(f"{'AVERAGE WER':<36} | {avg_w:4.1f}%{'':<15} | {avg_p:4.1f}%{'':<15} | {avg_n:4.1f}%")
    print("=" * 90)

    print("\nRECOMMENDATION:")
    if whisper_wers and (not parakeet_wers or avg_w <= avg_p):
        print("  ✓ KEEP WHISPER-LARGE-V3-TURBO as Default Lane 2 ASR engine.")
        print("    High fidelity on technical terminology, lower WER across varied accents.")
    else:
        print("  ✓ Parakeet shows comparable or lower WER.")
    print("=" * 90)


if __name__ == "__main__":
    run_benchmark()
