"""The provider boundary.

Everything OpenAI-specific lives here. The rest of the app names a TIER and passes a
Pydantic model; it never sees a model id, a token count or a request shape. M6 adds a
second provider behind this same function as a test that the seam holds.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Callable, TypeVar

from django.conf import settings
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Cached. NEVER construct a client inline: building and using one in a single
# expression lets it be garbage-collected mid-request, closing its connection pool on
# the way out, and the call dies with "client has been closed".
_CLIENTS: dict[tuple, Any] = {}

# R14 §14: Google AI Studio's OpenAI-compatible endpoint. Gemini goes through the same
# `openai` SDK and the same two functions below — only the base URL and key differ.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

PROVIDERS: dict[str, dict] = {
    "openai": {
        "label": "OpenAI", "base_url": None, "key_setting": "OPENAI_API_KEY",
        # Function tools on /v1/chat/completions need reasoning off for the gpt-5.x family.
        "chat_extra": {"reasoning_effort": "none"},
        "features": {"tools": True, "json_schema": True, "streaming": True, "vision": True},
    },
    "gemini": {
        "label": "Google AI Studio (Gemini)", "base_url": GEMINI_BASE_URL,
        "key_setting": "GEMINI_API_KEY",
        # Not every Gemini model accepts reasoning_effort="none" (2.5 Pro / 3.x keep
        # thinking on), so nothing extra is sent; thinking tokens are billed as output.
        "chat_extra": {},
        "features": {"tools": True, "json_schema": True, "streaming": True, "vision": True},
    },
}

# USD per million tokens — the fallback when the editable price table (ModelPrice,
# R14) has no row for a model. Approximate and only used for reporting; the provider's
# dashboard is the authoritative number.
PRICING = {
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5-nano": (0.05, 0.40),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3-pro-preview": (2.00, 12.00),
}
TIERS = ("lite", "fast", "coach", "deep")


class AIUnavailable(Exception):
    """The model could not be reached or could not produce a valid answer.

    Callers must degrade rather than surface this: an athlete is never left without a
    session because an API was down.

    R15: `error_kind` is the plain category (see classify) and `attempts` lists every
    route that was tried and failed ({provider, model, error, error_kind, latency_ms,
    retry_count}), so the caller can log each one.
    """

    def __init__(self, message: str = "", *, error_kind: str = "other",
                 attempts: list[dict] | None = None):
        super().__init__(message)
        self.error_kind = error_kind
        self.attempts = list(attempts or [])


def provider_key(provider: str) -> str:
    info = PROVIDERS.get(provider)
    return getattr(settings, info["key_setting"], "") if info else ""


def provider_configured(provider: str) -> bool:
    return bool(provider_key(provider))


def get_client(provider: str = "openai"):
    info = PROVIDERS.get(provider)
    if info is None:
        raise AIUnavailable(f"Unknown AI provider '{provider}'.")
    key = provider_key(provider)
    if not key:
        raise AIUnavailable(f"No {info['key_setting']} configured.")
    import hashlib

    cache_key = (provider, hashlib.sha256(key.encode()).hexdigest()[:16])
    if cache_key not in _CLIENTS:
        from openai import OpenAI

        # max_retries=0: the SDK's own silent retries would blow the R15 backoff budget;
        # call_policy below decides what is retried and for how long.
        kwargs = {"api_key": key, "timeout": settings.AI_TIMEOUT_SEC, "max_retries": 0}
        if info["base_url"]:
            kwargs["base_url"] = info["base_url"]
        _CLIENTS[cache_key] = OpenAI(**kwargs)
    return _CLIENTS[cache_key]


def tier_for(operation: str) -> str:
    if operation.startswith("admin_"):
        return "admin"
    return settings.AI_MODEL_TIERS.get(operation, "fast")


def _db_row(tier: str) -> tuple | None:
    """(provider, model, fallback_provider, fallback_model) for a tier, or None. Never
    raises: outside a database (pure tests, scripts) the env default applies."""
    try:
        from .models import AIConfig

        return AIConfig.objects.filter(tier=tier).values_list(
            "provider", "model", "fallback_provider", "fallback_model").first()
    except Exception:  # noqa: BLE001
        return None


def _db_route(tier: str) -> tuple[str, str] | None:
    """The admin's choice for a tier (AIConfig), or None."""
    row = _db_row(tier)
    return (row[0], row[1]) if row and row[1] else None


