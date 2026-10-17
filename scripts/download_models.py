#!/usr/bin/env python3
"""Download and report sizes of models required for Candidly voice interview platform.

Models:
- Lane 1 (live captions): mlx-community/nemotron-3.5-asr-streaming-0.6b
- Lane 2 (accuracy): mlx-community/whisper-large-v3-turbo
- Lane 2 fallback (Parakeet TDT v2): mlx-community/parakeet-tdt-0.6b-v2
- TTS (Kokoro 82M): mlx-community/Kokoro-82M-bf16
"""

import os
import sys
from pathlib import Path
from huggingface_hub import snapshot_download

MODELS = {
    "Lane 1 (streaming captions)": "mlx-community/nemotron-3.5-asr-streaming-0.6b",
    "Lane 2 (accuracy ASR - Whisper)": "mlx-community/whisper-large-v3-turbo",
    "Lane 2 fallback (Parakeet TDT v2)": "mlx-community/parakeet-tdt-0.6b-v2",
    "TTS (Kokoro 82M)": "mlx-community/Kokoro-82M-bf16",
}


def get_dir_size_mb(path: Path) -> float:
    total_bytes = 0
    seen_files = set()
    for p in path.rglob("*"):
        try:
            target = p.resolve()
            if target.is_file() and str(target) not in seen_files:
                seen_files.add(str(target))
                total_bytes += target.stat().st_size
        except Exception:
            pass
    return total_bytes / (1024 * 1024)


def download_all():
    print("=" * 60)
    print("Candidly AI Voice Pipeline - Model Downloader")
    print("=" * 60)
    
    results = {}
    for role, repo_id in MODELS.items():
        print(f"\n[+] Fetching {role}: {repo_id}...")
        try:
            local_path = snapshot_download(
                repo_id=repo_id,
                allow_patterns=["*.safetensors", "*.json", "*.txt", "*.model", "*.bin", "*.py"],
                resume_download=True,
            )
            p = Path(local_path)
            size_mb = get_dir_size_mb(p)
            print(f"    ✓ Downloaded/Cached at: {local_path}")
            print(f"    ✓ On-disk size: {size_mb:.1f} MB")
            results[repo_id] = (size_mb, True)
        except Exception as e:
            print(f"    ✗ Failed to download {repo_id}: {e}")
            results[repo_id] = (0.0, False)

    print("\n" + "=" * 60)
    print("Model Download Summary:")
    print("=" * 60)
    total_mb = sum(size for size, ok in results.values())
    for repo_id, (size, ok) in results.items():
        status = f"{size:.1f} MB" if ok else "FAILED"
        print(f"  - {repo_id:45} : {status}")
    print(f"\nTotal Storage: {total_mb:.1f} MB ({total_mb / 1024:.2f} GB)")
    print("=" * 60)
    return results


if __name__ == "__main__":
    download_all()
