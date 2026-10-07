"""R15 §B: compare providers — one prompt (or a replayed feature with a real, recent,
aggregate-only context) sent to 2–4 provider/model targets side by side. Staff only;
no budget; every target logged as operation `admin_compare`."""

from __future__ import annotations

import json
import time

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.coaching import client as ai
from apps.coaching.models import AIRequestLog, CompareRun

from .ai import _safe_error

MAX_PROMPT = 4000
OPERATIONS = {"insights_summary": "Insights (last 4 weeks), aggregates only",
              "run_review": "Newest post-run review: comparison rows and bullets only"}


def run_json(run: CompareRun) -> dict:
    user = run.created_by
    return {"id": run.pk, "created_at": run.created_at,
            "created_by": {"id": user.pk, "username": user.username} if user else None,
            "prompt": run.prompt, "operation": run.operation or None,
            "context_note": run.context_note or None, "results": run.results}


def operation_prompt(operation: str, athlete) -> tuple[str, str] | str:
    """(system, user prompt) replaying a feature for this athlete, or an error message.
    Aggregates only — the same payload the feature itself sends; no name, no notes,
    never the private habit."""
    from apps.coaching.prompts import INSIGHTS_USER, SYSTEM

    if operation == "insights_summary":
        from apps.coaching.insights import insights_payload

        payload = {k: v for k, v in insights_payload(athlete, "4w").items() if k != "summary"}
        return SYSTEM, INSIGHTS_USER.format(payload=json.dumps(payload, indent=2, default=str))
    if operation == "run_review":
        from apps.activities.models import RunReview
        from apps.activities.reviews import REVIEW_USER, ai_payload

        review = RunReview.objects.filter(athlete=athlete).order_by("-created_at").first()
        if review is None:
            return "That athlete has no run review to replay yet."
        return SYSTEM, REVIEW_USER.format(payload=json.dumps(ai_payload(review), indent=2,
                                                             default=str))
    return f"operation must be one of {', '.join(OPERATIONS)}."


def call_target(index: int, provider: str, model: str, system: str | None,
                prompt: str) -> dict:
    """One attempt, no retry, no fallback — the point is to see each target as it is."""
    result = {"index": index, "provider": provider, "model": model, "ok": False,
              "status": "error", "error_kind": None, "error": None, "hint": None, "text": "",
              "latency_ms": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
              "rating": None}
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    started = time.monotonic()
    try:
        response = ai.get_client(provider).chat.completions.create(model=model,
                                                                   messages=messages)
        usage = response.usage
        result.update(ok=True, status="ok",
                      text=(response.choices[0].message.content or "").strip()[:8000],
                      input_tokens=usage.prompt_tokens if usage else 0,
                      output_tokens=usage.completion_tokens if usage else 0)
        result["cost_usd"] = ai.estimate_cost(model, result["input_tokens"],
                                              result["output_tokens"], provider)
    except Exception as exc:  # noqa: BLE001 — shown to the admin, never raised
        kind = ai.classify(exc)
        result.update(error=_safe_error(exc), error_kind=kind,
                      hint=ai.hint_for(kind, provider, model))
    result["latency_ms"] = int((time.monotonic() - started) * 1000)
    AIRequestLog.objects.create(
        athlete=None, operation="admin_compare", tier="admin", provider=provider, model=model,
        prompt_version="admin", input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"], latency_ms=result["latency_ms"],
        estimated_cost_usd=result["cost_usd"],
        status=AIRequestLog.Status.OK if result["ok"] else AIRequestLog.Status.ERROR,
        error=(result["error"] or "")[:500], error_kind=result["error_kind"] or "")
    return result