def fallback_route(tier: str) -> tuple[tuple[str, str], str] | None:
    """R15: ((provider, model), source) a tier falls back to — the admin's choice, else
    the env route for that tier."""
    row = _db_row(tier)
    if row and row[2] and row[3]:
        return (row[2], row[3]), "db"
    route = env_route(tier)
    return (route, "env") if route[1] else None


def routes_for(operation: str) -> list[tuple[str, str]]:
    """[primary] or [primary, fallback]: the fallback only when it differs and its
    provider has a key."""
    primary = route_for(operation)
    routes = [primary]
    fallback = fallback_route(tier_for(operation))
    if fallback and fallback[0] != primary and provider_configured(fallback[0][0]):
        routes.append(fallback[0])
    return routes


def env_route(tier: str) -> tuple[str, str]:
    model = settings.AI_MODELS.get(tier) or settings.AI_MODELS.get("fast") or ""
    return settings.AI_PROVIDER, model


def route_for(operation: str) -> tuple[str, str]:
    """(provider, model) for an operation: AIConfig row for its tier, else env."""
    tier = tier_for(operation)
    provider, model = _db_route(tier) or env_route(tier)
    if not model:
        raise AIUnavailable(f"No model configured for tier '{tier}'.")
    return provider, model


def model_for(operation: str) -> str:
    return route_for(operation)[1]


def provider_for(operation: str) -> str:
    """The provider an operation would use (for log rows written without a call)."""
    tier = tier_for(operation)
    return (_db_route(tier) or env_route(tier))[0]


def price_for(model: str, provider: str | None = None) -> tuple[float, float] | None:
    try:
        from .models import ModelPrice

        rows = ModelPrice.objects.filter(model=model)
        if provider:
            rows = rows.filter(provider=provider)
        row = rows.values_list("input_per_m_usd", "output_per_m_usd").first()
        if row:
            return float(row[0]), float(row[1])
    except Exception:  # noqa: BLE001
        pass
    return PRICING.get(model)


def estimate_cost(model: str, input_tokens: int, output_tokens: int,
                  provider: str | None = None) -> float:
    rates = price_for(model, provider)
    if not rates:
        return 0.0
    return round(input_tokens / 1e6 * rates[0] + output_tokens / 1e6 * rates[1], 6)


# --- R15: error kinds, retry policy, fallback --------------------------------------------

MAX_TRANSIENT_RETRIES = 2
BACKOFF_BASE_S = 1.5
BACKOFF_BUDGET_S = 12.0
_BUSY_STATUS = {500, 502, 503, 504}


def _sleep(seconds: float) -> None:     # patched in tests
    time.sleep(seconds)


def _jitter(high: float) -> float:      # patched in tests
    return random.uniform(0, high)


def backoff_delay(retry: int) -> float:
    """Exponential with jitter: retry 0 → 1.5–3 s, retry 1 → 3–4.5 s."""
    return BACKOFF_BASE_S * (2 ** retry) + _jitter(BACKOFF_BASE_S)


