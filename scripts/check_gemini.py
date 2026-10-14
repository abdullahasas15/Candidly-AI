"""Script to verify all AI/LLM providers:
1. Primary Provider: Google Gemini with 3-key rotation (GEMINI_API_KEY1, GEMINI_API_KEY2, GEMINI_API_KEY3)
2. Secondary Backup: OpenRouter (nvidia/nemotron-3-super-120b-a12b:free)
3. Tertiary Backup: NVIDIA NIM (nvidia/nemotron-3-super-120b-a12b)

Usage:
    PYTHONPATH=. ./.venv/bin/python scripts/check_gemini.py
"""

import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# 1. Load environment
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    load_dotenv(override=True)

# 2. Inspect key sources
gemini_k1 = (os.getenv("GEMINI_API_KEY1") or "").strip()
gemini_k2 = (os.getenv("GEMINI_API_KEY2") or "").strip()
gemini_k3 = (os.getenv("GEMINI_API_KEY3") or "").strip()
legacy_gemini = (os.getenv("GEMINI_API_KEY") or "").strip()

openrouter_key = (os.getenv("openrouter") or os.getenv("OPENROUTER_API_KEY") or "").strip()
nvidia_key = (os.getenv("NVIDIA") or os.getenv("NVIDIA_API_KEY") or "").strip()

openrouter_model = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
nvidia_model = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")

print("=" * 80)
print("  CANDIDLY AI - MULTI-PROVIDER LLM CONFIGURATION (GEMINI 3-KEY + OPENROUTER + NVIDIA)")
print("=" * 80)
print(f"Project Root: {PROJECT_ROOT}")
print(f".env Path:    {ENV_PATH} (exists: {ENV_PATH.exists()})")
print("-" * 80)
print("Configured Providers:")
print(f"  * Gemini Key 1 (Primary):    {'Configured (len=' + str(len(gemini_k1)) + ')' if gemini_k1 else 'Not Configured'}")
print(f"  * Gemini Key 2 (Rotation 1): {'Configured (len=' + str(len(gemini_k2)) + ')' if gemini_k2 else 'Not Configured'}")
print(f"  * Gemini Key 3 (Rotation 2): {'Configured (len=' + str(len(gemini_k3)) + ')' if gemini_k3 else 'Not Configured'}")
print(f"  * OpenRouter (Secondary):    {'Configured (len=' + str(len(openrouter_key)) + ')' if openrouter_key else 'Not Configured'}")
print(f"  * NVIDIA NIM (Tertiary):     {'Configured (len=' + str(len(nvidia_key)) + ')' if nvidia_key else 'Not Configured'}")

gemini_keys = [("Key 1", gemini_k1), ("Key 2", gemini_k2), ("Key 3", gemini_k3)]
active_gemini_keys = [(name, k) for name, k in gemini_keys if k]

gemini_passed = False
openrouter_passed = False
nvidia_passed = False

# 3. Test Gemini Keys
print("-" * 80)
print("Testing Primary: Google Gemini (3-Key Rotation)...")
try:
    from google import genai
    from google.genai import types

    test_model = os.getenv("GEMINI_MODEL_LIVE", "gemini-3.5-flash-lite")
    for name, k in active_gemini_keys:
        t0 = time.perf_counter()
        try:
            client = genai.Client(api_key=k)
            resp = client.models.generate_content(
                model=test_model,
                contents="ping",
                config=types.GenerateContentConfig(
                    max_output_tokens=5,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            lat = round((time.perf_counter() - t0) * 1000.0, 1)
            text = (resp.text or "").strip()[:20]
            print(f"  ✓ Gemini {name}: PASS ({lat}ms, model: {test_model}) -> '{text}'")
            gemini_passed = True
        except Exception as exc:
            lat = round((time.perf_counter() - t0) * 1000.0, 1)
            err_msg = str(exc)
            if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
                print(f"  ⚠ Gemini {name}: QUOTA EXCEEDED (429, {lat}ms) -> Auto-rotates to next key")
            else:
                print(f"  ✗ Gemini {name}: FAIL ({lat}ms) -> {err_msg[:80]}")
except Exception as exc:
    print(f"  ✗ Failed to import/run Gemini client: {exc}")

# 4. Test OpenRouter Provider (Single verification probe)
if openrouter_key:
    print("-" * 80)
    print(f"Testing Secondary Backup: OpenRouter ({openrouter_model})...")
    from openai import OpenAI
    t0 = time.perf_counter()
    try:
        or_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
        resp = or_client.chat.completions.create(
            model=openrouter_model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=32,
            temperature=0.0,
            timeout=15.0,
        )
        lat = round((time.perf_counter() - t0) * 1000.0, 1)
        msg = resp.choices[0].message
        content = (msg.content or getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or "").strip()[:30]
        print(f"  ✓ OpenRouter: PASS ({lat}ms) -> '{content}'")
        openrouter_passed = True
    except Exception as exc:
        lat = round((time.perf_counter() - t0) * 1000.0, 1)
        print(f"  ✗ OpenRouter: FAIL ({lat}ms) -> {str(exc)[:90]}")

# 5. Test NVIDIA Provider (Single verification probe)
if nvidia_key:
    print("-" * 80)
    print(f"Testing Tertiary Backup: NVIDIA NIM ({nvidia_model})...")
    from openai import OpenAI
    t0 = time.perf_counter()
    try:
        nv_client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=nvidia_key)
        resp = nv_client.chat.completions.create(
            model=nvidia_model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=32,
            temperature=0.0,
            timeout=15.0,
        )
        lat = round((time.perf_counter() - t0) * 1000.0, 1)
        msg = resp.choices[0].message
        content = (msg.content or getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or "").strip()[:30]
        print(f"  ✓ NVIDIA NIM: PASS ({lat}ms) -> '{content}'")
        nvidia_passed = True
    except Exception as exc:
        lat = round((time.perf_counter() - t0) * 1000.0, 1)
        print(f"  ✗ NVIDIA NIM: FAIL ({lat}ms) -> {str(exc)[:90]}")

# 6. Routing Summary
print("\n" + "=" * 80)
print("  MULTI-PROVIDER ROUTING STATUS")
print("=" * 80)
print(f"  * Primary (Gemini 3-Key Rotation): {'ONLINE' if gemini_passed else 'ALL KEYS EXHAUSTED/DEGRADED'}")
print(f"  * Secondary Backup (OpenRouter):   {'ONLINE' if openrouter_passed else 'OFFLINE/UNCONFIGURED'}")
print(f"  * Tertiary Backup (NVIDIA NIM):    {'ONLINE' if nvidia_passed else 'OFFLINE/UNCONFIGURED'}")

if gemini_passed or openrouter_passed or nvidia_passed:
    active = []
    if gemini_passed:
        active.append("Google Gemini (3-Key Rotation)")
    if openrouter_passed:
        active.append(f"OpenRouter ({openrouter_model})")
    if nvidia_passed:
        active.append(f"NVIDIA NIM ({nvidia_model})")
    print(f"\n  ✓ SYSTEM OPERATIONAL: Active providers available: {', '.join(active)}")
    print("    Failover Flow: Gemini Key 1 -> Key 2 -> Key 3 -> OpenRouter -> NVIDIA")
    print("=" * 80)
    sys.exit(0)
else:
    print("\n  ✗ ALL PROVIDERS FAILED.")
    print("=" * 80)
    sys.exit(1)
