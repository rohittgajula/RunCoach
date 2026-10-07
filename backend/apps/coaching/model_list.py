"""R15 §A: the provider's live model list (filtered to text chat models), the
"Check models" probe, and the admin's model cards (catalog + prices + our own stats)."""

from __future__ import annotations

import datetime as dt
import logging
import statistics
import time

from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.utils import timezone

from . import client as ai
from . import model_catalog as catalog

logger = logging.getLogger(__name__)

LIST_TTL_S = 3600
FAIL_TTL_S = 300
CHECK_FRESH = dt.timedelta(days=1)
CHECK_MAX = 12
CHECK_SPACING_S = 1.5
CHECK_TIMEOUT_S = 20
STATS_DAYS = 30

EXCLUDE = ("tts", "image", "embedding", "embed", "audio", "live", "robotics", "computer-use",
           "transcribe", "nano-banana", "omni", "customtools", "realtime", "whisper", "dall-e",
           "moderation", "imagen", "veo", "aqa")
PREFIXES = {"gemini": ("gemini", "gemma"), "openai": ("gpt-", "o1", "o3", "o4", "chatgpt")}

# Typical tokens per call when a tier has no history yet: (input, output).
DEFAULT_TOKENS = {"lite": (800, 80), "fast": (1500, 300), "coach": (3000, 500),
                  "deep": (6000, 1200)}

STATUS_OF_KIND = {"busy": "busy", "no_quota": "no_quota", "unavailable": "unavailable"}


def is_text_chat(provider: str, model_id: str) -> bool:
    m = model_id.lower()
    if any(word in m for word in EXCLUDE):
        return False
    return m.startswith(PREFIXES.get(provider, ("",)))


def filter_ids(provider: str, ids) -> list[str]:
    out = []
    for raw in ids:
        mid = str(raw or "").removeprefix("models/").strip()
        if mid and is_text_chat(provider, mid) and mid not in out:
            out.append(mid)
    return sorted(out)


def _fetch_ids(provider: str) -> list[str]:
    """The raw ids from the provider's models.list() (patched in tests)."""
    page = ai.get_client(provider).models.list()
    return [getattr(m, "id", None) or (m.get("id") if isinstance(m, dict) else None)
            for m in page]


def _key(provider: str) -> str:
    return f"ai:models:v1:{provider}"


def live_models(provider: str, refresh: bool = False) -> tuple[list[str] | None, str | None]:
    """(filtered ids, fetched_at ISO) from a 1-h cache, or (None, None) when the list
    can't be read (no key, network, provider error)."""
    if not ai.provider_configured(provider):
        return None, None
    try:
        hit = None if refresh else cache.get(_key(provider))
    except Exception:  # noqa: BLE001
        hit = None
    if hit is not None:
        return (hit.get("ids"), hit.get("fetched_at"))
    try:
        ids = filter_ids(provider, _fetch_ids(provider))
        value = {"ids": ids, "fetched_at": timezone.now().isoformat()}
        ttl = LIST_TTL_S
    except Exception as exc:  # noqa: BLE001 — the price table is the fallback list
        logger.warning("models.list failed for %s: %s", provider, str(exc)[:200])
        value, ttl = {"ids": None, "fetched_at": None}, FAIL_TTL_S
    try:
        cache.set(_key(provider), value, ttl)
    except Exception:  # noqa: BLE001
        pass
    return value["ids"], value["fetched_at"]


def priced(provider: str) -> list[str]:
    from .models import ModelPrice

    return list(ModelPrice.objects.filter(provider=provider).values_list("model", flat=True))


def model_list(provider: str, refresh: bool = False) -> tuple[list[str], str, str | None]:
    """(ids, source, fetched_at): live when readable, else the price table."""
    ids, fetched = live_models(provider, refresh)
    if ids:
        return ids, "live", fetched
    return sorted(priced(provider)), "price_table", None


def statuses(provider: str) -> dict:
    from .models import ModelStatus

    return {s.model: s for s in ModelStatus.objects.filter(provider=provider)}


