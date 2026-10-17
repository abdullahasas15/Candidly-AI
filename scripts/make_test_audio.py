#!/usr/bin/env python3
"""Generate synthetic test audio using macOS `say` voices and Kokoro TTS.

Creates 16 kHz mono WAV files with technical passages and inserted 2-3s pauses.
Output files are saved to `debug/test_audio/` (gitignored).

Voices:
- US: Samantha
- UK: Daniel
- Indian: Rishi
- Australian: Karen
- Kokoro: af_heart (via mlx-audio)
"""

import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
import numpy as np

OUTPUT_DIR = Path("debug/test_audio")

TEST_PASSAGES = [
    {
        "id": "technical_tradeoffs",
        "voice": "Samantha",
        "lang": "en_US",
        "text_parts": [
            "When designing a distributed service, choosing between PostgreSQL and a NoSQL document store involves clear consistency trade-offs.",
            "PostgreSQL provides ACID guarantees and strict relational integrity with B-tree indexing for low-latency queries.",
            "However, if we require high write throughput and partition tolerance, horizontal sharding or DynamoDB might be preferable.",
        ],
        "pause_s": 2.5,
    },
    {
        "id": "concurrency_pause",
        "voice": "Daniel",
        "lang": "en_GB",
        "text_parts": [
            "In a multithreaded architecture, race conditions often emerge when multiple worker threads mutate shared state without synchronization.",
            "Using mutexes or read-write locks prevents data corruption, though fine-grained locking is needed to avoid deadlock.",
            "Alternatively, lock-free queues utilizing atomic compare-and-swap instructions can significantly reduce thread contention.",
        ],
        "pause_s": 3.0,
    },
    {
        "id": "kafka_streaming",
        "voice": "Rishi",
        "lang": "en_IN",
        "text_parts": [
            "For streaming telemetry data, Apache Kafka partitions allow horizontal scaling across multiple consumer group instances.",
            "Each partition key guarantees strict in-order message delivery within that partition.",
            "We handle consumer backpressure and rebalancing by tuning poll timeouts and batch commit intervals.",
        ],
        "pause_s": 2.0,
    },
    {
        "id": "kubernetes_deployment",
        "voice": "Karen",
        "lang": "en_AU",
        "text_parts": [
            "In Kubernetes, container pods are managed by replica sets behind a cluster IP service.",
            "Ingress controllers route external HTTP traffic based on host headers and TLS termination rules.",
            "Horizontal Pod Autoscalers continuously adjust pod replica counts based on CPU utilization and custom Prometheus metrics.",
        ],
        "pause_s": 2.5,
    },
]


def convert_to_16k_mono_pcm(input_path: str, output_path: str) -> None:
    """Uses macOS afconvert to produce 16kHz mono 16-bit linear PCM WAV."""
    cmd = [
        "/usr/bin/afconvert",
        "-f", "WAVE",
        "-d", "LEI16@16000",
        "-c", "1",
        input_path,
        output_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def generate_say_passage(passage: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_wav = OUTPUT_DIR / f"{passage['id']}_{passage['voice'].lower()}.wav"
    
    combined_audio = []
    pause_samples = int(passage["pause_s"] * 16000)
    silence = np.zeros(pause_samples, dtype=np.int16)

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, part in enumerate(passage["text_parts"]):
            aiff_path = os.path.join(tmpdir, f"part_{idx}.aiff")
            wav_path = os.path.join(tmpdir, f"part_{idx}.wav")
            
            # Run macOS say
            subprocess.run(["say", "-v", passage["voice"], "-o", aiff_path, part], check=True)
            # Convert to 16kHz mono
            convert_to_16k_mono_pcm(aiff_path, wav_path)
            
            # Read 16k PCM
            with wave.open(wav_path, "rb") as wf:
                data = wf.readframes(wf.getnframes())
                samples = np.frombuffer(data, dtype=np.int16)
                combined_audio.append(samples)
                if idx < len(passage["text_parts"]) - 1:
                    combined_audio.append(silence)

    final_samples = np.concatenate(combined_audio)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(final_samples.tobytes())

    dur_s = len(final_samples) / 16000.0
    print(f"Generated: {out_wav} ({dur_s:.2f}s, voice={passage['voice']}, pause={passage['pause_s']}s)")
    return out_wav


def generate_kokoro_passage() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_wav = OUTPUT_DIR / "kokoro_technical_passage.wav"
    
    parts = [
        "In modern backend architecture, cache stampedes can degrade database availability during traffic spikes.",
        "Employing mutual exclusion locks around cache refreshes or probabilistic early expiration mitigates the thundering herd problem.",
    ]
    pause_samples = int(2.5 * 16000)
    silence = np.zeros(pause_samples, dtype=np.int16)
    
    try:
        from mlx_audio.tts.utils import load_model
        import mlx_audio.tts.generate as generate
        print("Synthesizing Kokoro audio via mlx-audio...")
        model = load_model("mlx-community/Kokoro-82M-bf16")
        
        pcm_chunks = []
        for idx, text in enumerate(parts):
            # Kokoro sample rate is 24000
            for seg in model.generate(text=text, voice="af_heart"):
                raw_audio = np.array(seg.audio, dtype=np.float32)
                # simple linear interpolation to 16k
                num_16k = int(len(raw_audio) * 16000 / 24000)
                audio_16k = np.interp(
                    np.linspace(0, len(raw_audio), num_16k, endpoint=False),
                    np.arange(len(raw_audio)),
                    raw_audio
                )
                int16_samples = (np.clip(audio_16k, -1.0, 1.0) * 32767).astype(np.int16)
                pcm_chunks.append(int16_samples)
            if idx < len(parts) - 1:
                pcm_chunks.append(silence)
                
        final_samples = np.concatenate(pcm_chunks)
        with wave.open(str(out_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(final_samples.tobytes())
        print(f"Generated Kokoro test: {out_wav} ({len(final_samples)/16000:.2f}s)")
    except Exception as e:
        print(f"Kokoro test audio generation fallback to say: {e}")
        # fallback to say
        return generate_say_passage({
            "id": "kokoro_fallback",
            "voice": "Samantha",
            "lang": "en_US",
            "text_parts": parts,
            "pause_s": 2.5
        })

    return out_wav


def generate_all() -> list[Path]:
    print("=" * 60)
    print("Generating Synthetic Test Audio Fixtures (macOS say + Kokoro)")
    print("=" * 60)
    generated = []
    for p in TEST_PASSAGES:
        wav = generate_say_passage(p)
        generated.append(wav)
    kwav = generate_kokoro_passage()
    generated.append(kwav)
    print("=" * 60)
    print(f"All {len(generated)} test audio fixtures ready in {OUTPUT_DIR}/")
    return generated


if __name__ == "__main__":
    generate_all()
