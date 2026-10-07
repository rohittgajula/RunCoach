"""The progress review (R8 §C): coach tier, cached per window per day."""

from __future__ import annotations

from apps.coaching.models import AIAnalysis

PROGRESS_USER = """This athlete's last {window} run(s) compared with the runs before, \
calculated in Python. `better` is already direction-aware.

{payload}

Return went_well (1-3 short points), improve (1-3), check (0-2: heat, hydration, sleep, \
kit — prefer the items in `focus`) and a 60-140 word markdown review. Use only numbers \
above; a null metric was not measured — do not guess it. Compare like with like (use \
distance_buckets when overall numbers mix short and long runs)."""

FIELDS = ("went_well", "improve", "check", "markdown")


def _today_rows(athlete):
    tz = athlete.local_now.tzinfo
    today = athlete.local_today
    return [r for r in AIAnalysis.objects.filter(athlete=athlete, kind=AIAnalysis.Kind.PROGRESS)
            if r.created_at.astimezone(tz).date() == today]


def review_state(athlete, window: int) -> dict:
    row = next((r for r in _today_rows(athlete)
                if (r.result or {}).get("window") == window), None)
    if row is None:
        return {"status": "none", "went_well": [], "improve": [], "check": [],
                "markdown": "", "generated_at": None}
    result = row.result or {}
    return {"status": "ready", **{k: result.get(k) or ([] if k != "markdown" else "")
                                  for k in FIELDS}, "generated_at": row.created_at}


def generate_review(athlete, body: dict, refresh: bool = False) -> dict:
    """Raises AIUnavailable (incl. budget)."""
    from apps.coaching.schemas import ProgressReview
    from apps.coaching.services import _run

    from .progress import ai_payload, dumps

    window = body["window"]
    existing = review_state(athlete, window)
    if existing["status"] == "ready" and not refresh:
        return existing
    if refresh:
        for row in _today_rows(athlete):
            if (row.result or {}).get("window") == window:
                row.delete()
    clean = ai_payload(body)
    result, _ = _run(athlete, kind=AIAnalysis.Kind.PROGRESS, operation="progress_review",
                     payload=clean,
                     user_prompt=PROGRESS_USER.format(window=window, payload=dumps(clean)),
                     schema=ProgressReview)
    # Tag the stored row with its window so the per-window cache can find it.
    row = (AIAnalysis.objects.filter(athlete=athlete, kind=AIAnalysis.Kind.PROGRESS)
           .order_by("-created_at").first())
    if row is not None and (row.result or {}).get("window") != window:
        row.result = {**(row.result or {}), "window": window}
        row.save(update_fields=["result"])
    return review_state(athlete, window)
