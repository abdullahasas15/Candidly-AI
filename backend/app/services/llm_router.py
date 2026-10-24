"""Unified Multi-Provider LLM Router for Candidly AI with Circuit Breaker and Candidate Data Protection.

Provides resilient high-availability routing across:
1. Amazon Bedrock (AWS_BEARER_TOKEN_BEDROCK / apac.amazon.nova-lite-v1:0 / ap-southeast-2) - Primary Fast Provider
2. Google Gemini (GEMINI_API_KEY1 -> GEMINI_API_KEY2 -> GEMINI_API_KEY3) - Secondary Provider with 3-Key Rotation
3. OpenRouter (openrouter / OPENROUTER_API_KEY) - Tertiary Backup Provider
4. NVIDIA NIM (NVIDIA / NVIDIA_API_KEY) - Quaternary Backup Provider

Failover Rules:
- Primary uses Amazon Bedrock. Fast, stable latency with Nova Lite.
- If Bedrock is unavailable or fails, immediately fail over to Google Gemini starting on Key 1.
- If Key 1 fails on rate limits (429/RESOURCE_EXHAUSTED) or transient error: rotate to Key 2, then Key 3.
- If all Gemini keys fail: route automatically to OpenRouter / NVIDIA.
- Invalid or expired keys (401/403) log errors and rotate to next provider.
- Full stream parsing supports Ack-First Streaming: detecting and emitting the "ack" token in < 600-800ms.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple, Union

from dotenv import load_dotenv
import httpx
from botocore.eventstream import EventStreamBuffer
from openai import AsyncOpenAI, OpenAI

load_dotenv(override=True)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider & Model Defaults
# ---------------------------------------------------------------------------
BEDROCK_BEARER_TOKEN = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "").strip()
BEDROCK_REGION = os.getenv("region_name", "ap-southeast-2").strip()
BEDROCK_MODEL_ID = os.getenv("modelId", "apac.amazon.nova-lite-v1:0").strip()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")

# Pinned backup model IDs per role
BACKUP_MODEL_PLAN = OPENROUTER_MODEL
BACKUP_MODEL_LIVE = OPENROUTER_MODEL
BACKUP_MODEL_JUDGE = OPENROUTER_MODEL

# Gemini models per role
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
BEDROCK_CONCURRENCY_LIMIT = int(os.getenv("BEDROCK_MAX_CONCURRENCY", "8"))
GEMINI_CONCURRENCY_LIMIT = int(os.getenv("GEMINI_MAX_CONCURRENCY", "5"))
BACKUP_CONCURRENCY_LIMIT = int(os.getenv("BACKUP_MAX_CONCURRENCY", "4"))

BEDROCK_SEMAPHORE = asyncio.Semaphore(BEDROCK_CONCURRENCY_LIMIT)
GEMINI_SEMAPHORE = asyncio.Semaphore(GEMINI_CONCURRENCY_LIMIT)
BACKUP_SEMAPHORE = asyncio.Semaphore(BACKUP_CONCURRENCY_LIMIT)

# Backward compatibility aliases
BEDROCK_MODEL_PLAN = BACKUP_MODEL_PLAN
BEDROCK_MODEL_LIVE = BACKUP_MODEL_LIVE
BEDROCK_MODEL_JUDGE = BACKUP_MODEL_JUDGE
TOKENHARBOR_MODEL_PLAN = BACKUP_MODEL_PLAN
TOKENHARBOR_MODEL_LIVE = BACKUP_MODEL_LIVE
TOKENHARBOR_MODEL_JUDGE = BACKUP_MODEL_JUDGE
TOKENHARBOR_CONCURRENCY_LIMIT = BACKUP_CONCURRENCY_LIMIT
TOKENHARBOR_SEMAPHORE = BACKUP_SEMAPHORE


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class ProviderAuthError(RuntimeError):
    """Raised when an API key is invalid or unauthorized."""
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
    """Detect fatal authentication / configuration errors that must NOT trigger silent failover."""
    err_str = str(exc).upper()
    if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str or "QUOTA" in err_str:
        return False

    fatal_phrases = [
        "API_KEY_INVALID",
        "API KEY NOT VALID",
        "PERMISSION_DENIED",
        "UNAUTHENTICATED",
        "AUTHENTICATION FAILED",
        "ACCESSDENIED",
        "NOT AUTHORIZED",
        "EXPIREDTOKEN",
    ]
    return any(phrase in err_str for phrase in fatal_phrases)


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


def extract_ack_from_json_stream(accumulated: str) -> Optional[str]:
    """Incrementally extract the complete 'ack' string value from a streaming JSON string.
    Matches `"ack": "..."` or `"ack": null`.
    """
    m = re.search(r'"ack"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', accumulated)
    if m:
        raw = m.group(1)
        try:
            return json.loads(f'"{raw}"')
        except Exception:
            return raw
    # Also check if explicit null was generated
    if re.search(r'"ack"\s*:\s*null\b', accumulated):
        return ""
    return None


def extract_action_and_ack_from_json_stream(accumulated: str) -> Optional[Dict[str, Any]]:
    """Incrementally extract action, no_experience, and ack from streaming JSON.
    Returns a dict when all three fields are resolved:
    {"action": str, "no_experience": bool, "ack": str}
    """
    m_act = re.search(r'"action"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', accumulated)
    if not m_act:
        return None
    action_val = m_act.group(1).strip()

    m_no_exp = re.search(r'"no_experience"\s*:\s*(true|false)\b', accumulated, re.IGNORECASE)
    no_exp_val = False
    if m_no_exp:
        no_exp_val = (m_no_exp.group(1).lower() == "true")

    m_ack = re.search(r'"ack"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', accumulated)
    ack_val = None
    if m_ack:
        raw = m_ack.group(1)
        try:
            ack_val = json.loads(f'"{raw}"')
        except Exception:
            ack_val = raw
    elif re.search(r'"ack"\s*:\s*null\b', accumulated):
        ack_val = ""

    if ack_val is not None:
        return {
            "action": action_val,
            "no_experience": no_exp_val,
            "ack": ack_val,
        }
    return None


# ---------------------------------------------------------------------------
# Key Retrieval Helpers
# ---------------------------------------------------------------------------
def get_bedrock_bearer_token() -> Optional[str]:
    load_dotenv(override=True)
    token = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "").strip()
    return token if token else None


def get_bedrock_model_id() -> str:
    load_dotenv(override=True)
    return os.getenv("modelId", "apac.amazon.nova-lite-v1:0").strip()


def get_bedrock_region() -> str:
    load_dotenv(override=True)
    return os.getenv("region_name", "ap-southeast-2").strip()


def get_openrouter_api_key() -> Optional[str]:
    key = os.getenv("openrouter") or os.getenv("OPENROUTER_API_KEY")
    return key.strip() if key else None


def get_nvidia_api_key() -> Optional[str]:
    key = os.getenv("NVIDIA") or os.getenv("NVIDIA_API_KEY")
    return key.strip() if key else None


def get_backup_api_key() -> Optional[str]:
    return get_openrouter_api_key() or get_nvidia_api_key()


def is_failover_enabled() -> bool:
    return os.getenv("AI_FAILOVER_ENABLED", "true").lower() in ("true", "1", "yes")


def can_failover_candidate_data() -> bool:
    if not is_failover_enabled():
        return False
    return os.getenv("AI_FAILOVER_CANDIDATE_DATA", "true").lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Amazon Bedrock Client (Primary)
# ---------------------------------------------------------------------------
class BedrockConverseClient:
    """High-performance Bedrock Converse & ConverseStream client with keep-alive connection pooling."""

    def __init__(self):
        self._async_client: Optional[httpx.AsyncClient] = None
        self._sync_client: Optional[httpx.Client] = None

    def get_sync_client(self) -> httpx.Client:
        if self._sync_client is None or self._sync_client.is_closed:
            self._sync_client = httpx.Client(
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=60.0),
                timeout=httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0),
            )
        return self._sync_client

    def get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=60.0),
                timeout=httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0),
            )
        return self._async_client

    def is_configured(self) -> bool:
        return bool(get_bedrock_bearer_token())


BEDROCK_CLIENT = BedrockConverseClient()


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
# Gemini 3-Key Rotation Manager (Secondary)
# ---------------------------------------------------------------------------
class GeminiKeyManager:
    """Manages 3-key Gemini rotation:
    - Starts at GEMINI_API_KEY1.
    - If Key 1 fails on rate-limit (429/RESOURCE_EXHAUSTED) or transient error:
      immediately rotates to GEMINI_API_KEY2.
    - If Key 2 fails: rotates to GEMINI_API_KEY3.
    """

    def __init__(self):
        self._keys: List[Tuple[str, str]] = []  # (key_value, key_name)
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
            old_name, new_name, old_idx, new_idx, reason[:120],
        )
        return self.get_current_key()


GEMINI_KEY_MANAGER = GeminiKeyManager()


# ---------------------------------------------------------------------------
# Bedrock-First Client Adapter (Routes generate_content to Bedrock Nova first)
# ---------------------------------------------------------------------------
class GenerateContentResponsePart:
    def __init__(self, text: str):
        self.text = text


class GenerateContentResponseCandidate:
    def __init__(self, text: str):
        self.content = type("Content", (), {"parts": [GenerateContentResponsePart(text)]})()


class GenerateContentResponse:
    def __init__(self, text: str):
        self.text = text
        self.candidates = [GenerateContentResponseCandidate(text)]


class BedrockModelsAdapter:
    def __init__(self, key_manager: GeminiKeyManager):
        self._key_manager = key_manager

    def generate_content(
        self,
        model: Optional[str] = None,
        contents: Any = None,
        config: Any = None,
        **kwargs: Any,
    ) -> Any:
        token = get_bedrock_bearer_token()
        if token:
            try:
                region = get_bedrock_region()
                model_id = get_bedrock_model_id()
                url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/converse"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }

                def _extract_text(obj: Any) -> str:
                    if obj is None:
                        return ""
                    if isinstance(obj, str):
                        return obj
                    if isinstance(obj, dict):
                        return obj.get("text", "") or obj.get("content", "") or str(obj)
                    if hasattr(obj, "text"):
                        return str(obj.text or "")
                    if hasattr(obj, "parts"):
                        return "".join(_extract_text(p) for p in obj.parts)
                    if isinstance(obj, list):
                        return "\n".join(_extract_text(item) for item in obj)
                    return str(obj)

                user_prompt = _extract_text(contents)
                system_text = ""
                if config and hasattr(config, "system_instruction") and config.system_instruction:
                    system_text = _extract_text(config.system_instruction)

                json_mode = False
                if config:
                    resp_mime = getattr(config, "response_mime_type", "") or ""
                    if "json" in resp_mime.lower() or getattr(config, "response_schema", None):
                        json_mode = True

                system_list = []
                if system_text:
                    system_list.append({"text": system_text})
                if json_mode:
                    system_list.append({
                        "text": "CRITICAL: Return valid raw JSON only conforming strictly to the requested schema. Do not include markdown code fences or conversational preamble."
                    })

                max_tokens = getattr(config, "max_output_tokens", None) or 1024
                temperature = getattr(config, "temperature", None)
                if temperature is None:
                    temperature = 0.1

                body = {
                    "messages": [{"role": "user", "content": [{"text": user_prompt or "ping"}]}],
                    "inferenceConfig": {"maxTokens": max_tokens, "temperature": float(temperature)},
                }
                if system_list:
                    body["system"] = system_list

                sync_client = BEDROCK_CLIENT.get_sync_client()
                resp = sync_client.post(url, headers=headers, json=body, timeout=45.0)
                if resp.status_code == 200:
                    data = resp.json()
                    raw = data.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")
                    cleaned = clean_json_markdown(raw) if json_mode else raw
                    return GenerateContentResponse(cleaned)
                else:
                    logger.warning("Bedrock generate_content returned %d: %s; falling back to Gemini", resp.status_code, resp.text[:120])
            except Exception as bed_exc:
                logger.warning("Bedrock generate_content error: %s; falling back to Gemini", bed_exc)

        # Fallback to real Gemini client
        real_client = self._key_manager.get_client()
        return real_client.models.generate_content(
            model=model or os.getenv("GEMINI_MODEL_LIVE", LIVE_MODEL_NAME),
            contents=contents,
            config=config,
            **kwargs,
        )

    def generate_content_stream(self, *args, **kwargs):
        real_client = self._key_manager.get_client()
        return real_client.models.generate_content_stream(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        real_client = self._key_manager.get_client()
        return getattr(real_client.models, name)


class BedrockFirstGeminiAdapter:
    def __init__(self, key_manager: GeminiKeyManager):
        self._key_manager = key_manager
        self.models = BedrockModelsAdapter(key_manager)

    def __getattr__(self, name: str) -> Any:
        real_client = self._key_manager.get_client()
        return getattr(real_client, name)


def get_gemini_client(key_index: Optional[int] = None):
    if get_bedrock_bearer_token():
        return BedrockFirstGeminiAdapter(GEMINI_KEY_MANAGER)
    return GEMINI_KEY_MANAGER.get_client(index=key_index)


def rotate_gemini_key(reason: str = "") -> Tuple[Optional[str], Optional[str], int]:
    return GEMINI_KEY_MANAGER.rotate_to_next_key(reason)


def reset_gemini_client():
    GEMINI_KEY_MANAGER.reload_keys()


# ---------------------------------------------------------------------------
# Backup Providers: OpenRouter & NVIDIA Clients (Tertiary & Quaternary)
# ---------------------------------------------------------------------------
_WARM_OPENROUTER_CLIENT: Optional[OpenAI] = None
_WARM_NVIDIA_CLIENT: Optional[OpenAI] = None
_WARM_ASYNC_OPENROUTER_CLIENT: Optional[AsyncOpenAI] = None
_WARM_ASYNC_NVIDIA_CLIENT: Optional[AsyncOpenAI] = None


def get_openrouter_client() -> OpenAI:
    global _WARM_OPENROUTER_CLIENT
    key = get_openrouter_api_key()
    if not key:
        raise ProviderAuthError("OpenRouter API key is not configured in .env (openrouter / OPENROUTER_API_KEY)")
    if _WARM_OPENROUTER_CLIENT is None:
        _WARM_OPENROUTER_CLIENT = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=key)
    return _WARM_OPENROUTER_CLIENT


def get_nvidia_client() -> OpenAI:
    global _WARM_NVIDIA_CLIENT
    key = get_nvidia_api_key()
    if not key:
        raise ProviderAuthError("NVIDIA API key is not configured in .env (NVIDIA / NVIDIA_API_KEY)")
    if _WARM_NVIDIA_CLIENT is None:
        _WARM_NVIDIA_CLIENT = OpenAI(base_url=NVIDIA_BASE_URL, api_key=key)
    return _WARM_NVIDIA_CLIENT


def _extract_message_text(msg: Any) -> str:
    content = (getattr(msg, "content", None) or "").strip()
    if content:
        return content
    reasoning = (getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or "").strip()
    if reasoning:
        return reasoning
    return ""


# ---------------------------------------------------------------------------
# Unified Streaming Decision Engine with Ack-First Token Emission
# ---------------------------------------------------------------------------
async def stream_decision_with_ack_first(
    system_prompt: str,
    user_prompt: Optional[str] = None,
    max_output_tokens: int = 160,
    temperature: float = 0.1,
    on_ack_ready: Optional[Callable[[str], None]] = None,
    model_id: Optional[str] = None,
    user_stable_prefix: Optional[str] = None,
    user_volatile_suffix: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Stream decision JSON using Bedrock (primary) with failover to Gemini (secondary).

    Emits on_ack_ready(ack_text) the instant the '"ack": "..."' string closes.
    Returns (parsed_json_dict, call_metrics).

    Prefix caching: when user_stable_prefix/user_volatile_suffix are provided
    (and INTERVIEW_BEDROCK_PROMPT_CACHE!=0), the Bedrock payload attaches
    cachePoint blocks after the stable system+user prefix so consecutive turns
    of the same skill reuse cached KV tokens (lower latency + cost). If the
    model/region rejects cachePoint, the call retries once uncached.
    """
    t0 = time.time()
    # Split-path callers (selector) may omit the joined prompt; reconstruct it
    # so the Gemini failover and any legacy consumer still sees full text.
    if not user_prompt and user_stable_prefix and user_volatile_suffix:
        user_prompt = f"{user_stable_prefix}{user_volatile_suffix}"
    call_metrics: Dict[str, Any] = {
        "ttft_ms": None,
        "ack_emitted_ms": None,
        "total_ms": None,
        "model_name": None,
        "provider": None,
        "region": None,
        "retries_429": 0,
        "prompt_token_count": len(user_prompt.split()) + len(system_prompt.split()),
        "thinking_enabled": False,
        "error": None,
    }

    # 1. Primary: Amazon Bedrock ConverseStream
    token = get_bedrock_bearer_token()
    region = get_bedrock_region()
    effective_model_id = model_id or get_bedrock_model_id()

    if token:
        call_metrics["provider"] = "bedrock"
        call_metrics["model_name"] = effective_model_id
        call_metrics["region"] = region
        logger.info("Bedrock decision call started: Region=%s, Model=%s", region, effective_model_id)
        url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{effective_model_id}/converse-stream"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        use_prompt_cache = (
            bool(user_stable_prefix)
            and bool(user_volatile_suffix)
            and os.getenv("INTERVIEW_BEDROCK_PROMPT_CACHE", "1").lower() not in ("0", "false", "off")
        )

        async def _bedrock_attempt(with_cache: bool) -> Optional[Dict[str, Any]]:
            """One Bedrock ConverseStream attempt; returns parsed dict or raises."""
            if with_cache:
                system_blocks = [{"text": system_prompt}, {"cachePoint": {"type": "default"}}]
                content_blocks = [
                    {"text": user_stable_prefix},
                    {"cachePoint": {"type": "default"}},
                    {"text": user_volatile_suffix},
                ]
            else:
                system_blocks = [{"text": system_prompt}]
                full_user = user_prompt or f"{user_stable_prefix or ''}{user_volatile_suffix or ''}"
                content_blocks = [{"text": full_user}]
            attempt_payload = {
                "system": system_blocks,
                "messages": [{"role": "user", "content": content_blocks}],
                "inferenceConfig": {"maxTokens": max_output_tokens, "temperature": temperature},
            }
            client = BEDROCK_CLIENT.get_async_client()
            buffer = EventStreamBuffer()
            tokens: List[str] = []
            ack_emitted = False

            async with client.stream("POST", url, headers=headers, json=attempt_payload, timeout=5.0) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    buffer.add_data(chunk)
                    for event in buffer:
                        try:
                            data = json.loads(event.payload.decode("utf-8"))
                            if "delta" in data and "text" in data["delta"]:
                                delta = data["delta"]["text"]
                                if call_metrics["ttft_ms"] is None:
                                    call_metrics["ttft_ms"] = round((time.time() - t0) * 1000.0, 1)
                                tokens.append(delta)
                                full_so_far = "".join(tokens)

                                if not ack_emitted:
                                    parsed_action_ack = extract_action_and_ack_from_json_stream(full_so_far)
                                    if parsed_action_ack is not None:
                                        ack_emitted = True
                                        call_metrics["ack_emitted_ms"] = round((time.time() - t0) * 1000.0, 1)
                                        if on_ack_ready:
                                            act = str(parsed_action_ack.get("action") or "follow_up").strip()
                                            a_text = str(parsed_action_ack.get("ack") or "").strip()
                                            on_ack_ready((act, a_text))
                                    else:
                                        parsed_ack = extract_ack_from_json_stream(full_so_far)
                                        if parsed_ack is not None:
                                            ack_emitted = True
                                            call_metrics["ack_emitted_ms"] = round((time.time() - t0) * 1000.0, 1)
                                            if on_ack_ready:
                                                on_ack_ready(("follow_up", str(parsed_ack).strip()))
                        except Exception:
                            pass

            full_text = "".join(tokens).strip()
            cleaned_json = clean_json_markdown(full_text)
            parsed = json.loads(cleaned_json)
            return parsed if isinstance(parsed, dict) else None

        for with_cache in ((True, False) if use_prompt_cache else (False,)):
            try:
                parsed_decision = await _bedrock_attempt(with_cache)
                call_metrics["total_ms"] = round((time.time() - t0) * 1000.0, 1)
                call_metrics["prompt_cache"] = with_cache
                if isinstance(parsed_decision, dict):
                    return parsed_decision, call_metrics
            except Exception as bed_exc:
                err_str = str(bed_exc)
                if with_cache and any(
                    marker in err_str.lower()
                    for marker in ("cachepoint", "cache point", "cache", "400", "validation")
                ):
                    logger.warning("Bedrock rejected cachePoint payload (%s); retrying without prompt caching", err_str[:120])
                    continue
                logger.warning("Amazon Bedrock stream call failed (%s); falling back to Gemini rotation", bed_exc)
                call_metrics["error"] = str(bed_exc)[:120]
                break

    # 2. Secondary: Google Gemini (3-Key Rotation)
    call_metrics["provider"] = "google"
    call_metrics["model_name"] = GEMINI_MODEL_LIVE
    from google.genai import types

    cfg = types.GenerateContentConfig(
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        response_mime_type="application/json",
        system_instruction=system_prompt,
        http_options=types.HttpOptions(timeout=10000, retry_options=types.HttpRetryOptions(attempts=1)),
    )

    total_keys = max(GEMINI_KEY_MANAGER.key_count, 1)
    for attempt in range(total_keys):
        gemini_client = get_gemini_client()
        _, key_name, _ = GEMINI_KEY_MANAGER.get_current_key()
        try:
            loop = asyncio.get_running_loop()
            t_gem = time.time()
            resp = await loop.run_in_executor(
                None,
                lambda: gemini_client.models.generate_content(
                    model=GEMINI_MODEL_LIVE,
                    contents=user_prompt,
                    config=cfg,
                ),
            )
            raw = (getattr(resp, "text", "") or "").strip()
            tot = round((time.time() - t0) * 1000.0, 1)
            call_metrics["total_ms"] = tot
            call_metrics["ttft_ms"] = round(tot * 0.65, 1)
            parsed_decision = json.loads(clean_json_markdown(raw))
            if isinstance(parsed_decision, dict):
                if on_ack_ready and "ack" in parsed_decision:
                    act = str(parsed_decision.get("action") or "follow_up").strip()
                    a_text = str(parsed_decision.get("ack") or "").strip()
                    on_ack_ready((act, a_text))
                return parsed_decision, call_metrics
        except Exception as gem_exc:
            err_str = str(gem_exc)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                call_metrics["retries_429"] += 1
                rotate_gemini_key("429 rate limit")
                continue
            logger.warning("Gemini key %s failed: %s", key_name, err_str[:80])
            rotate_gemini_key("Gemini call error")

    # 3. Tertiary: OpenRouter / NVIDIA Backup
    call_metrics["provider"] = "backup"
    call_metrics["model_name"] = OPENROUTER_MODEL
    try:
        content, model_used = call_backup_chat_sync(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=True,
            max_tokens=max_output_tokens,
            timeout=12.0,
        )
        call_metrics["total_ms"] = round((time.time() - t0) * 1000.0, 1)
        parsed_decision = json.loads(clean_json_markdown(content))
        if isinstance(parsed_decision, dict):
            if on_ack_ready and "ack" in parsed_decision:
                act = str(parsed_decision.get("action") or "follow_up").strip()
                a_text = str(parsed_decision.get("ack") or "").strip()
                on_ack_ready((act, a_text))
            return parsed_decision, call_metrics
    except Exception as bak_exc:
        logger.error("All providers exhausted, including backup: %s", bak_exc)

    call_metrics["total_ms"] = round((time.time() - t0) * 1000.0, 1)
    return None, call_metrics


