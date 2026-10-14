"""Unified Multi-Provider LLM Router for Candidly AI with Circuit Breaker and Candidate Data Protection.

Provides resilient high-availability routing across:
1. Google Gemini (GEMINI_API_KEY1 -> GEMINI_API_KEY2 -> GEMINI_API_KEY3) - Primary Provider with 3-Key Rotation
2. OpenRouter (openrouter / OPENROUTER_API_KEY) - Secondary Backup Provider (nvidia/nemotron-3-super-120b-a12b:free)
3. NVIDIA NIM (NVIDIA / NVIDIA_API_KEY) - Tertiary Backup Provider (nvidia/nemotron-3-super-120b-a12b)

Failover Rules:
- Primary uses Google Gemini. It starts on Key 1.
- If Key 1 fails on rate limits (429/RESOURCE_EXHAUSTED), 503, 5xx, or network timeout:
  immediately rotate to Key 2.
- If Key 2 fails: rotate to Key 3.
- If all 3 Gemini keys fail: route automatically to OpenRouter.
- If OpenRouter fails: route automatically to NVIDIA.
- Invalid or expired keys (400/401/403/API_KEY_INVALID) log errors and rotate to next key; raises ProviderAuthError if all keys invalid.
- GeminiCircuitBreaker tracks failure thresholds, cooldowns, and half-open probing.
- AI_FAILOVER_CANDIDATE_DATA controls candidate data routing to backup (default True).
- Failover is disabled when AI_FAILOVER_ENABLED=false (true primary evaluation).
- Amazon Bedrock is completely removed in favor of OpenRouter and NVIDIA.
"""

import asyncio
import json
import logging
import os
import random
import re
import time
from typing import Dict, Any, List, Optional, AsyncIterator, Tuple
from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI

load_dotenv(override=True)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider & Model Defaults
# ---------------------------------------------------------------------------
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")

# Pinned backup model IDs per role
BACKUP_MODEL_PLAN = OPENROUTER_MODEL
BACKUP_MODEL_LIVE = OPENROUTER_MODEL
BACKUP_MODEL_JUDGE = OPENROUTER_MODEL

# Primary Gemini models per role
GEMINI_MODEL_PLAN = os.getenv("GEMINI_MODEL_PLAN", "gemini-3.5-flash-lite")
GEMINI_MODEL_LIVE = os.getenv("GEMINI_MODEL_LIVE", "gemini-3.5-flash-lite")
GEMINI_MODEL_JUDGE = os.getenv("GEMINI_MODEL_JUDGE", "gemini-3.5-flash-lite")

GEMINI_MODELS = [
    GEMINI_MODEL_LIVE,
    GEMINI_MODEL_PLAN,
    "gemini-2.5-flash",
    "gemini-3.5-flash",
]

# Concurrency Semaphores
GEMINI_CONCURRENCY_LIMIT = int(os.getenv("GEMINI_MAX_CONCURRENCY", "5"))
BACKUP_CONCURRENCY_LIMIT = int(os.getenv("BACKUP_MAX_CONCURRENCY", "4"))

GEMINI_SEMAPHORE = asyncio.Semaphore(GEMINI_CONCURRENCY_LIMIT)
BACKUP_SEMAPHORE = asyncio.Semaphore(BACKUP_CONCURRENCY_LIMIT)