def status_note(row) -> str | None:
    if row is None or row.status == "ok":
        return None
    return ai.hint_for(row.error_kind or row.status, row.provider, row.model)


def info(provider: str, model: str, rows: dict, priced_set: set) -> dict:
    row = rows.get(model)
    return {"id": model, "priced": model in priced_set,
            "status": row.status if row else "unknown",
            "checked_at": row.checked_at if row else None, "note": status_note(row)}


def model_status(provider: str, model: str) -> str:
    from .models import ModelStatus

    return (ModelStatus.objects.filter(provider=provider, model=model)
            .values_list("status", flat=True).first() or "unknown")


def acceptable(provider: str, model: str) -> bool:
    """A model a tier may be pointed at: priced, or in the live list."""
    from .models import ModelPrice

    if ModelPrice.objects.filter(provider=provider, model=model).exists():
        return True
    ids, _ = live_models(provider)
    return bool(ids) and model in ids


# --- "Check models" ------------------------------------------------------------------------

def plan_check(provider: str, models: list[str] | None, force: bool) -> tuple[list, list]:
    """(queued, skipped) — at most 12, never-checked first, then oldest-checked."""
    rows = statuses(provider)
    candidates = list(models) if models else model_list(provider)[0]
    now = timezone.now()
    queued, skipped = [], []
    for model in candidates:
        row = rows.get(model)
        if row and not force and now - row.checked_at < CHECK_FRESH:
            skipped.append(model)
        else:
            queued.append(model)
    queued.sort(key=lambda m: (rows.get(m) is not None,
                               rows[m].checked_at if m in rows else now))
    return queued[:CHECK_MAX], skipped


def probe(provider: str, model: str) -> tuple[str, str, str]:
    """One tiny call, one attempt. → (status, error_kind, detail). Logged as admin_check."""
    from .models import AIRequestLog

    started = time.monotonic()
    tokens = (0, 0)
    try:
        client = ai.get_client(provider)
        try:
            client = client.with_options(timeout=CHECK_TIMEOUT_S)
        except Exception:  # noqa: BLE001 — fakes in tests have no with_options
            pass
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=5)
        usage = getattr(response, "usage", None)
        if usage:
            tokens = (usage.prompt_tokens or 0, usage.completion_tokens or 0)
        result = ("ok", "", "")
    except Exception as exc:  # noqa: BLE001
        kind = ai.classify(exc)
        result = (STATUS_OF_KIND.get(kind, "error"), kind, scrub(str(exc))[:300])
    AIRequestLog.objects.create(
        athlete=None, operation="admin_check", tier="admin", provider=provider, model=model,
        prompt_version="admin", input_tokens=tokens[0], output_tokens=tokens[1],
        latency_ms=int((time.monotonic() - started) * 1000),
        estimated_cost_usd=ai.estimate_cost(model, tokens[0], tokens[1], provider),
        status="ok" if result[0] == "ok" else "error", error=result[2][:500],
        error_kind=result[1])
    return result


def run_check(provider: str, models: list[str]) -> dict:
    from .models import ModelStatus

    done = {}
    for i, model in enumerate(models[:CHECK_MAX]):
        if i:
            ai._sleep(CHECK_SPACING_S)
        status, kind, detail = probe(provider, model)
        ModelStatus.objects.update_or_create(
            provider=provider, model=model,
            defaults={"status": status, "error_kind": kind, "detail": detail,
                      "checked_at": timezone.now()})
        done[model] = status
    return done


def scrub(text: str) -> str:
    from django.conf import settings

    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        secret = getattr(settings, key, "")
        if secret:
            text = (text or "").replace(secret, "***")
    return text or ""


# --- model cards ---------------------------------------------------------------------------

def tier_tokens(days: int = STATS_DAYS) -> dict[str, tuple[int, int]]:
    """Median (input, output) tokens per successful call of each tier, else defaults."""
    from .models import AIRequestLog

    since = timezone.now() - dt.timedelta(days=days)
    out = {}
    for tier in catalog.TIERS:
        rows = list(AIRequestLog.objects.filter(tier=tier, status="ok", created_at__gte=since,
                                                input_tokens__gt=0)
                    .values_list("input_tokens", "output_tokens")[:2000])
        if rows:
            out[tier] = (int(statistics.median(r[0] for r in rows)),
                         int(statistics.median(r[1] for r in rows)))
        else:
            out[tier] = DEFAULT_TOKENS[tier]
    return out