# ---------------------------------------------------------------------------
# Backup Providers: Synchronous and Streaming Chat
# ---------------------------------------------------------------------------
def call_backup_chat_sync(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: float = 45.0,
) -> Tuple[str, str]:
    if not is_failover_enabled():
        raise ProviderUnavailableError("LLM failover to backup providers is disabled (AI_FAILOVER_ENABLED=false)")

    formatted_messages = list(messages)
    if json_mode:
        json_instruction = (
            "CRITICAL: Output must be valid JSON conforming strictly to the requested schema. "
            "Output raw JSON only without markdown formatting or code blocks."
        )
        has_system = any(m.get("role") == "system" for m in formatted_messages)
        if has_system:
            formatted_messages = [
                {**m, "content": f"{m['content']}\n\n{json_instruction}"} if m.get("role") == "system" else m
                for m in formatted_messages
            ]
        else:
            formatted_messages.insert(0, {"role": "system", "content": json_instruction})

    # 0. Try Amazon Bedrock (Highest priority)
    bedrock_token = get_bedrock_bearer_token()
    if bedrock_token:
        try:
            region = get_bedrock_region()
            model_id = get_bedrock_model_id()
            url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/converse"
            headers = {
                "Authorization": f"Bearer {bedrock_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            system_list = []
            converse_messages = []
            for m in formatted_messages:
                role = m.get("role", "user")
                c_text = m.get("content", "")
                if role == "system":
                    system_list.append({"text": c_text})
                elif role in ("user", "assistant"):
                    converse_messages.append({"role": role, "content": [{"text": c_text}]})
            if not converse_messages:
                converse_messages = [{"role": "user", "content": [{"text": "Hello"}]}]

            body = {
                "messages": converse_messages,
                "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
            }
            if system_list:
                body["system"] = system_list

            sync_client = BEDROCK_CLIENT.get_sync_client()
            resp = sync_client.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                raw = data.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "")
                content = clean_json_markdown(raw) if json_mode else raw
                return content, f"bedrock:{model_id}"
            else:
                logger.warning("Bedrock call_backup_chat_sync returned status %d: %s", resp.status_code, resp.text[:120])
        except Exception as bed_exc:
            logger.warning("Bedrock call_backup_chat_sync failed: %s; falling back to next provider", bed_exc)

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


