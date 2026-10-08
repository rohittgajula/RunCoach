"""R18: profile parameters — memory facts are the live source of truth.

For every key the effective value is, in order:
  newest active fact parameter (pinned facts win ties)  vs  the explicit app setting
  — whichever changed more recently wins (a setting with no recorded change counts as
  oldest) — then Garmin (sleep need), then the default.

`sleep_need_minutes`, `usual_run_time`, `loop_distance_km` are resolved at read time (the
athlete columns hold the explicit setting). `available_days`, `long_run_day`,
`runs_per_week` shape the plan, so when their effective value changes it is written to
the columns through the same path as PATCH /athlete/ (reflow / relayout); the explicit
setting is kept in `Athlete.profile_settings`.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from analysis import fact_params as parser

logger = logging.getLogger(__name__)

KEYS = ("sleep_need_minutes", "usual_run_time", "loop_distance_km", "available_days",
        "long_run_day", "runs_per_week")
READ_KEYS = ("sleep_need_minutes", "usual_run_time", "loop_distance_km")
PLAN_KEYS = ("available_days", "long_run_day", "runs_per_week")
SETTING_KEYS = KEYS + ("injury_note",)


# --- explicit settings ------------------------------------------------------------------

def _column(athlete, key):
    value = getattr(athlete, key)
    if key == "usual_run_time" and value is not None:
        return value.strftime("%H:%M")
    return value


def _to_column(key, value):
    if key == "usual_run_time" and value is not None:
        return dt.time.fromisoformat(str(value))
    if key == "loop_distance_km" and value is not None:
        return float(value)
    if key in ("sleep_need_minutes", "long_run_day", "runs_per_week") and value is not None:
        return int(value)
    return value


def setting(athlete, key) -> tuple[object, dt.datetime | None]:
    """(explicit value, when it last changed | None)."""
    record = (athlete.profile_settings or {}).get(key) or {}
    at = record.get("at")
    at = dt.datetime.fromisoformat(at) if at else None
    if key in PLAN_KEYS and "value" in record:
        return record["value"], at
    return _column(athlete, key), at


def record_setting_change(athlete, key, value, *, save: bool = True) -> None:
    """The athlete set `key` explicitly (Settings or update_profile), now."""
    settings = dict(athlete.profile_settings or {})
    settings[key] = {"value": value, "at": timezone.now().isoformat()}
    athlete.profile_settings = settings
    if save:
        athlete.save(update_fields=["profile_settings", "updated_at"])


def _snapshot_plan_setting(athlete, key) -> None:
    """Before memory first overwrites a plan column, keep the explicit value."""
    settings = dict(athlete.profile_settings or {})
    if key not in settings:
        settings[key] = {"value": _column(athlete, key), "at": None}
        athlete.profile_settings = settings


# --- memory -------------------------------------------------------------------------------

def _active_params(athlete, key):
    from apps.coaching.models import FactParameter

    return (FactParameter.objects.filter(athlete=athlete, key=key,
                                         status=FactParameter.Status.ACTIVE)
            .select_related("fact").order_by("-effective_at", "-fact__pinned", "-id"))


def memory_candidate(athlete, key):
    ensure_parsed(athlete)
    return _active_params(athlete, key).first()


def _garmin(athlete, key):
    if key == "sleep_need_minutes":
        from .effective import garmin_sleep_need_s

        seconds = garmin_sleep_need_s(athlete)
        return round(seconds / 60) if seconds else None
    return None


DEFAULTS = {"sleep_need_minutes": 480}


def resolve(athlete, key) -> dict:
    """Effective = {key, label, value, display, source, fact_id, fact_text, updated_at,
    setting_value, garmin_value, parameter_id}."""
    param = memory_candidate(athlete, key)
    value, at = setting(athlete, key)
    garmin = _garmin(athlete, key)
    out = {"key": key, "label": parser.LABELS[key], "fact_id": None, "fact_text": None,
           "parameter_id": None, "setting_value": value, "garmin_value": garmin}
    use_memory = param is not None and (value is None or at is None or param.effective_at >= at)
    if use_memory:
        out.update(value=param.value, source="memory", fact_id=param.fact_id,
                   fact_text=param.fact.text, updated_at=param.effective_at,
                   parameter_id=param.pk)
    elif value is not None:
        out.update(value=value, source="setting", updated_at=at)
    elif garmin is not None:
        out.update(value=garmin, source="garmin", updated_at=None)
    else:
        out.update(value=DEFAULTS.get(key), source="default", updated_at=None)
    out["display"] = parser.display(key, out["value"])
    return out


def effective_value(athlete, key):
    return resolve(athlete, key)["value"]


def all_effective(athlete) -> list[dict]:
    return [resolve(athlete, key) for key in KEYS]


# --- parsing facts --------------------------------------------------------------------------

def reparse(fact, *, sync: bool = True) -> list:
    """Parse the fact's text into parameters (replacing the old ones). Queues the AI
    fallback when the parser finds nothing and the text looks parameter-like."""
    from apps.coaching.models import FactParameter

    athlete = fact.athlete
    text = fact.text or ""
    _explicit_days, _ = setting(athlete, "available_days")
    found = parser.parse(text, current_days=_explicit_days)
    now = timezone.now()
    with transaction.atomic():
        FactParameter.objects.filter(fact=fact).delete()
        rows = [FactParameter.objects.create(
            athlete=athlete, fact=fact, key=p.key, value=p.value, unit=p.unit,
            confidence=p.confidence, source="parser", needs_review=p.needs_review,
            status=(FactParameter.Status.REVIEW if p.needs_review
                    else FactParameter.Status.ACTIVE),
            effective_at=now) for p in found]
        pending = not found and parser.looks_parameter_like(text)
        type(fact).objects.filter(pk=fact.pk).update(params_text=text, parse_pending=pending)
        fact.params_text, fact.parse_pending = text, pending
    if pending:
        _queue_ai(fact)
    if sync:
        sync_plan_fields(athlete)
    return rows


def _queue_ai(fact) -> None:
    try:
        from apps.coaching.tasks import parse_fact_params_ai

        parse_fact_params_ai.delay(fact.pk, fact.text)    # re-checks the text when it runs
    except Exception:  # noqa: BLE001 — no broker: the parser result stands
        logger.debug("could not queue the AI fact parse for %s", fact.pk)


def store_ai_params(fact, text: str, items: list[dict]) -> list:
    """AI fallback result (only if the fact still has that text)."""
    from apps.coaching.models import FactParameter

    fact.refresh_from_db()
    if fact.text != text:
        return []
    now = timezone.now()
    rows = []
    for item in items:
        key, value = item.get("key"), item.get("value")
        if key not in KEYS:
            continue
        if key == "available_days" and isinstance(value, list):
            value = {str(d): d in value for d in range(7)}
        try:
            value = _normalise(key, value)
        except (TypeError, ValueError):
            continue
        if not parser.valid(key, value):
            continue
        confidence = float(item.get("confidence") or 0)
        review = confidence < parser.REVIEW_BELOW
        rows.append(FactParameter.objects.create(
            athlete=fact.athlete, fact=fact, key=key, value=value, unit=parser.UNITS[key],
            confidence=round(confidence, 2), source="ai", needs_review=review,
            status=FactParameter.Status.REVIEW if review else FactParameter.Status.ACTIVE,
            effective_at=now))
    type(fact).objects.filter(pk=fact.pk).update(parse_pending=False)
    sync_plan_fields(fact.athlete)
    return rows


def _normalise(key, value):
    if key in ("sleep_need_minutes", "long_run_day", "runs_per_week"):
        return int(round(float(value)))
    if key == "loop_distance_km":
        return round(float(value), 2)
    if key == "usual_run_time":
        t = dt.time.fromisoformat(str(value)[:5])
        return f"{t.hour:02d}:{t.minute:02d}"
    return value


def ensure_parsed(athlete) -> None:
    """Facts never parsed (before R18) or changed by a path that skipped the signal."""
    from apps.coaching.models import MemoryFact

    stale = list(MemoryFact.objects.filter(athlete=athlete).exclude(params_text=F("text")))
    for fact in stale:
        fact.athlete = athlete
        reparse(fact, sync=False)
    if stale:
        sync_plan_fields(athlete)


# --- plan-shaping keys -----------------------------------------------------------------------

def _conflict(athlete, key, value, pending: dict) -> str | None:
    days = pending.get("available_days", athlete.available_days) or {}
    if key == "available_days":
        if not any((value or {}).values()):
            return "No run day left."
        long_day = pending.get("long_run_day", athlete.long_run_day)
        if not value.get(str(long_day)):
            return (f"Your long-run day ({parser.DAY_NAMES[long_day]}) isn't one of these "
                    "days.")
    if key == "long_run_day" and not days.get(str(value)):
        return f"{parser.DAY_NAMES[int(value)]} isn't one of your run days."
    return None


def sync_plan_fields(athlete, *, force_param_ids: tuple = ()) -> dict | None:
    """Write effective plan-shaping values to the athlete (with reflow / relayout).
    A memory value that conflicts is parked as needs_review (not applied) unless it is in
    `force_param_ids` (the athlete confirmed it) — then the long-run day moves to the
    latest available day."""
    from apps.coaching.models import FactParameter

    athlete.refresh_from_db()
    changes: dict = {}
    for key in PLAN_KEYS:
        eff = resolve(athlete, key)
        value = eff["value"]
        if value is None or value == _column(athlete, key):
            continue
        if eff["source"] == "memory":
            conflict = _conflict(athlete, key, value, changes)
            if conflict and eff["parameter_id"] not in force_param_ids:
                FactParameter.objects.filter(pk=eff["parameter_id"]).update(
                    status=FactParameter.Status.REVIEW, needs_review=True, conflict=conflict)
                continue
            if conflict and key == "available_days":
                chosen = [int(k) for k, v in value.items() if v]
                changes["long_run_day"] = max(chosen)
            _snapshot_plan_setting(athlete, key)
        changes[key] = value
    if not changes:
        return None
    for key in changes:
        if key != "long_run_day":
            _snapshot_plan_setting(athlete, key)
    _snapshot_plan_setting(athlete, "long_run_day")
    return apply_plan_changes(athlete, changes)


def apply_plan_changes(athlete, changes: dict) -> dict | None:
    """Save plan-shaping fields and re-flow the active plan (as PATCH /athlete/ does)."""
    from apps.planning.reflow import reflow_active_plan
    from apps.planning.relayout import relayout_active_plan

    days_before = (athlete.available_days, athlete.long_run_day)
    runs_before = athlete.runs_per_week
    with transaction.atomic():
        for key, value in changes.items():
            setattr(athlete, key, _to_column(key, value))
        athlete.save()
        days_changed = (athlete.available_days, athlete.long_run_day) != days_before
        runs_changed = athlete.runs_per_week != runs_before
        reflowed = reflow_active_plan(athlete) if days_changed else None
        relaid = None
        if runs_changed or (days_changed and athlete.runs_per_week):
            relaid = relayout_active_plan(athlete)
    if (days_changed or runs_changed) and athlete.strength_per_week:
        try:
            from apps.planning.strength_service import place_for

            place_for(athlete)
        except Exception:  # noqa: BLE001
            logger.exception("strength placement after a profile change failed")
    return {"changes": changes, "reflow": reflowed, "relayout": relaid}


# --- JSON -----------------------------------------------------------------------------------

def parameter_json(param, applied_ids: set | None = None) -> dict:
    return {"id": param.pk, "key": param.key, "label": parser.LABELS.get(param.key, param.key),
            "value": param.value, "value_display": parser.display(param.key, param.value),
            "unit": param.unit, "confidence": param.confidence, "source": param.source,
            "needs_review": param.needs_review, "status": param.status,
            "conflict": param.conflict or None,
            "applied": bool(applied_ids and param.pk in applied_ids)}


def applied_parameter_ids(athlete) -> set:
    return {e["parameter_id"] for e in all_effective(athlete) if e["parameter_id"]}


def effective_json(athlete) -> dict:
    from .versioning import current

    return {"parameters": all_effective(athlete), "data_version": current(athlete.pk)}


# --- explicit changes (chat update_profile) ----------------------------------------------------

def normalise_setting(field: str, value):
    """The chat tool's loose value → the API format. Raises ValueError."""
    import re

    if field == "injury_note":
        return " ".join(str(value or "").split())[:200]
    if value in (None, "", "null") and field in ("sleep_need_minutes", "usual_run_time",
                                                 "loop_distance_km", "runs_per_week"):
        return None
    if field == "sleep_need_minutes":
        number = float(value)
        return int(round(number * 60 if number <= 12 else number))
    if field == "usual_run_time":
        m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*", str(value), re.IGNORECASE)
        if not m:
            raise ValueError("usual_run_time must look like 06:30.")
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if (m.group(3) or "").lower() == "pm" and hour < 12:
            hour += 12
        if (m.group(3) or "").lower() == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    if field == "loop_distance_km":
        return round(float(value), 2)
    if field in ("runs_per_week",):
        return int(value)
    if field == "long_run_day":
        if isinstance(value, str) and not value.strip().isdigit():
            return [d.lower() for d in parser.DAY_NAMES].index(value.strip().lower())
        return int(value)
    if field == "available_days":
        if isinstance(value, list):
            return {str(d): d in [int(x) for x in value] for d in range(7)}
        if isinstance(value, dict):
            return {str(d): bool(value.get(str(d))) for d in range(7)}
        raise ValueError("available_days must be a list of weekdays (0 = Monday).")
    raise ValueError(f"Unknown setting {field}.")