# Backward compatibility aliases
BEDROCK_MODEL_PLAN = BACKUP_MODEL_PLAN
BEDROCK_MODEL_LIVE = BACKUP_MODEL_LIVE
BEDROCK_MODEL_JUDGE = BACKUP_MODEL_JUDGE
TOKENHARBOR_MODEL_PLAN = BACKUP_MODEL_PLAN
TOKENHARBOR_MODEL_LIVE = BACKUP_MODEL_LIVE
TOKENHARBOR_MODEL_JUDGE = BACKUP_MODEL_JUDGE
BEDROCK_CONCURRENCY_LIMIT = BACKUP_CONCURRENCY_LIMIT
TOKENHARBOR_CONCURRENCY_LIMIT = BACKUP_CONCURRENCY_LIMIT
BEDROCK_SEMAPHORE = BACKUP_SEMAPHORE
TOKENHARBOR_SEMAPHORE = BACKUP_SEMAPHORE


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class ProviderAuthError(RuntimeError):
    """Raised when an API key is invalid or unauthorized. Must NEVER failover silently."""
    pass


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider is unavailable due to rate limits or outages."""
    pass


class CandidateDataFailoverBlockedError(RuntimeError):
    """Raised when candidate data failover to backup provider is attempted while AI_FAILOVER_CANDIDATE_DATA=false."""
    pass


# ---------------------------------------------------------------------------
# Error Classification Helpers
# ---------------------------------------------------------------------------
def is_fatal_auth_error(exc: Exception) -> bool:
    """Detect fatal authentication / configuration errors that must NEVER trigger silent failover."""
    err_str = str(exc)
    err_upper = err_str.upper()

    # Rate limits / resource exhaustion / quota limits are transient, not fatal auth errors
    if "RESOURCE_EXHAUSTED" in err_upper or "429" in err_upper or "QUOTA" in err_upper:
        return False

    fatal_phrases = [
        "API_KEY_INVALID",
        "API KEY NOT VALID",
        "INVALID_ARGUMENT",
        "PERMISSION_DENIED",
        "UNAUTHENTICATED",
        "CONSUMER_INVALID",
        "AUTHENTICATION FAILED",
        "ACCESSDENIED",
        "NOT AUTHORIZED",
        "EXPIREDTOKEN",
    ]
    if any(phrase in err_upper for phrase in fatal_phrases):
        return True

    if re.search(r"['\"]?code['\"]?\s*:\s*(?:401|403)\b", err_str) or \
       re.search(r"status(?:_code)?\s*[=:]\s*(?:401|403)\b", err_str) or \
       re.search(r"\b(?:401\s+UNAUTHORIZED|403\s+FORBIDDEN)\b", err_upper):
        return True

    return False


def is_transient_failover_error(exc: Exception) -> bool:
    """Detect transient errors (429 rate limit, 5xx, timeouts) eligible for key rotation or backup routing."""
    err_str = str(exc).upper()
    transient_markers = [
        "429",
        "RESOURCE_EXHAUSTED",
        "500",
        "502",
        "503",
        "504",
        "UNAVAILABLE",
        "OVERLOADED",
        "HIGH DEMAND",
        "TIMEOUT",
        "CONNECTTIMEOUT",
        "READTIMEOUT",
        "CONNECTION RESET",
    ]
    return any(marker in err_str for marker in transient_markers)


def extract_retry_after(exc: Exception) -> Optional[float]:
    """Extract retryDelay in seconds from Gemini / HTTP errors if available."""
    err_str = str(exc)
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)(?:\.\d+)?s?", err_str, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except Exception:
            pass
    match_sec = re.search(r"retry\s*in\s*(\d+)", err_str, re.IGNORECASE)
    if match_sec:
        try:
            return float(match_sec.group(1))
        except Exception:
            pass
    return None


def clean_json_markdown(text: str) -> str:
    """Strip markdown code fence blocks if present."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Key Retrieval Helpers
# ---------------------------------------------------------------------------
def get_openrouter_api_key() -> Optional[str]:
    """Retrieve OpenRouter API key from environment."""
    key = os.getenv("openrouter") or os.getenv("OPENROUTER_API_KEY")
    return key.strip() if key else None


def get_nvidia_api_key() -> Optional[str]:
    """Retrieve NVIDIA API key from environment."""
    key = os.getenv("NVIDIA") or os.getenv("NVIDIA_API_KEY")
    return key.strip() if key else None


def get_backup_api_key() -> Optional[str]:
    """Retrieve first available backup provider API key (OpenRouter or NVIDIA)."""
    return get_openrouter_api_key() or get_nvidia_api_key()


def get_bedrock_api_key() -> Optional[str]:
    """Backward compatibility alias returning backup API key."""
    return get_backup_api_key()


def get_llm_api_key() -> Optional[str]:
    """Backward compatible accessor."""
    return get_backup_api_key()


def is_failover_enabled() -> bool:
    """Return whether failover to secondary backup provider is enabled."""
    return os.getenv("AI_FAILOVER_ENABLED", "true").lower() in ("true", "1", "yes")


def can_failover_candidate_data() -> bool:
    """Candidate data may use the backup when AI_FAILOVER_CANDIDATE_DATA=true (default true)."""
    if not is_failover_enabled():
        return False
    return os.getenv("AI_FAILOVER_CANDIDATE_DATA", "true").lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Circuit Breaker for Primary Provider (Gemini)