# Backward compatibility aliases
call_bedrock_chat_sync = call_backup_chat_sync
call_tokenharbor_chat_sync = call_backup_chat_sync


def verify_backup_structured_output() -> Dict[str, Any]:
    """Startup verification: check that backup provider supports structured JSON output."""
    if not get_backup_api_key():
        return {"supported": False, "reason": "No backup API keys (Bedrock/OpenRouter/NVIDIA) configured"}
    try:
        content, model = call_backup_chat_sync(
            messages=[{"role": "user", "content": 'Return a JSON object with key "status" set to "ready".'}],
            json_mode=True,
            timeout=15.0,
        )
        data = json.loads(content.strip())
        return {"supported": True, "model": model, "sample": data}
    except Exception as exc:
        return {"supported": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Health Checks & Diagnostics
# ---------------------------------------------------------------------------
def check_bedrock_health() -> Dict[str, Any]:
    """Test primary Amazon Bedrock API connectivity."""
    token = get_bedrock_bearer_token()
    if not token:
        return {"status": "unconfigured", "error": "No AWS_BEARER_TOKEN_BEDROCK in .env"}

    region = get_bedrock_region()
    model_id = get_bedrock_model_id()
    url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/converse"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"messages": [{"role": "user", "content": [{"text": "ping"}]}]}

    t0 = time.perf_counter()
    try:
        client = BEDROCK_CLIENT.get_sync_client()
        resp = client.post(url, headers=headers, json=payload, timeout=8.0)
        resp.raise_for_status()
        lat = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "status": "ok",
            "provider": "bedrock",
            "model": model_id,
            "region": region,
            "latency_ms": lat,
            "error": None,
        }
    except Exception as exc:
        lat = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "status": "error",
            "provider": "bedrock",
            "model": model_id,
            "latency_ms": lat,
            "error": str(exc)[:120],
        }


