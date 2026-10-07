"""The provider boundary.

Everything OpenAI-specific lives here. The rest of the app names a TIER and passes a
Pydantic model; it never sees a model id, a token count or a request shape. M6 adds a
second provider behind this same function as a test that the seam holds.
"""

from __future__ import annotations

import json
import logging
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
    """


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

        kwargs = {"api_key": key, "timeout": settings.AI_TIMEOUT_SEC}
        if info["base_url"]:
            kwargs["base_url"] = info["base_url"]
        _CLIENTS[cache_key] = OpenAI(**kwargs)
    return _CLIENTS[cache_key]


def tier_for(operation: str) -> str:
    if operation == "admin_test":
        return "admin"
    return settings.AI_MODEL_TIERS.get(operation, "fast")


def _db_route(tier: str) -> tuple[str, str] | None:
    """The admin's choice for a tier (AIConfig), or None. Never raises: outside a
    database (pure tests, scripts) the env default applies."""
    try:
        from .models import AIConfig

        row = AIConfig.objects.filter(tier=tier).values_list("provider", "model").first()
    except Exception:  # noqa: BLE001
        return None
    return (row[0], row[1]) if row and row[1] else None


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

    Uses strict Structured Outputs rather than asking for JSON in the prompt, so
    malformed JSON stops being a failure mode to handle and becomes one the decoder
    prevents. A schema-valid answer can still be semantically wrong — that is what
    the validators downstream are for.
    """
    provider, model = route_for(operation)
    client = get_client(provider)
    retries = settings.AI_MAX_RETRIES if max_retries is None else max_retries
    json_mode = "schema"

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

            stats = _usage_stats(provider, model, response, latency, attempt)
            return schema.model_validate_json(_json_text(choice.message.content)), stats

        except ValidationError as exc:
            last_error = exc
            logger.warning("ai %s failed validation (attempt %s): %s", operation, attempt, exc)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            message = str(exc)
            # A rate limit is a wait, not a failure. Back off and let the caller
            # decide; retrying immediately makes it worse.
            if "429" in message or "rate limit" in message.lower():
                logger.warning("ai %s rate limited", operation)
                raise AIUnavailable("Rate limited. Try again shortly.") from exc
            logger.warning("ai %s error (attempt %s): %s", operation, attempt, message)
            if _is_client_error(exc):
                # A provider that rejects the strict json_schema (seen with some
                # OpenAI-compatible endpoints) gets one try in plain JSON mode, with the
                # schema in the prompt and the same Pydantic validation after.
                if json_mode == "schema" and _schema_rejected(message):
                    json_mode = "object"
                    attempt -= 1          # the fallback does not use up a retry
                    continue
                raise AIUnavailable(f"{operation} rejected: {message[:300]}") from exc

        if attempt < retries:
            time.sleep(min(2**attempt, 8))

    raise AIUnavailable(f"{operation} failed after {retries + 1} attempts: {last_error}")


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
    provider, model = route_for(operation)
    client = get_client(provider)
    extra = dict(PROVIDERS.get(provider, {}).get("chat_extra") or {})
    retries = settings.AI_MAX_RETRIES
    conversation = list(messages)
    audit: list[dict] = []

    for iteration in range(max_iterations):
        final_turn = iteration == max_iterations - 1
        if before_call:
            before_call(model)

        response = None
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            started = time.monotonic()
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=conversation,
                    tools=tools,
                    tool_choice="none" if final_turn else "auto",
                    # OpenAI: function tools on /v1/chat/completions are rejected for
                    # reasoning models unless reasoning is off (a 400 on gpt-5.6-terra).
                    # Chat is a conversational loop over tools that do the thinking in
                    # Python, so no reasoning is the right setting anyway. Per provider:
                    # see PROVIDERS[...]["chat_extra"].
                    **extra,
                )
                if on_call:
                    on_call(
                        _usage_stats(provider, model, response,
                                     int((time.monotonic() - started) * 1000), attempt),
                        None,
                    )
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if on_call:
                    on_call({"provider": provider, "model": model, "retry_count": attempt}, exc)
                message = str(exc)
                if "429" in message or "rate limit" in message.lower():
                    raise AIUnavailable("Rate limited. Try again shortly.") from exc
                logger.warning("ai %s error (attempt %s): %s", operation, attempt, message)
                if _is_client_error(exc):
                    # A 4xx (other than 429) is a bad request: retrying it sends the same
                    # bad request again and is billed spend for a guaranteed failure.
                    raise AIUnavailable(f"{operation} rejected: {message[:300]}") from exc
                if attempt < retries:
                    time.sleep(min(2**attempt, 8))
        if response is None:
            raise AIUnavailable(f"{operation} failed after {retries + 1} attempts: {last_error}")

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