# ---------------------------------------------------------------------------
class GeminiCircuitBreaker:
    """Circuit breaker for Google Gemini:
    - After failure_threshold errors across all keys, routes directly to backup.
    - Stay open for cooldown_secs, then transition to HALF_OPEN to probe primary.
    """
    def __init__(
        self,
        failure_threshold: int = 3,
        window_secs: float = 60.0,
        cooldown_secs: float = 60.0,
    ):
        self.failure_threshold = failure_threshold
        self.window_secs = window_secs
        self.cooldown_secs = cooldown_secs
        self.failure_timestamps: List[float] = []
        self.state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.opened_at: float = 0.0
        self.mandatory_cooldown_until: float = 0.0

    def can_attempt_primary(self) -> bool:
        now = time.monotonic()
        if now < self.mandatory_cooldown_until:
            return False
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if now - self.opened_at >= self.cooldown_secs:
                logger.info("Gemini circuit breaker entering HALF_OPEN probe state")
                self.state = "HALF_OPEN"
                return True
            return False
        if self.state == "HALF_OPEN":
            return True
        return True

    def can_attempt(self) -> bool:
        return self.can_attempt_primary()

    def record_success(self):
        if self.state in ("OPEN", "HALF_OPEN"):
            logger.info("Gemini probe succeeded! Resetting circuit breaker to CLOSED")
        self.state = "CLOSED"
        self.failure_timestamps.clear()
        self.mandatory_cooldown_until = 0.0

    def record_failure(self, exc: Any, retry_after: Optional[float] = None):
        now = time.monotonic()
        retry_delay = retry_after if retry_after is not None else extract_retry_after(exc)
        if retry_delay and retry_delay > 0:
            self.mandatory_cooldown_until = max(self.mandatory_cooldown_until, now + min(retry_delay, 120.0))

        self.failure_timestamps = [t for t in self.failure_timestamps if now - t <= self.window_secs]
        self.failure_timestamps.append(now)

        if len(self.failure_timestamps) >= self.failure_threshold or self.state == "HALF_OPEN":
            self.state = "OPEN"
            self.opened_at = now
            logger.warning(
                "Gemini circuit breaker TRIPPED to OPEN (cooldown %.1fs). Primary will be bypassed. Error: %s",
                self.cooldown_secs, str(exc)[:120],
            )


GEMINI_CIRCUIT_BREAKER = GeminiCircuitBreaker(failure_threshold=3, window_secs=60.0, cooldown_secs=60.0)


# ---------------------------------------------------------------------------
# Gemini 3-Key Rotation Manager
# ---------------------------------------------------------------------------
class GeminiKeyManager:
    """Manages 3-key Gemini rotation:
    - Starts at GEMINI_API_KEY1.
    - If Key 1 fails even once on rate-limit (429/RESOURCE_EXHAUSTED) or 503/transient:
      immediately rotates to GEMINI_API_KEY2.
    - If Key 2 fails: rotates to GEMINI_API_KEY3.
    - If all 3 keys fail in a single cycle: signals primary exhaustion so caller fails over to OpenRouter/NVIDIA.
    """
    def __init__(self):
        self._keys: List[Tuple[str, str]] = []  # list of (key_value, key_name)
        self._current_index: int = 0
        self._client_cache: Dict[int, Any] = {}
        self.reload_keys()

    def reload_keys(self):
        load_dotenv(override=True)
        keys: List[Tuple[str, str]] = []
        for name in ["GEMINI_API_KEY1", "GEMINI_API_KEY2", "GEMINI_API_KEY3", "GEMINI_API_KEY", "GOOGLE_API_KEY"]:
            val = (os.getenv(name) or "").strip()
            if val and not any(k[0] == val for k in keys):
                keys.append((val, name))
        self._keys = keys
        self._client_cache.clear()

    @property
    def key_count(self) -> int:
        return len(self._keys)

    def get_current_key(self) -> Tuple[Optional[str], Optional[str], int]:
        if not self._keys:
            return None, None, 0
        idx = self._current_index % len(self._keys)
        key, name = self._keys[idx]
        return key, name, idx

    def get_client(self, index: Optional[int] = None):
        from google import genai
        if not self._keys:
            self.reload_keys()
        if not self._keys:
            raise ProviderAuthError("No Gemini API keys (GEMINI_API_KEY1, GEMINI_API_KEY2, GEMINI_API_KEY3) configured in .env")

        target_idx = (index if index is not None else self._current_index) % len(self._keys)
        if target_idx not in self._client_cache:
            key, name = self._keys[target_idx]
            self._client_cache[target_idx] = genai.Client(api_key=key)
        return self._client_cache[target_idx]

    def rotate_to_next_key(self, reason: str = "") -> Tuple[Optional[str], Optional[str], int]:
        if not self._keys:
            return None, None, 0
        old_idx = self._current_index % len(self._keys)
        old_name = self._keys[old_idx][1]
        self._current_index = (self._current_index + 1) % len(self._keys)
        new_idx = self._current_index % len(self._keys)
        new_name = self._keys[new_idx][1]
        logger.warning(
            "Rotating Gemini API key from %s to %s (index %d -> %d). Reason: %s",
            old_name, new_name, old_idx, new_idx, reason[:120]
        )
        return self.get_current_key()


