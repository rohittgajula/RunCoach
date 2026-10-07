"""AI providers, per-tier routing, the price table, a test prompt and usage stats
(R14 §14). Keys never leave the server: only `configured: true/false`."""

from __future__ import annotations

import datetime as dt
import json
import time

from django.conf import settings
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.coaching import client as ai
from apps.coaching.models import AIConfig, AIRequestLog, ModelPrice

RANGES = {"7d": 7, "4w": 28, "3m": 91, "6m": 182, "1y": 365}
MAX_PROMPT = 2000


def provider_of_model(model: str) -> str:
    return "gemini" if model.startswith("gemini") else "openai"


def ensure_prices() -> None:
    """Seed the editable table from the built-in fallback the first time it is read."""
    if ModelPrice.objects.exists():
        return
    ModelPrice.objects.bulk_create(
        [ModelPrice(provider=provider_of_model(model), model=model, input_per_m_usd=rates[0],
                    output_per_m_usd=rates[1], note="default (approximate)")
         for model, rates in ai.PRICING.items()],
        ignore_conflicts=True)


def _models(provider: str) -> list[str]:
    return list(ModelPrice.objects.filter(provider=provider).values_list("model", flat=True))


@api_view(["GET"])
@permission_classes([IsAdminUser])
def providers(request):
    ensure_prices()
    return Response([{"key": key, "label": info["label"],
                      "configured": ai.provider_configured(key),
                      "base_url": info["base_url"], "features": info["features"],
                      "models": _models(key)}
                     for key, info in ai.PROVIDERS.items()])


def _config_body() -> dict:
    rows = {r.tier: r for r in AIConfig.objects.all()}
    tiers = []
    for tier in ai.TIERS:
        env_provider, env_model = ai.env_route(tier)
        row = rows.get(tier)
        provider, model = (row.provider, row.model) if row else (env_provider, env_model)
        tiers.append({"tier": tier, "provider": provider, "model": model,
                      "source": "db" if row else "env",
                      "env_provider": env_provider, "env_model": env_model,
                      "available": bool(model) and ai.provider_configured(provider),
                      "updated_at": row.updated_at if row else None})
    return {"tiers": tiers, "operations": dict(sorted(settings.AI_MODEL_TIERS.items()))}


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAdminUser])
def config(request):
    if request.method == "GET":
        return Response(_config_body())
    ensure_prices()
    items = request.data.get("tiers") if isinstance(request.data, dict) else None
    if not isinstance(items, list) or not items:
        return Response({"detail": "tiers must be a non-empty list."}, status=400)
    changes = []
    for item in items:
        if not isinstance(item, dict) or item.get("tier") not in ai.TIERS:
            return Response({"detail": f"tier must be one of {', '.join(ai.TIERS)}."}, status=400)
        if item.get("reset"):
            changes.append((item["tier"], None, None))
            continue
        provider, model = item.get("provider"), item.get("model")
        if provider not in ai.PROVIDERS:
            return Response({"detail": f"Unknown provider '{provider}'."}, status=400)
        if not ai.provider_configured(provider):
            return Response({"detail": f"{ai.PROVIDERS[provider]['label']} has no API key "
                                       "configured."}, status=400)
        if not isinstance(model, str) or not ModelPrice.objects.filter(
                provider=provider, model=model).exists():
            return Response({"detail": f"'{model}' is not in the {provider} price table — add "
                                       "it there first."}, status=400)
        changes.append((item["tier"], provider, model))
    for tier, provider, model in changes:
        if provider is None:
            AIConfig.objects.filter(tier=tier).delete()
        else:
            AIConfig.objects.update_or_create(tier=tier, defaults={"provider": provider,
                                                                   "model": model})
    return Response(_config_body())