def measured(provider: str, days: int = STATS_DAYS) -> dict[str, dict]:
    from .models import AIRequestLog

    since = timezone.now() - dt.timedelta(days=days)
    rows = (AIRequestLog.objects.filter(provider=provider, created_at__gte=since)
            .exclude(status__in=["refused", "cached"]).values("model")
            .annotate(total=Count("id"), ok=Count("id", filter=Q(status__in=["ok", "invalid"])),
                      bad=Count("id", filter=Q(status__in=["error", "fallback"])),
                      lat=Avg("latency_ms", filter=Q(status="ok")),
                      cost=Avg("estimated_cost_usd", filter=Q(status="ok"))))
    return {r["model"]: r for r in rows}


def cards(provider: str, refresh: bool = False) -> dict:
    from .models import ModelPrice

    ids, source, fetched = model_list(provider, refresh)
    rows = statuses(provider)
    prices = {p.model: p for p in ModelPrice.objects.filter(provider=provider)}
    tokens = tier_tokens()
    stats = measured(provider)
    out = []
    for model in ids:
        base = info(provider, model, rows, set(prices))
        meta = catalog.card(model)
        price = prices.get(model)
        rates = ((price.input_per_m_usd, price.output_per_m_usd) if price
                 else ai.PRICING.get(model))
        status = base["status"]
        free_ok = None
        if provider == "gemini" and status != "unknown":
            free_ok = True if status == "ok" else (False if status in ("no_quota",
                                                                        "unavailable") else None)
        cost_level = meta["cost_level"]
        if free_ok:
            cost_level = "free_tier"
        m = stats.get(model) or {}
        total = int(m.get("total") or 0)
        out.append({
            **base, "label": meta["label"], "family": meta["family"], "known": meta["known"],
            "summary": meta["summary"], "best_for": meta["best_for"], "speed": meta["speed"],
            "quality": meta["quality"], "cost_level": cost_level,
            "price_in_per_1m": float(rates[0]) if rates else None,
            "price_out_per_1m": float(rates[1]) if rates else None,
            "est_cost_per_call_usd": {
                tier: (round(t[0] / 1e6 * rates[0] + t[1] / 1e6 * rates[1], 6) if rates
                       else None) for tier, t in tokens.items()},
            "context_window": meta.get("context_window"),
            "free_tier_ok": free_ok,
            "calls": total,
            "avg_latency_ms": int(m["lat"]) if m.get("lat") else None,
            "error_rate": round((m.get("bad") or 0) / total, 3) if total else 0.0,
            "avg_cost_usd": round(float(m["cost"]), 6) if m.get("cost") is not None else None,
        })
    return {"provider": provider, "source": source, "fetched_at": fetched, "models": out}


def recommended(provider: str, tier: str) -> str | None:
    """The model the one-click switch picks for a tier: env model first when this is the
    env provider, then the catalog's preference list; skips models whose last probe was
    not ok and (when the live list is known) models not in it."""
    from django.conf import settings

    rows = statuses(provider)
    live, _ = live_models(provider)
    prefs = list(catalog.RECOMMENDED.get(provider, {}).get(tier, []))
    if provider == settings.AI_PROVIDER:
        env_model = ai.env_route(tier)[1]
        if env_model:
            prefs.insert(0, env_model)
    for model in prefs:
        row = rows.get(model)
        if row is not None and row.status != "ok":
            continue
        if live and model not in live and not (provider == settings.AI_PROVIDER
                                               and model == ai.env_route(tier)[1]):
            continue
        return model
    # Nothing in the list survived: any probed-ok model of a suitable family.
    for model, row in rows.items():
        if row.status == "ok" and tier in catalog.card(model)["best_for"]:
            return model
    return None