def _status_of(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def _is_quota(text: str) -> bool:
    """A 429 that waiting a few seconds won't fix (vs a per-minute rate limit)."""
    if "limit: 0" in text or "insufficient_quota" in text or "perday" in text \
            or "per_day" in text or "per day" in text:
        return True
    if "perminute" in text or "per_minute" in text or "per minute" in text \
            or "rate limit" in text:
        return False
    return "quota" in text or "billing" in text


def classify(exc: Exception) -> str:
    """busy | no_quota | unavailable | auth | bad_request | timeout | other."""
    if isinstance(exc, AIUnavailable) and exc.error_kind != "other":
        return exc.error_kind
    code = _status_of(exc)
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    if "timeout" in name or isinstance(exc, TimeoutError) or "timed out" in text:
        return "timeout"
    if code == 429 or (code is None and ("429" in text or "resource_exhausted" in text)):
        return "no_quota" if _is_quota(text) else "busy"
    if code in _BUSY_STATUS or "overloaded" in text or "high demand" in text \
            or (code is None and ("503" in text or "unavailable" in text and "model" not in text)):
        return "busy"
    if code == 404 or "no longer available" in text or "not found" in text:
        return "unavailable"
    if code in (401, 403) or "api key" in text and "invalid" in text:
        return "auth"
    if isinstance(code, int) and 400 <= code < 500:
        return "bad_request"
    return "other"


def is_transient(kind: str) -> bool:
    """Worth waiting a moment for: overloaded or a per-minute rate limit. Not quota."""
    return kind == "busy"


def hint_for(kind: str | None, provider: str = "", model: str = "") -> str:
    """One plain sentence for the admin's "recent errors"."""
    google = provider == "gemini"
    if kind == "no_quota":
        if google and "pro" in (model or ""):
            return "Pro models need billing on your Google AI Studio key."
        if google:
            return ("This model has no free-tier quota left on your Google AI Studio key — "
                    "wait for the daily reset, pick another model or enable billing.")
        return "Your OpenAI account is out of quota or credit."
    if kind == "busy":
        who = "Google" if google else "The provider"
        return (f"{who} says this model is busy right now (503/rate limit); calls were "
                "retried and then fell back.")
    if kind == "unavailable":
        return ("This model isn't available to your key (retired or not offered to new "
                "users) — pick another.")
    if kind == "auth":
        return "The API key was rejected — check the key in the server's environment."
    if kind == "bad_request":
        return ("The provider rejected the request — often a feature this model doesn't "
                "support (tools, JSON schema, images).")
    if kind == "timeout":
        return "The model took too long to answer."
    return "Unexpected error — see the message."


def call_policy(fn: Callable[[], Any], *, operation: str = "") -> tuple[Any, int]:
    """Run fn() with the R15 transient retry rule. Returns (result, transient retries).
    Raises the last exception (with `_transient_retries` set on it)."""
    slept = 0.0
    retry = 0
    while True:
        try:
            return fn(), retry
        except Exception as exc:  # noqa: BLE001
            kind = classify(exc)
            if not is_transient(kind) or retry >= MAX_TRANSIENT_RETRIES:
                exc._transient_retries = retry  # type: ignore[attr-defined]
                raise
            delay = backoff_delay(retry)
            if slept + delay > BACKOFF_BUDGET_S:
                exc._transient_retries = retry  # type: ignore[attr-defined]
                raise
            logger.warning("ai %s %s (retry %s in %.1fs)", operation, kind, retry + 1, delay)
            _sleep(delay)
            slept += delay
            retry += 1


def attempt_record(provider: str, model: str, exc: Exception, latency_ms: int = 0,
                   retry_count: int = 0) -> dict:
    return {"provider": provider, "model": model, "error": str(exc)[:500],
            "error_kind": classify(exc), "latency_ms": latency_ms, "retry_count": retry_count}


def complete(
    *,
    operation: str,
    system: str,
    user: str,
    schema: type[T],
    max_retries: int | None = None,
    image_data_url: str | None = None,
) -> tuple[T, dict]:
    """One structured call. Returns (validated result, usage stats).

    R15: tried on the tier's route; if that keeps failing, once more on the tier's
    fallback route. A successful answer after a failed primary carries the failed
    attempts in stats["failed_attempts"] (the caller logs them as `fallback` rows); a
    total failure raises AIUnavailable with `.attempts`.
    """
    routes = routes_for(operation)
    failed: list[dict] = []
    last: Exception | None = None
    for provider, model in routes:
        started = time.monotonic()
        try:
            result, stats = _complete_on(provider, model, operation=operation, system=system,
                                         user=user, schema=schema, max_retries=max_retries,
                                         image_data_url=image_data_url)
        except Exception as exc:  # noqa: BLE001
            last = exc
            failed.append(attempt_record(provider, model, exc,
                                         int((time.monotonic() - started) * 1000),
                                         getattr(exc, "_transient_retries", 0)))
            if len(failed) < len(routes):
                logger.warning("ai %s: %s/%s failed (%s); falling back", operation, provider,
                               model, failed[-1]["error_kind"])
            continue
        if failed:
            stats["failed_attempts"] = failed
        return result, stats
    raise AIUnavailable(str(last) if isinstance(last, AIUnavailable)
                        else f"{operation} failed: {last}",
                        error_kind=failed[-1]["error_kind"] if failed else "other",
                        attempts=failed) from last


def _complete_on(provider: str, model: str, *, operation: str, system: str, user: str,
                 schema: type[T], max_retries: int | None,
                 image_data_url: str | None) -> tuple[T, dict]:
    """Strict Structured Outputs on one route, rather than asking for JSON in the prompt,
    so malformed JSON stops being a failure mode to handle and becomes one the decoder
    prevents. A schema-valid answer can still be semantically wrong — that is what the
    validators downstream are for."""
    client = get_client(provider)
    retries = settings.AI_MAX_RETRIES if max_retries is None else max_retries
    json_mode = "schema"
    transient = 0
    slept = 0.0

    last_error: Exception | None = None
    attempt = -1
    while attempt < retries:
        attempt += 1
        started = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _system_for(system, schema, json_mode)},
                    {"role": "user", "content": _user_content(user, image_data_url)},
                ],
                response_format=_response_format(schema, json_mode),
            )
            latency = int((time.monotonic() - started) * 1000)

            choice = response.choices[0]
            # A 200 can still carry a truncated answer. Treat it as a failure rather
            # than validating half an object.
            if choice.finish_reason == "length":
                raise AIUnavailable("Response was cut off before it finished.")
            if getattr(choice.message, "refusal", None):
                raise AIUnavailable(f"Model refused: {choice.message.refusal}")

            stats = _usage_stats(provider, model, response, latency, attempt + transient)
            return schema.model_validate_json(_json_text(choice.message.content)), stats

        except ValidationError as exc:
            last_error = exc
            logger.warning("ai %s failed validation (attempt %s): %s", operation, attempt, exc)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            message = str(exc)
            kind = classify(exc)
            if is_transient(kind):
                # Overloaded / per-minute rate: wait (bounded) and try the same request
                # again; this does not use up a validation retry.
                delay = backoff_delay(transient)
                if transient < MAX_TRANSIENT_RETRIES and slept + delay <= BACKOFF_BUDGET_S:
                    logger.warning("ai %s %s (retry %s in %.1fs)", operation, kind,
                                   transient + 1, delay)
                    _sleep(delay)
                    slept += delay
                    transient += 1
                    attempt -= 1
                    continue
                err = AIUnavailable(f"{operation}: {provider}/{model} {kind}: {message[:300]}",
                                    error_kind=kind)
                err._transient_retries = transient  # type: ignore[attr-defined]
                raise err from exc
            logger.warning("ai %s error (attempt %s): %s", operation, attempt, message)
            if kind in ("no_quota", "unavailable", "auth", "timeout") or _is_client_error(exc):
                # A provider that rejects the strict json_schema (seen with some
                # OpenAI-compatible endpoints) gets one try in plain JSON mode, with the
                # schema in the prompt and the same Pydantic validation after.
                if kind == "bad_request" and json_mode == "schema" and _schema_rejected(message):
                    json_mode = "object"
                    attempt -= 1          # the fallback does not use up a retry
                    continue
                raise AIUnavailable(f"{operation} rejected: {message[:300]}",
                                    error_kind=kind) from exc

        if attempt < retries:
            _sleep(min(2**attempt, 8))

    raise AIUnavailable(f"{operation} failed after {retries + 1} attempts: {last_error}",
                        error_kind=classify(last_error) if last_error else "other")