def validate_setting(athlete, field: str, value) -> None:
    """Field rules of PATCH /athlete/. Raises ValueError with a readable message."""
    from rest_framework.exceptions import ValidationError

    from .serializers import AthleteSerializer

    if field == "long_run_day":
        if not 0 <= int(value) <= 6:
            raise ValueError("long_run_day must be 0 (Monday) to 6 (Sunday).")
        if not (athlete.available_days or {}).get(str(value)):
            raise ValueError(f"{parser.DAY_NAMES[int(value)]} isn't one of your run days "
                             "\u2014 add it to your run days first.")
        return
    serializer = AthleteSerializer(athlete)
    try:
        checked = serializer.fields[field].run_validation(value)
        method = getattr(serializer, f"validate_{field}", None)
        if method:
            method(checked)
    except ValidationError as exc:
        detail = exc.detail
        while isinstance(detail, (list, dict)) and detail:
            detail = detail[0] if isinstance(detail, list) else next(iter(detail.values()))
        raise ValueError(str(detail)) from exc


def setting_display(athlete, field: str, value=None, *, current: bool = False) -> str:
    if field == "injury_note":
        text = athlete.injury_note if current else value
        return f"“{text}”" if text else "none"
    if current:
        return resolve(athlete, field)["display"]
    if value is None and field == "sleep_need_minutes":
        return "Garmin's"
    return parser.display(field, value)


def apply_setting(athlete, field: str, value) -> dict:
    """An explicit change (now → newer than any memory fact, so it takes effect)."""
    before = setting_display(athlete, field, current=True)
    if field in PLAN_KEYS:
        record_setting_change(athlete, field, value, save=False)
        changes = {field: value}
        if field == "available_days" and not value.get(str(athlete.long_run_day)):
            changes["long_run_day"] = max(int(k) for k, v in value.items() if v)
            record_setting_change(athlete, "long_run_day", changes["long_run_day"], save=False)
        apply_plan_changes(athlete, changes)
    else:
        setattr(athlete, field, _to_column(field, value))
        if field in KEYS:
            record_setting_change(athlete, field, value, save=False)
        athlete.save()
    athlete.refresh_from_db()
    return {"before": before, "after": setting_display(athlete, field, current=True)}