@api_view(["POST"])
@permission_classes([IsAdminUser])
def test_prompt(request):
    """One call to a chosen provider + model. Logged (operation admin_test, no
    athlete), never budgeted, never given any athlete data."""
    data = request.data
    provider, model, prompt = data.get("provider"), data.get("model"), data.get("prompt")
    want_json = bool(data.get("json"))
    if provider not in ai.PROVIDERS:
        return Response({"detail": f"Unknown provider '{provider}'."}, status=400)
    if not isinstance(model, str) or not model.strip() or len(model) > 80:
        return Response({"detail": "model is required."}, status=400)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        return Response({"detail": f"prompt must be 1–{MAX_PROMPT} characters."}, status=400)
    if not ai.provider_configured(provider):
        return Response({"detail": f"{ai.PROVIDERS[provider]['label']} has no API key "
                                   "configured."}, status=400)
    body = {"ok": False, "text": "", "json": None, "latency_ms": 0, "input_tokens": 0,
            "output_tokens": 0, "cost_usd": 0.0, "error": None}
    started = time.monotonic()
    try:
        client = ai.get_client(provider)
        kwargs = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        if want_json:
            kwargs["response_format"] = {"type": "json_object"}
            kwargs["messages"].insert(0, {"role": "system",
                                          "content": "Answer with one JSON object only."})
        response = client.chat.completions.create(**kwargs)
        body["latency_ms"] = int((time.monotonic() - started) * 1000)
        text = (response.choices[0].message.content or "").strip()
        usage = response.usage
        body.update(ok=True, text=text[:8000],
                    input_tokens=usage.prompt_tokens if usage else 0,
                    output_tokens=usage.completion_tokens if usage else 0)
        if want_json:
            try:
                body["json"] = json.loads(ai._json_text(text))
            except ValueError:
                body["ok"], body["error"] = False, "The reply was not valid JSON."
        body["cost_usd"] = ai.estimate_cost(model, body["input_tokens"],
                                            body["output_tokens"], provider)
    except Exception as exc:  # noqa: BLE001 — shown to the admin, never raised
        body["latency_ms"] = int((time.monotonic() - started) * 1000)
        body["error"] = _safe_error(exc)
    AIRequestLog.objects.create(
        athlete=None, operation="admin_test", tier="admin", provider=provider, model=model,
        prompt_version="admin", input_tokens=body["input_tokens"],
        output_tokens=body["output_tokens"], latency_ms=body["latency_ms"],
        estimated_cost_usd=body["cost_usd"],
        status=AIRequestLog.Status.OK if body["ok"] else AIRequestLog.Status.ERROR,
        error=(body["error"] or "")[:500])
    return Response(body)


def _safe_error(exc: Exception) -> str:
    """An error message with any configured key scrubbed out (SDK errors can echo it)."""
    text = str(exc)[:400]
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        secret = getattr(settings, key, "")
        if secret:
            text = text.replace(secret, "***")
    return text


# --- prices ------------------------------------------------------------------------------

def price_json(row: ModelPrice) -> dict:
    return {"id": row.pk, "provider": row.provider, "model": row.model,
            "input_per_m_usd": row.input_per_m_usd, "output_per_m_usd": row.output_per_m_usd,
            "note": row.note, "updated_at": row.updated_at}


def _price_fields(data, partial: bool) -> dict | str:
    out = {}
    if "provider" in data or not partial:
        if data.get("provider") not in ai.PROVIDERS:
            return f"provider must be one of {', '.join(ai.PROVIDERS)}."
        out["provider"] = data["provider"]
    if "model" in data or not partial:
        model = data.get("model")
        if not isinstance(model, str) or not model.strip() or len(model) > 80:
            return "model is required (≤ 80 characters)."
        out["model"] = model.strip()
    for key in ("input_per_m_usd", "output_per_m_usd"):
        if key in data or not partial:
            value = data.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) \
                    or not 0 <= value <= 1000:
                return f"{key} must be a number 0–1000."
            out[key] = float(value)
    if "note" in data:
        note = data.get("note") or ""
        if not isinstance(note, str) or len(note) > 200:
            return "note must be at most 200 characters."
        out["note"] = note
    return out


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def prices(request):
    ensure_prices()
    if request.method == "GET":
        return Response([price_json(r) for r in ModelPrice.objects.all()])
    fields = _price_fields(request.data, partial=False)
    if isinstance(fields, str):
        return Response({"detail": fields}, status=400)
    if ModelPrice.objects.filter(provider=fields["provider"], model=fields["model"]).exists():
        return Response({"detail": "That model already has a price — edit it instead."},
                        status=400)
    return Response(price_json(ModelPrice.objects.create(**fields)), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAdminUser])
def price_detail(request, pk: int):
    row = ModelPrice.objects.filter(pk=pk).first()
    if row is None:
        return Response({"detail": "Not found."}, status=404)
    in_use = AIConfig.objects.filter(provider=row.provider, model=row.model).exists()
    if request.method == "DELETE":
        if in_use:
            return Response({"detail": "A tier uses this model; point it elsewhere first."},
                            status=409)
        row.delete()
        return Response(status=204)
    fields = _price_fields(request.data, partial=True)
    if isinstance(fields, str):
        return Response({"detail": fields}, status=400)
    if in_use and ({"provider", "model"} & set(fields)) and (
            fields.get("provider", row.provider), fields.get("model", row.model)) != (
            row.provider, row.model):
        return Response({"detail": "A tier uses this model; point it elsewhere first."},
                        status=409)
    for key, value in fields.items():
        setattr(row, key, value)
    row.save()
    return Response(price_json(row))


# --- stats -------------------------------------------------------------------------------

OK = ("ok", "invalid")


def _agg(qs):
    return qs.annotate(
        calls=Count("id", filter=Q(status__in=OK)),
        errors=Count("id", filter=Q(status="error")),
        input_tokens=Sum("input_tokens"), output_tokens=Sum("output_tokens"),
        cost_usd=Sum("estimated_cost_usd"))