def _targets(raw) -> list[tuple[str, str]] | str:
    if not isinstance(raw, list) or not 2 <= len(raw) <= 4:
        return "targets must be a list of 2–4 {provider, model}."
    out = []
    for item in raw:
        if not isinstance(item, dict):
            return "targets must be a list of 2–4 {provider, model}."
        provider, model = item.get("provider"), item.get("model")
        if provider not in ai.PROVIDERS:
            return f"Unknown provider '{provider}'."
        if not isinstance(model, str) or not model.strip() or len(model) > 80:
            return "Every target needs a model (≤ 80 characters)."
        if not ai.provider_configured(provider):
            return f"{ai.PROVIDERS[provider]['label']} has no API key configured."
        if (provider, model.strip()) in out:
            return "Targets must be different."
        out.append((provider, model.strip()))
    return out


@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def compare(request):
    if request.method == "GET":
        try:
            limit = int(request.query_params.get("limit", 20))
        except ValueError:
            limit = 0
        if not 1 <= limit <= 50:
            return Response({"detail": "limit must be 1–50."}, status=400)
        return Response([run_json(r) for r in
                         CompareRun.objects.select_related("created_by")[:limit]])

    data = request.data if isinstance(request.data, dict) else {}
    targets = _targets(data.get("targets"))
    if isinstance(targets, str):
        return Response({"detail": targets}, status=400)
    prompt = data.get("prompt")
    operation = data.get("operation") or None
    if prompt is not None and (not isinstance(prompt, str) or len(prompt) > MAX_PROMPT):
        return Response({"detail": f"prompt must be 1–{MAX_PROMPT} characters."}, status=400)
    prompt = (prompt or "").strip()
    system, note = None, ""
    if operation is None:
        if not prompt:
            return Response({"detail": f"prompt must be 1–{MAX_PROMPT} characters."},
                            status=400)
        text = prompt
    else:
        if operation not in OPERATIONS:
            return Response({"detail": f"operation must be one of {', '.join(OPERATIONS)}."},
                            status=400)
        from apps.athletes.models import Athlete

        athlete_id = data.get("athlete_id")
        if athlete_id is None:
            athlete = getattr(request.user, "athlete", None)
        elif isinstance(athlete_id, int) and not isinstance(athlete_id, bool):
            athlete = Athlete.objects.filter(pk=athlete_id).first()
        else:
            return Response({"detail": "athlete_id must be a number."}, status=400)
        if athlete is None:
            return Response({"detail": "Athlete not found."}, status=404)
        built = operation_prompt(operation, athlete)
        if isinstance(built, str):
            return Response({"detail": built}, status=400)
        system, text = built
        if prompt:
            text = f"{text}\n\nAdditional instruction: {prompt}"
        note = OPERATIONS[operation]
    results = [call_target(i, provider, model, system, text)
               for i, (provider, model) in enumerate(targets)]
    run = CompareRun.objects.create(created_by=request.user, prompt=text[:20000],
                                    operation=operation or "", context_note=note,
                                    results=results)
    return Response(run_json(run), status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsAdminUser])
def compare_detail(request, pk: int):
    run = CompareRun.objects.filter(pk=pk).select_related("created_by").first()
    if run is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "GET":
        return Response(run_json(run))
    ratings = request.data.get("ratings") if isinstance(request.data, dict) else None
    if not isinstance(ratings, list) or not ratings:
        return Response({"detail": "ratings must be a non-empty list of {index, rating}."},
                        status=400)
    results = [dict(r) for r in run.results]
    for item in ratings:
        if not isinstance(item, dict):
            return Response({"detail": "ratings must be a list of {index, rating}."}, status=400)
        index, rating = item.get("index"), item.get("rating")
        if not isinstance(index, int) or isinstance(index, bool) \
                or not 0 <= index < len(results):
            return Response({"detail": "index is out of range."}, status=400)
        if rating is not None and (not isinstance(rating, int) or isinstance(rating, bool)
                                   or not 1 <= rating <= 5):
            return Response({"detail": "rating must be 1–5 or null."}, status=400)
        results[index]["rating"] = rating
    run.results = results
    run.save(update_fields=["results"])
    return Response(run_json(run))
