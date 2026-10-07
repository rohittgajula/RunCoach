"""The coaching service.

The order of operations is the design:

    safety gate  ->  cache  ->  model  ->  validation  ->  store

The gate runs BEFORE the model, not after. A gate that only filters output is one you
have already walked through: by then the model has been asked to justify a harder
session and the answer is on the page.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from apps.athletes.models import Athlete
from apps.activities.models import Activity

from .client import AIUnavailable, canonical_hash, complete, model_for
from .context import athlete_state, recent_runs, run_summary, weekly_rollup
from .models import AIAnalysis, AIRequestLog
from .prompts import (
    GUIDANCE_USER, INSIGHTS_USER, JOURNAL_USER, PROMPT_VERSION, REVIEW_USER, RUN_USER, SYSTEM,
    WEEKLY_USER,
)
from .schemas import (
    Guidance, InsightsSummary, JournalFacts, RunAnalysis, WeeklyReview, WorkoutReview,
)
from .validators import prose_of, validate

logger = logging.getLogger(__name__)

# Per-athlete monthly ceiling. Not a rate limit — a money limit. Every registered
# athlete spends the same prepaid balance, so this is what stops one person's
# enthusiasm emptying it for everyone. See docs/HOSTING.md. AI_MONTHLY_CALL_BUDGET in env.
MONTHLY_CALL_BUDGET = settings.AI_MONTHLY_CALL_BUDGET


class BudgetExceeded(AIUnavailable):
    """This athlete has used their share for the month."""


def _spent_this_month(athlete: Athlete) -> int:
    start = athlete.local_today.replace(day=1)
    return AIRequestLog.objects.filter(
        athlete=athlete, created_at__date__gte=start,
        status__in=[AIRequestLog.Status.OK, AIRequestLog.Status.INVALID],
    ).count()


def check_budget(athlete: Athlete, operation: str, model: str) -> None:
    """Raise BudgetExceeded (and log the refusal) once the monthly ceiling is hit."""
    if _spent_this_month(athlete) >= MONTHLY_CALL_BUDGET:
        AIRequestLog.objects.create(
            athlete=athlete, operation=operation, provider=settings.AI_PROVIDER,
            model=model, prompt_version=PROMPT_VERSION,
            status=AIRequestLog.Status.REFUSED,
            error=f"Monthly budget of {MONTHLY_CALL_BUDGET} calls reached.",
        )
        raise BudgetExceeded(
            f"You have used your {MONTHLY_CALL_BUDGET} coaching requests for this month."
        )


def log_call(
    athlete: Athlete, operation: str, stats: dict | None, error: Exception | None,
    prompt_version: str = PROMPT_VERSION,
) -> None:
    """One AIRequestLog row per model call, failures included — they are billed too."""
    stats = dict(stats or {})
    model = stats.pop("model", "") or ""
    if error is not None:
        AIRequestLog.objects.create(
            athlete=athlete, operation=operation, provider=settings.AI_PROVIDER,
            model=model, prompt_version=prompt_version,
            status=AIRequestLog.Status.ERROR, error=str(error)[:500],
            retry_count=stats.get("retry_count", 0),
        )
        return
    AIRequestLog.objects.create(
        athlete=athlete, operation=operation, provider=settings.AI_PROVIDER,
        model=model, prompt_version=prompt_version, status=AIRequestLog.Status.OK,
        **{k: v for k, v in stats.items() if k in {
            "input_tokens", "output_tokens", "latency_ms", "estimated_cost_usd", "retry_count",
        }},
    )


def _run(
    athlete: Athlete,
    *,
    kind: str,
    operation: str,
    payload: dict,
    user_prompt: str,
    schema,
    activity: Activity | None = None,
):
    """One cached, logged, validated call."""
    model = model_for(operation)
    digest = canonical_hash(payload, PROMPT_VERSION, model)

    cached = AIAnalysis.objects.filter(
        athlete=athlete, kind=kind, input_hash=digest
    ).first()
    if cached:
        # Deliberately not logged as a request: it cost nothing, and counting it
        # would make the cost log lie in the direction of looking worse.
        return schema.model_validate(cached.result), True

    if _spent_this_month(athlete) >= MONTHLY_CALL_BUDGET:
        AIRequestLog.objects.create(
            athlete=athlete, operation=operation, provider=settings.AI_PROVIDER,
            model=model, prompt_version=PROMPT_VERSION,
            status=AIRequestLog.Status.REFUSED,
            error=f"Monthly budget of {MONTHLY_CALL_BUDGET} calls reached.",
        )
        raise BudgetExceeded(
            f"You have used your {MONTHLY_CALL_BUDGET} coaching requests for this month."
        )

    try:
        result, stats = complete(
            operation=operation, system=SYSTEM, user=user_prompt, schema=schema
        )
    except Exception as exc:
        AIRequestLog.objects.create(
            athlete=athlete, operation=operation, provider=settings.AI_PROVIDER,
            model=model, prompt_version=PROMPT_VERSION,
            status=AIRequestLog.Status.ERROR, error=str(exc)[:500],
        )
        raise

    # Validate before storing. Structured Outputs guarantees the shape; nothing
    # guarantees the content, and an invented figure is the one failure that breaks
    # the whole promise of this system.
    flags = payload.get("state", payload).get("reported_by_athlete", {}) if isinstance(payload, dict) else {}
    checked = validate(
        prose_of(result),
        payload,
        flags_set=bool(flags.get("pain") or flags.get("illness")),
    )
    if not checked.ok:
        logger.warning(
            "ai %s produced %d finding(s): %s",
            operation, len(checked.findings),
            "; ".join(f.detail for f in checked.findings),
        )

    AIRequestLog.objects.create(
        athlete=athlete, operation=operation, provider=settings.AI_PROVIDER,
        prompt_version=PROMPT_VERSION,
        # A response with findings is still logged as OK: it was billed and it was
        # returned. INVALID is reserved for one that could not be parsed at all.
        status=AIRequestLog.Status.OK,
        error="; ".join(f.detail for f in checked.findings)[:500],
        **stats,
    )
    AIAnalysis.objects.update_or_create(
        athlete=athlete, kind=kind, input_hash=digest,
        defaults={
            "activity": activity,
            "prompt_version": PROMPT_VERSION,
            "model": stats["model"],
            # mode="json" so dates and enums become primitives. A plain
            # model_dump() puts date objects in a JSONField and the write dies
            # AFTER the paid call has already been made.
            "result": result.model_dump(mode="json"),
            "findings": checked.as_list(),
        },
    )
    return result, False


def guidance_for(athlete: Athlete) -> tuple[Guidance, bool]:
    """Where the athlete stands, and what to do about it."""
    state = athlete_state(athlete)
    return _run(
        athlete,
        kind=AIAnalysis.Kind.GUIDANCE,
        operation="guidance",
        payload=state,
        user_prompt=GUIDANCE_USER.format(state=json.dumps(state, indent=2, default=str)),
        schema=Guidance,
    )


def analyse_run(athlete: Athlete, activity: Activity) -> tuple[RunAnalysis, bool]:
    run = run_summary(activity)
    recent = recent_runs(athlete, limit=8)
    payload = {"run": run, "recent": recent}
    return _run(
        athlete,
        kind=AIAnalysis.Kind.RUN,
        operation="run_analysis",
        payload=payload,
        user_prompt=RUN_USER.format(
            run=json.dumps(run, indent=2, default=str),
            recent=json.dumps(recent, indent=2, default=str),
        ),
        schema=RunAnalysis,
        activity=activity,
    )


def weekly_review(athlete: Athlete) -> tuple[WeeklyReview, bool]:
    weeks = weekly_rollup(athlete)
    state = athlete_state(athlete)
    payload = {"weeks": weeks, "state": state}
    return _run(
        athlete,
        kind=AIAnalysis.Kind.WEEKLY,
        operation="weekly_review",
        payload=payload,
        user_prompt=WEEKLY_USER.format(
            weeks=json.dumps(weeks, indent=2, default=str),
            state=json.dumps(state, indent=2, default=str),
        ),
        schema=WeeklyReview,
    )


def extract_journal(athlete: Athlete, text: str, written_on) -> tuple[JournalFacts, bool]:
    payload = {"text": text, "written_on": str(written_on)}
    return _run(
        athlete,
        kind=AIAnalysis.Kind.JOURNAL,
        operation="journal_extract",
        payload=payload,
        user_prompt=JOURNAL_USER.format(text=text, written_on=written_on),
        schema=JournalFacts,
    )


def review_activity(athlete: Athlete, activity: Activity, workout=None) -> tuple[WorkoutReview, bool]:
    """R6 §3. Cached by input hash: the same session, plan and notes never pay twice."""
    from apps.journal.models import JournalEntry
    from apps.planning.actuals import actual_json, compliance_json

    actual = actual_json(activity)
    actual.pop("steps", None)            # the segments are summarised above; noise here
    notes = [
        {"date": str(e.applies_to_date), "said": (e.extracted or {}).get("notes_summary")
         or e.text[:300], "rpe": e.rpe}
        for e in JournalEntry.objects.filter(athlete=athlete).filter(
            models_q_activity_or_day(activity)).order_by("-created_at")[:4]
    ]
    payload = {
        "sport": activity.sport,
        "date": str(activity.local_date),
        "planned": {
            "title": workout.title, "kind": workout.kind,
            "duration_min": round(workout.duration_s / 60),
            "target_zone": workout.target_zone, "purpose": workout.purpose,
        } if workout else None,
        "actual": actual,
        "compliance": compliance_json(workout, activity) if workout else None,
        "hr_ceiling_bpm": athlete.hr_ceiling,
        "athlete_notes": notes,
    }
    return _run(
        athlete, kind=AIAnalysis.Kind.REVIEW, operation="workout_review", payload=payload,
        user_prompt=REVIEW_USER.format(payload=json.dumps(payload, indent=2, default=str)),
        schema=WorkoutReview, activity=activity,
    )


def models_q_activity_or_day(activity: Activity):
    from django.db.models import Q

    return Q(activity=activity) | Q(applies_to_date=activity.local_date)


def insights_overview(athlete: Athlete, payload: dict) -> tuple[InsightsSummary, bool]:
    """R6 §5. `payload` includes today's date, so the cache is per day (and range)."""
    clean = {k: v for k, v in payload.items() if k != "summary"}
    return _run(
        athlete, kind=AIAnalysis.Kind.INSIGHTS, operation="insights_summary",
        payload=clean,
        user_prompt=INSIGHTS_USER.format(payload=json.dumps(clean, indent=2, default=str)),
        schema=InsightsSummary,
    )