def _clean(row: dict) -> dict:
    out = dict(row)
    for key in ("input_tokens", "output_tokens", "calls", "errors"):
        if key in out:
            out[key] = int(out[key] or 0)
    if "cost_usd" in out:
        out["cost_usd"] = round(float(out["cost_usd"] or 0.0), 4)
    if "avg_latency_ms" in out:
        out["avg_latency_ms"] = int(out["avg_latency_ms"]) if out["avg_latency_ms"] else None
    return out


@api_view(["GET"])
@permission_classes([IsAdminUser])
def stats(request):
    key = request.query_params.get("range") or "4w"
    if key not in RANGES:
        return Response({"detail": "range must be one of 7d, 4w, 3m, 6m, 1y."}, status=400)
    today = timezone.now().date()
    start = today - dt.timedelta(days=RANGES[key] - 1)
    base = AIRequestLog.objects.filter(created_at__date__gte=start, created_at__date__lte=today)

    totals = base.aggregate(
        all=Count("id"), ok=Count("id", filter=Q(status__in=OK)),
        errors=Count("id", filter=Q(status="error")),
        refused=Count("id", filter=Q(status="refused")),
        input_tokens=Sum("input_tokens"), output_tokens=Sum("output_tokens"),
        cost_usd=Sum("estimated_cost_usd"),
        avg_latency_ms=Avg("latency_ms", filter=Q(status__in=OK)))
    attempted = (totals["ok"] or 0) + (totals["errors"] or 0)
    body_totals = _clean({
        "calls": totals["ok"], "ok": totals["ok"], "errors": totals["errors"],
        "refused": int(totals["refused"] or 0), "cached": 0,
        "error_rate": round((totals["errors"] or 0) / attempted, 3) if attempted else 0.0,
        "input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"],
        "cost_usd": totals["cost_usd"], "avg_latency_ms": totals["avg_latency_ms"]})

    month0 = today.replace(day=1)
    month = AIRequestLog.objects.filter(created_at__date__gte=month0).aggregate(
        calls=Count("id", filter=Q(status__in=OK)), cost_usd=Sum("estimated_cost_usd"),
        input_tokens=Sum("input_tokens"), output_tokens=Sum("output_tokens"))

    per_day = {r["day"]: r for r in _agg(base.annotate(day=TruncDate("created_at"))
                                         .values("day"))}
    by_day = []
    for i in range(RANGES[key]):
        day = start + dt.timedelta(days=i)
        row = per_day.get(day, {})
        by_day.append(_clean({"date": day, "calls": row.get("calls"), "errors": row.get("errors"),
                              "input_tokens": row.get("input_tokens"),
                              "output_tokens": row.get("output_tokens"),
                              "cost_usd": row.get("cost_usd")}))

    year_start = (month0 - dt.timedelta(days=330)).replace(day=1)
    by_month = [_clean({"month": r["m"].strftime("%Y-%m"), **{k: r[k] for k in (
        "calls", "errors", "input_tokens", "output_tokens", "cost_usd")}})
        for r in _agg(AIRequestLog.objects.filter(created_at__date__gte=year_start)
                      .annotate(m=TruncMonth("created_at")).values("m")).order_by("m")]

    def grouped(*fields, extra=None):
        qs = _agg(base.values(*fields))
        if extra:
            qs = qs.annotate(**extra)
        return [_clean(r) for r in qs.order_by("-cost_usd", "-calls")]

    by_operation = grouped("operation", "tier")
    by_user = []
    names = {}
    from apps.athletes.models import Athlete

    rows = grouped("athlete_id")
    for a in Athlete.objects.filter(pk__in=[r["athlete_id"] for r in rows if r["athlete_id"]]):
        names[a.pk] = a.display_name
    for r in rows:
        by_user.append({**r, "name": names.get(r["athlete_id"], "Admin tests")
                        if r["athlete_id"] else "Admin tests"})
    errors = base.filter(status__in=["error", "invalid"]).order_by("-created_at")[:20]
    return Response({
        "range": key, "start": start, "end": today, "totals": body_totals,
        "month": _clean({"start": month0, **month}),
        "by_day": by_day, "by_month": by_month,
        "by_tier": grouped("tier"), "by_operation": by_operation, "by_user": by_user,
        "by_model": grouped("provider", "model", extra={"avg_latency_ms": Avg(
            "latency_ms", filter=Q(status__in=OK))}),
        "recent_errors": [{"at": e.created_at, "operation": e.operation,
                           "provider": e.provider, "model": e.model, "status": e.status,
                           "error": _safe_text(e.error)[:200]} for e in errors],
    })


def _safe_text(text: str) -> str:
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        secret = getattr(settings, key, "")
        if secret:
            text = (text or "").replace(secret, "***")
    return text or ""