GEMINI_KEY_MANAGER = GeminiKeyManager()


def get_gemini_client(key_index: Optional[int] = None):
    """Return active Gemini Client (cached for current key in rotation)."""
    return GEMINI_KEY_MANAGER.get_client(index=key_index)


def rotate_gemini_key(reason: str = "") -> Tuple[Optional[str], Optional[str], int]:
    """Rotate to the next Gemini key in the rotation pool."""
    return GEMINI_KEY_MANAGER.rotate_to_next_key(reason)


def reset_gemini_client():
    """Reset the Gemini client pool and reload keys from environment."""
    GEMINI_KEY_MANAGER.reload_keys()


def warm_gemini_client(model: Optional[str] = None) -> bool:
    """Pre-flight warmup of Gemini client connection."""
    try:
        c = get_gemini_client()
        target_model = model or GEMINI_MODEL_LIVE
        c.models.generate_content(
            model=target_model,
            contents="ping",
        )
        return True
    except Exception as exc:
        logger.debug("Gemini client warm-up skipped/failed: %s", exc)
        return False


def call_gemini_with_rotation(
    generate_fn,
    *args,
    max_attempts: Optional[int] = None,
    **kwargs,
) -> Any:
    """Execute a Gemini generation function with automatic 3-key rotation.
    If the current key hits a rate limit (429), quota exhaustion, 503 or transient error,
    it automatically rotates to the next key and retries immediately.
    """
    total_keys = max(GEMINI_KEY_MANAGER.key_count, 1)
    attempts = max_attempts or total_keys
    last_exc = None

    for attempt in range(attempts):
        client = get_gemini_client()
        _, key_name, _ = GEMINI_KEY_MANAGER.get_current_key()
        try:
            result = generate_fn(client, *args, **kwargs)
            GEMINI_CIRCUIT_BREAKER.record_success()
            return result
        except Exception as exc:
            last_exc = exc
            err_str = str(exc)
            if is_fatal_auth_error(exc):
                logger.error("Fatal authentication error on Gemini key %s: %s", key_name, err_str[:120])
                rotate_gemini_key(f"Fatal auth error: {err_str[:60]}")
                continue

            if is_transient_failover_error(exc) or "RESOURCE_EXHAUSTED" in err_str or "429" in err_str or "503" in err_str:
                retry_after = extract_retry_after(exc)
                logger.warning(
                    "Gemini key %s failed with transient/quota error (%s). Rotating key (attempt %d/%d).",
                    key_name, err_str[:80], attempt + 1, attempts
                )
                rotate_gemini_key(f"Quota/transient error: {err_str[:60]}")
                continue

            # Non-quota error, don't keep rotating blindly
            logger.warning("Gemini invocation error on %s: %s", key_name, err_str[:120])
            break

    GEMINI_CIRCUIT_BREAKER.record_failure(last_exc)
    raise ProviderUnavailableError(f"All Gemini keys exhausted or failed: {last_exc}")


# ---------------------------------------------------------------------------
# Backup Providers: OpenRouter & NVIDIA Clients
# ---------------------------------------------------------------------------
_WARM_OPENROUTER_CLIENT: Optional[OpenAI] = None
_WARM_NVIDIA_CLIENT: Optional[OpenAI] = None
_WARM_ASYNC_OPENROUTER_CLIENT: Optional[AsyncOpenAI] = None
_WARM_ASYNC_NVIDIA_CLIENT: Optional[AsyncOpenAI] = None