def _user_content(text: str, image_data_url: str | None):
    """Plain text, or text plus one image for the vision-capable meal estimate."""
    if not image_data_url:
        return text
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]


def _response_format(schema, json_mode: str) -> dict:
    if json_mode == "object":
        return {"type": "json_object"}
    return {"type": "json_schema",
            "json_schema": {"name": schema.__name__, "strict": True,
                            "schema": _strict_schema(schema)}}


def _system_for(system: str, schema, json_mode: str) -> str:
    if json_mode != "object":
        return system
    return (f"{system}\n\nAnswer with one JSON object only, matching this JSON schema "
            f"exactly:\n{json.dumps(_strict_schema(schema))}")


def _schema_rejected(message: str) -> bool:
    text = message.lower()
    return any(word in text for word in ("response_format", "json_schema", "schema"))


def _json_text(content: str | None) -> str:
    """The JSON object in a reply. Strict mode returns it bare; JSON mode on some
    providers wraps it in a ```json fence."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    return text.strip()


def _usage_stats(provider: str, model: str, response, latency_ms: int, attempt: int) -> dict:
    usage = response.usage
    stats = {
        "provider": provider,
        "model": model,
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
        "latency_ms": latency_ms,
        "retry_count": attempt,
    }
    stats["estimated_cost_usd"] = estimate_cost(
        model, stats["input_tokens"], stats["output_tokens"], provider
    )
    return stats


def chat_with_tools(
    *,
    operation: str,
    messages: list[dict],
    tools: list[dict],
    dispatch: Callable[[str, dict], Any],
    max_iterations: int = 6,
    before_call: Callable[[str], None] | None = None,
    on_call: Callable[[dict | None, Exception | None], None] | None = None,
) -> tuple[str, list[dict]]:
    """A tool-use loop. Returns (final assistant text, tool-call audit records).

    The model may call tools; each call is executed by `dispatch(name, args)` — which
    is Python, scoped to one athlete — and the JSON result goes back to the model.
    That is the whole "Python calculates, the model interprets" rule applied to chat:
    the model never computes a plan or a calorie target, it asks for one.

    At most `max_iterations` model calls. The last allowed call is made with
    `tool_choice="none"`, so the loop always ends in an answer rather than in a
    half-finished tool chain the athlete never sees.

    `before_call(model)` runs before every model call (the budget gate raises from
    there) and `on_call(stats, error)` after it (the request log). Both are hooks so
    this module stays free of athlete and database concerns.
    """
    routes = routes_for(operation)
    route_index = 0
    conversation = list(messages)
    audit: list[dict] = []

    for iteration in range(max_iterations):
        final_turn = iteration == max_iterations - 1

        response = None
        while response is None:
            provider, model = routes[route_index]
            if before_call:
                before_call(model)
            started = time.monotonic()
            try:
                response = _chat_once(provider, model, conversation, tools, final_turn,
                                      operation)
            except Exception as exc:  # noqa: BLE001
                kind = classify(exc)
                latency = int((time.monotonic() - started) * 1000)
                retries = getattr(exc, "_transient_retries", 0)
                has_next = route_index + 1 < len(routes)
                if on_call:
                    on_call({"provider": provider, "model": model, "retry_count": retries,
                             "latency_ms": latency, "error_kind": kind,
                             "status": "fallback" if has_next else "error"}, exc)
                logger.warning("ai %s %s/%s failed (%s)%s", operation, provider, model, kind,
                               "; falling back" if has_next else "")
                if not has_next:
                    raise AIUnavailable(f"{operation} failed: {str(exc)[:300]}",
                                        error_kind=kind) from exc
                route_index += 1
                # Another provider: Gemini thought signatures mean nothing to it.
                conversation = [_strip_extra(m) for m in conversation]
                continue
            if on_call:
                on_call(_usage_stats(provider, model, response,
                                     int((time.monotonic() - started) * 1000), 0), None)

        choice = response.choices[0]
        message = choice.message
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls or final_turn:
            if choice.finish_reason == "length":
                raise AIUnavailable("Response was cut off before it finished.")
            if getattr(message, "refusal", None):
                raise AIUnavailable(f"Model refused: {message.refusal}")
            return (message.content or "").strip(), audit

        # Gemini may return tool calls without an id; the reply must still pair each
        # result with its call, so one is made up. Gemini 3 also attaches a "thought
        # signature" (extra_content) that has to be sent back with the call, or the
        # next request is a 400.
        call_ids = [getattr(call, "id", None) or f"call_{iteration}_{i}"
                    for i, call in enumerate(tool_calls)]
        conversation.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [_echo_call(call, call_id) for call, call_id in zip(tool_calls, call_ids)],
        })
        for call, call_id in zip(tool_calls, call_ids):
            name = call.function.name
            args: dict = {}
            try:
                args = json.loads(call.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be an object")
                result = dispatch(name, args)
            except Exception as exc:  # noqa: BLE001 — a tool error is the model's to handle
                logger.warning("tool %s failed: %s", name, exc)
                result = {"error": str(exc)[:300]}
            audit.append({"name": name, "arguments": args, "result": result})
            conversation.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result, default=str)[:20000],
            })

    raise AIUnavailable("Tool loop ended without an answer.")  # pragma: no cover


def _chat_once(provider: str, model: str, conversation: list[dict], tools: list[dict],
               final_turn: bool, operation: str):
    """One tool-loop model call on one route, with the R15 transient retry rule. Any
    other failure (or a 5xx after its retries) raises — the caller falls back."""
    client = get_client(provider)
    extra = dict(PROVIDERS.get(provider, {}).get("chat_extra") or {})

    def call():
        return client.chat.completions.create(
            model=model,
            messages=conversation,
            tools=tools,
            tool_choice="none" if final_turn else "auto",
            # OpenAI: function tools on /v1/chat/completions are rejected for reasoning
            # models unless reasoning is off (a 400 on gpt-5.6-terra). Chat is a
            # conversational loop over tools that do the thinking in Python, so no
            # reasoning is the right setting anyway. Per provider: PROVIDERS[...]["chat_extra"].
            **extra,
        )

    response, _ = call_policy(call, operation=operation)
    return response


def _strip_extra(message: dict) -> dict:
    if message.get("role") != "assistant" or not message.get("tool_calls"):
        return message
    return {**message, "tool_calls": [{k: v for k, v in c.items() if k != "extra_content"}
                                      for c in message["tool_calls"]]}


def _echo_call(call, call_id: str) -> dict:
    out = {"id": call_id, "type": "function",
           "function": {"name": call.function.name, "arguments": call.function.arguments}}
    extra = getattr(call, "extra_content", None)
    if extra is None:
        extra = (getattr(call, "model_extra", None) or {}).get("extra_content")
    if extra:
        out["extra_content"] = extra
    return out


def _is_client_error(exc: Exception) -> bool:
    """True for an HTTP 4xx other than 429 (openai.APIStatusError carries status_code)."""
    code = getattr(exc, "status_code", None)
    return isinstance(code, int) and 400 <= code < 500 and code != 429


def _strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic's JSON schema, adjusted for OpenAI strict mode.

    Strict mode requires every property listed in `required` and
    `additionalProperties: false` on every object, and it does not accept `$defs`
    references at the top level in all cases — so definitions are inlined.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                return resolve(defs[name])
            node = {key: resolve(value) for key, value in node.items()}
            if node.get("type") == "object":
                node["additionalProperties"] = False
                if "properties" in node:
                    node["required"] = list(node["properties"])
            return node
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def canonical_hash(payload: dict, prompt_version: str, model: str) -> str:
    """Stable across dict ordering, so the same context always hits the same cache row."""
    import hashlib

    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{blob}|{prompt_version}|{model}".encode()).hexdigest()