def checkin_explain_payload(today_payload: dict) -> dict:
    """What the explanation is written from — and its cache key (it contains the date)."""
    return {
        "date": str(today_payload["date"]),
        "verdict": today_payload["verdict"],
        "headline": today_payload["headline"],
        # R13: a pain report's body location never goes to the model (no diagnosis).
        "signals": [{"signal": r["signal"], "status": r["status"],
                     "label": "Pain reported" if r["signal"] == "pain" else r["label"]}
                    for r in today_payload["reasons"]],
        "signals_missing": today_payload["signals_missing"],
        # As planned, so applying the change does not invalidate the explanation.
        "planned": ((today_payload["workout"] or {}).get("original") or {}).get("title")
        or (today_payload["workout"] or {}).get("title"),
        "changed_to": (today_payload["adjusted"] or {}).get("title"),
    }


def cached_checkin_explanation(athlete: Athlete, payload: dict) -> str | None:
    """Today's stored explanation for exactly these inputs, without a model call."""
    from .prompts import PROMPT_VERSION as version

    try:
        model = model_for("checkin_explain")
    except AIUnavailable:
        return None
    digest = canonical_hash(payload, version, model)
    row = AIAnalysis.objects.filter(athlete=athlete, kind=AIAnalysis.Kind.CHECKIN,
                                    input_hash=digest).first()
    return (row.result or {}).get("text") if row else None


def checkin_explanation(athlete: Athlete, payload: dict) -> str:
    """R7 §1, lite tier. Cached per day by input hash; budget-checked in _run."""
    from .prompts import CHECKIN_USER
    from .schemas import CheckinExplanation

    result, _cached = _run(
        athlete, kind=AIAnalysis.Kind.CHECKIN, operation="checkin_explain", payload=payload,
        user_prompt=CHECKIN_USER.format(payload=json.dumps(payload, indent=2, default=str)),
        schema=CheckinExplanation,
    )
    return result.text