def get_openrouter_client() -> OpenAI:
    """Return warm OpenRouter client."""
    global _WARM_OPENROUTER_CLIENT
    key = get_openrouter_api_key()
    if not key:
        raise ProviderAuthError("OpenRouter API key is not configured in .env (openrouter / OPENROUTER_API_KEY)")
    if _WARM_OPENROUTER_CLIENT is None:
        _WARM_OPENROUTER_CLIENT = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=key)
    return _WARM_OPENROUTER_CLIENT


def get_nvidia_client() -> OpenAI:
    """Return warm NVIDIA NIM client."""
    global _WARM_NVIDIA_CLIENT
    key = get_nvidia_api_key()
    if not key:
        raise ProviderAuthError("NVIDIA API key is not configured in .env (NVIDIA / NVIDIA_API_KEY)")
    if _WARM_NVIDIA_CLIENT is None:
        _WARM_NVIDIA_CLIENT = OpenAI(base_url=NVIDIA_BASE_URL, api_key=key)
    return _WARM_NVIDIA_CLIENT


def get_async_openrouter_client() -> AsyncOpenAI:
    """Return warm Async OpenRouter client."""
    global _WARM_ASYNC_OPENROUTER_CLIENT
    key = get_openrouter_api_key()
    if not key:
        raise ProviderAuthError("OpenRouter API key is not configured")
    if _WARM_ASYNC_OPENROUTER_CLIENT is None:
        _WARM_ASYNC_OPENROUTER_CLIENT = AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=key)
    return _WARM_ASYNC_OPENROUTER_CLIENT


def get_async_nvidia_client() -> AsyncOpenAI:
    """Return warm Async NVIDIA NIM client."""
    global _WARM_ASYNC_NVIDIA_CLIENT
    key = get_nvidia_api_key()
    if not key:
        raise ProviderAuthError("NVIDIA API key is not configured")
    if _WARM_ASYNC_NVIDIA_CLIENT is None:
        _WARM_ASYNC_NVIDIA_CLIENT = AsyncOpenAI(base_url=NVIDIA_BASE_URL, api_key=key)
    return _WARM_ASYNC_NVIDIA_CLIENT


def _extract_message_text(msg: Any) -> str:
    """Extract content from an OpenAI chat completion message, accounting for Nemotron reasoning tokens."""
    content = (getattr(msg, "content", None) or "").strip()
    if content:
        return content

    # Nemotron emits reasoning before content
    reasoning = (getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or "").strip()
    if reasoning:
        return reasoning

    return ""