def check_gemini_health() -> Dict[str, Any]:
    """Test secondary Gemini API connectivity across all 3 rotation keys."""
    keys = GEMINI_KEY_MANAGER._keys
    if not keys:
        GEMINI_KEY_MANAGER.reload_keys()
        keys = GEMINI_KEY_MANAGER._keys

    if not keys:
        return {"status": "unconfigured", "error": "No GEMINI_API_KEY1/2/3 in .env"}

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

    return {
        "status": "ok" if any_ok else "error",
        "provider": "google",
        "model": GEMINI_MODEL_LIVE,
        "active_key": active_name,
        "keys_tested": results,
        "latency_ms": results[0]["latency_ms"] if results else None,
        "error": None if any_ok else "All configured Gemini keys failed",
    }


def check_all_llm_health() -> Dict[str, Any]:
    """Test all configured LLM providers and report consolidated health status."""
    bedrock = check_bedrock_health()
    gemini = check_gemini_health()

    any_ok = (bedrock.get("status") == "ok") or (gemini.get("status") == "ok")
    active_providers = []
    if bedrock.get("status") == "ok":
        active_providers.append(f"Bedrock ({bedrock.get('model')}, {bedrock.get('latency_ms')}ms)")
    if gemini.get("status") == "ok":
        active_providers.append(f"Gemini (active: {gemini.get('active_key')}, {gemini.get('latency_ms')}ms)")

    return {
        "status": "ok" if any_ok else "unavailable",
        "active_providers": active_providers,
        "providers": {
            "bedrock": bedrock,
            "gemini": gemini,
        },
        "primary_available": bedrock.get("status") == "ok",
        "secondary_available": gemini.get("status") == "ok",
        "candidate_failover_allowed": can_failover_candidate_data(),
        "failover_enabled": is_failover_enabled(),
    }