def call_backup_chat_sync(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: float = 45.0,
) -> Tuple[str, str]:
    """Synchronously call backup provider (OpenRouter first, then NVIDIA if OpenRouter fails).
    Returns (content, provider_model_used).
    """
    if not is_failover_enabled():
        raise ProviderUnavailableError("LLM failover to backup providers is disabled (AI_FAILOVER_ENABLED=false)")

    formatted_messages = list(messages)
    if json_mode:
        json_instruction = (
            "CRITICAL: Output must be valid JSON conforming strictly to the requested schema. "
            "Output raw JSON only without markdown formatting or code blocks."
        )
        # Check if system message exists
        has_system = any(m.get("role") == "system" for m in formatted_messages)
        if has_system:
            formatted_messages = [
                {**m, "content": f"{m['content']}\n\n{json_instruction}"} if m.get("role") == "system" else m
                for m in formatted_messages
            ]
        else:
            formatted_messages.insert(0, {"role": "system", "content": json_instruction})

    # 1. Try OpenRouter
    or_key = get_openrouter_api_key()
    if or_key:
        or_model = model or OPENROUTER_MODEL
        try:
            client = get_openrouter_client()
            resp = client.chat.completions.create(
                model=or_model,
                messages=formatted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            raw = _extract_message_text(resp.choices[0].message)
            content = clean_json_markdown(raw) if json_mode else raw
            return content, f"openrouter:{or_model}"
        except Exception as or_exc:
            logger.warning("OpenRouter backup failed (%s); trying NVIDIA NIM fallback", str(or_exc)[:120])

    # 2. Try NVIDIA NIM
    nv_key = get_nvidia_api_key()
    if nv_key:
        nv_model = model or NVIDIA_MODEL
        try:
            client = get_nvidia_client()
            resp = client.chat.completions.create(
                model=nv_model,
                messages=formatted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            raw = _extract_message_text(resp.choices[0].message)
            content = clean_json_markdown(raw) if json_mode else raw
            return content, f"nvidia:{nv_model}"
        except Exception as nv_exc:
            logger.error("NVIDIA NIM backup also failed: %s", str(nv_exc)[:120])
            raise ProviderUnavailableError(f"Both OpenRouter and NVIDIA backup providers failed: {nv_exc}")

    raise ProviderAuthError("Neither OpenRouter nor NVIDIA API keys are configured in .env")


async def stream_backup_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 256,
    timeout: float = 15.0,
) -> AsyncIterator[str]:
    """Async generator streaming chunks from OpenRouter, falling back to NVIDIA NIM."""
    if not is_failover_enabled():
        return

    # Try OpenRouter streaming
    or_key = get_openrouter_api_key()
    if or_key:
        or_model = model or OPENROUTER_MODEL
        try:
            client = get_async_openrouter_client()
            stream = await client.chat.completions.create(
                model=or_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                timeout=timeout,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                text = (getattr(delta, "content", None) or "")
                if text:
                    yield text
            return
        except Exception as or_exc:
            logger.warning("OpenRouter streaming failed (%s); falling back to NVIDIA NIM streaming", or_exc)

    # Try NVIDIA streaming
    nv_key = get_nvidia_api_key()
    if nv_key:
        nv_model = model or NVIDIA_MODEL
        try:
            client = get_async_nvidia_client()
            stream = await client.chat.completions.create(
                model=nv_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                timeout=timeout,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                text = (getattr(delta, "content", None) or "")
                if text:
                    yield text
            return
        except Exception as nv_exc:
            logger.error("NVIDIA NIM streaming failed: %s", nv_exc)
            raise ProviderUnavailableError(f"Streaming failed on both OpenRouter and NVIDIA: {nv_exc}")

    raise ProviderAuthError("No backup API keys configured for streaming")


# Backward compatibility aliases
call_bedrock_chat_sync = call_backup_chat_sync
stream_bedrock_chat = stream_backup_chat
call_tokenharbor_chat_sync = call_backup_chat_sync
stream_tokenharbor_chat = stream_backup_chat


# ---------------------------------------------------------------------------
# Health Checks & Diagnostic Probes
# ---------------------------------------------------------------------------
def check_gemini_health() -> Dict[str, Any]:
    """Test primary Gemini API connectivity across all 3 rotation keys."""
    keys = GEMINI_KEY_MANAGER._keys
    if not keys:
        GEMINI_KEY_MANAGER.reload_keys()
        keys = GEMINI_KEY_MANAGER._keys

    if not keys:
        return {"status": "unconfigured", "error": "No GEMINI_API_KEY1/2/3 configured in .env"}

    from google.genai import types

    results = []
    any_ok = False
    active_key, active_name, active_idx = GEMINI_KEY_MANAGER.get_current_key()

    for idx, (key_val, key_name) in enumerate(keys):
        t0 = time.perf_counter()
        try:
            client = GEMINI_KEY_MANAGER.get_client(index=idx)
            resp = client.models.generate_content(
                model=GEMINI_MODEL_LIVE,
                contents="ping",
                config=types.GenerateContentConfig(
                    max_output_tokens=5,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    http_options=types.HttpOptions(timeout=10000, retry_options=types.HttpRetryOptions(attempts=1)),
                ),
            )
            lat = round((time.perf_counter() - t0) * 1000.0, 1)
            results.append({
                "key_name": key_name,
                "status": "ok",
                "latency_ms": lat,
                "response": (resp.text or "").strip()[:20],
                "error": None,
            })
            any_ok = True
        except Exception as exc:
            lat = round((time.perf_counter() - t0) * 1000.0, 1)
            status_code = "auth_error" if is_fatal_auth_error(exc) else ("rate_limited" if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc) else "error")
            results.append({
                "key_name": key_name,
                "status": status_code,
                "latency_ms": lat,
                "error": str(exc)[:120],
            })

    if any_ok:
        GEMINI_CIRCUIT_BREAKER.record_success()
        return {
            "status": "ok",
            "model": GEMINI_MODEL_LIVE,
            "active_key": active_name,
            "keys_tested": results,
            "latency_ms": results[0]["latency_ms"] if results else None,
            "error": None,
        }
    else:
        # All keys failed
        return {
            "status": "exhausted",
            "model": GEMINI_MODEL_LIVE,
            "active_key": active_name,
            "keys_tested": results,
            "error": "All configured Gemini keys are rate-limited or unavailable",
        }


def check_backup_health() -> Dict[str, Any]:
    """Test secondary OpenRouter and tertiary NVIDIA backup providers."""
    or_key = get_openrouter_api_key()
    nv_key = get_nvidia_api_key()

    if not or_key and not nv_key:
        return {"status": "unconfigured", "error": "Neither openrouter nor NVIDIA keys configured in .env"}

    providers: Dict[str, Any] = {}
    any_ok = False

    if or_key:
        t0 = time.perf_counter()
        try:
            client = get_openrouter_client()
            resp = client.chat.completions.create(
                model=OPENROUTER_MODEL,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=16,
                temperature=0.0,
                timeout=10.0,
            )
            lat = round((time.perf_counter() - t0) * 1000.0, 1)
            text = _extract_message_text(resp.choices[0].message)
            providers["openrouter"] = {"status": "ok", "latency_ms": lat, "model": OPENROUTER_MODEL, "response": text[:20]}
            any_ok = True
        except Exception as exc:
            lat = round((time.perf_counter() - t0) * 1000.0, 1)
            providers["openrouter"] = {"status": "error", "latency_ms": lat, "error": str(exc)[:120]}

    if nv_key:
        t0 = time.perf_counter()
        try:
            client = get_nvidia_client()
            resp = client.chat.completions.create(
                model=NVIDIA_MODEL,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=16,
                temperature=0.0,
                timeout=10.0,
            )
            lat = round((time.perf_counter() - t0) * 1000.0, 1)
            text = _extract_message_text(resp.choices[0].message)
            providers["nvidia"] = {"status": "ok", "latency_ms": lat, "model": NVIDIA_MODEL, "response": text[:20]}
            any_ok = True
        except Exception as exc:
            lat = round((time.perf_counter() - t0) * 1000.0, 1)
            providers["nvidia"] = {"status": "error", "latency_ms": lat, "error": str(exc)[:120]}

    return {
        "status": "ok" if any_ok else "error",
        "providers": providers,
        "fallback_available": any_ok,
    }


def check_bedrock_health() -> Dict[str, Any]:
    """Backward compatibility wrapper returning backup health."""
    return check_backup_health()


def check_tokenharbor_health() -> Dict[str, Any]:
    """Backward compatibility wrapper returning backup health."""
    return check_backup_health()


def check_all_llm_health() -> Dict[str, Any]:
    """Test all configured LLM providers and report consolidated health status."""
    gemini = check_gemini_health()
    backup = check_backup_health()

    any_ok = (gemini.get("status") == "ok") or (backup.get("status") == "ok")
    active_providers = []
    if gemini.get("status") == "ok":
        active_providers.append(f"Gemini (active: {gemini.get('active_key')}, {gemini.get('latency_ms')}ms)")
    if backup.get("providers", {}).get("openrouter", {}).get("status") == "ok":
        active_providers.append(f"OpenRouter ({OPENROUTER_MODEL})")
    if backup.get("providers", {}).get("nvidia", {}).get("status") == "ok":
        active_providers.append(f"NVIDIA ({NVIDIA_MODEL})")

    return {
        "status": "ok" if any_ok else "unavailable",
        "active_providers": active_providers,
        "providers": {
            "gemini": gemini,
            "backup": backup,
        },
        "primary_available": gemini.get("status") == "ok",
        "fallback_available": backup.get("status") == "ok",
        "circuit_breaker": GEMINI_CIRCUIT_BREAKER.state,
        "candidate_failover_allowed": can_failover_candidate_data(),
        "failover_enabled": is_failover_enabled(),
    }


def verify_backup_structured_output() -> Dict[str, Any]:
    """Startup verification: check that backup provider supports structured JSON output."""
    if not get_backup_api_key():
        return {"supported": False, "reason": "No backup API keys (openrouter/NVIDIA) configured"}
    try:
        content, model = call_backup_chat_sync(
            messages=[{"role": "user", "content": 'Return a JSON object with key "status" set to "ready".'}],
            json_mode=True,
            timeout=15.0,
        )
        data = json.loads(content.strip())
        if isinstance(data, dict) and data.get("status") == "ready":
            return {"supported": True, "model": model}
        return {"supported": False, "reason": f"Unexpected JSON response: {content[:80]}"}
    except Exception as exc:
        return {"supported": False, "error": str(exc)[:150]}


verify_bedrock_structured_output = verify_backup_structured_output
verify_tokenharbor_structured_output = verify_backup_structured_output
