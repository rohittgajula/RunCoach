"""Chat turns: context in, tool loop, a stored assistant message out.

The order of operations matters. The user message is stored first, then an assistant
message in `pending`, then the model runs. Whatever happens — budget exhausted, API
down, a tool blowing up — the assistant row ends as `done` or `error` with readable
text, and the endpoint returns 200. A chat that 500s loses what the athlete typed.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from django.db import transaction

from analysis.memory_facts import context_facts
from apps.athletes.models import Athlete

from .client import AIUnavailable, chat_with_tools
from .models import ChatMessage, ChatThread, MemoryFact
from .services import BudgetExceeded, check_budget, log_call
from .tools import TOOLS, ToolRunner, training_summary, upcoming_races

logger = logging.getLogger(__name__)

OPERATION = "chat"
PROMPT_VERSION = "chat-v1"
HISTORY_MESSAGES = 20
MAX_TOOL_ITERATIONS = 6

ERROR_TEXT = (
    "Sorry — I couldn't reach the coaching model just now, so I haven't changed "
    "anything. Your message is saved; try again in a minute."
)
BUDGET_TEXT = (
    "You've used this month's coaching requests, so I can't answer right now. Your plan, "
    "calendar and diet targets all keep working — they don't need me."
)

PERSONA = """You are RunCoach, an evidence-based running coach for a recreational \
runner. You talk like a calm, practical coach: short paragraphs, plain words, markdown \
where it helps.

Rules:
- Python calculates; you interpret. Never invent paces, loads, calorie targets or plan \
volumes. Get numbers from the context below or by calling a tool.
- To build a plan, first work out whether there is a race at all. If the athlete has a \
saved race in `races` below and is training for it, call propose_plan with its race_id. \
If they say they are not racing, are training for themselves, want to practise, or \
simply have no saved race, call propose_practice_plan — it builds toward the next \
unbroken block (5, 10, 15, 20, 30, 45, 60 minutes) instead of a date. Do NOT ask for a \
race date from somebody who has not mentioned a race, and never invent one: a plan \
counting down to a race nobody entered is worse than no plan. Ask only what you cannot \
derive: how many days a week, injuries. Either plan is a PROPOSAL until the athlete \
accepts it — say so.
- You may make the week easier (skip, move, clear a day). Add load only when the athlete \
asks for it, and never after reported pain or illness.
- To change a session or a week the athlete asked about, call edit_workout or edit_week \
(find ids in the context or with get_workouts). Up to +20 % more running per session \
applies directly. If a tool returns needs_confirmation, NOTHING was saved: tell the athlete \
exactly what would change and ask; call again with confirmed=true only after they agree.
- The athlete is in charge. When they explicitly ask to change their plan, a workout or \
a setting, CALL THE TOOL (edit_workout, edit_week, move_workout, update_profile …) — never \
refuse outright. If it returns warnings or needs_confirmation, explain the risk in a \
sentence or two and ask "Do it anyway?" (Yes/No). Increases follow the same rule: up to \
+20 % applies directly, more needs their yes.
- Settings (sleep need, usual run time, loop distance, run days, runs per week, long-run \
day, injury note): change them only with update_profile, which always asks the athlete to \
confirm first. Memory facts like "I need 7 h of sleep" already set the athlete's values \
(see `athlete.settings`, with their source).
- Honesty rule: never say a workout or the plan was changed, moved, updated or sent to the \
watch unless a tool call in THIS turn succeeded (status "updated", or move/skip/clear without \
an error). If a tool returned an error or needs_confirmation, say plainly it was not changed. \
After a change, state exactly what changed: the date and before → after, e.g. \
"Sat 12 Oct: 40 → 45 min".
- Do not diagnose. Persistent pain is a reason to see a professional.
- "Distance" means distance run, not what the watch logged.
- Meal numbers from log_meal are estimates; say so."""


def _fmt_pace(seconds) -> str | None:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}/km" if seconds else None


def system_prompt(athlete: Athlete) -> str:
    from apps.athletes.profile_params import all_effective
    from apps.diet.services import diet_day

    from .context import history_summary
    from apps.planning.models import PlannedWorkout, TrainingPlan
    from apps.planning.plan_store import current_phase

    today = athlete.local_today
    weeks = training_summary(athlete, 6)
    plan = TrainingPlan.objects.filter(athlete=athlete, status=TrainingPlan.Status.ACTIVE).first()
    phase = current_phase(plan, today) if plan else None
    upcoming = PlannedWorkout.objects.filter(
        athlete=athlete, date__in=[today, today + dt.timedelta(days=1)],
        plan__status=TrainingPlan.Status.ACTIVE,
    )
    diet = diet_day(athlete, today)
    context = {
        "today": today,
        "weekday": today.strftime("%A"),
        "athlete": {
            "name": athlete.display_name, "age": athlete.age, "sex": athlete.sex,
            "weight_kg": athlete.weight_kg, "height_cm": athlete.height_cm,
            "easy_pace": f"{_fmt_pace(athlete.easy_pace_min)}–{_fmt_pace(athlete.easy_pace_max)}",
            "threshold_pace": _fmt_pace(athlete.threshold_pace_s),
            "available_days": [d for d in range(7) if athlete.is_available(d)],
            "long_run_day": athlete.long_run_day,
            "diet_goal": athlete.diet_goal,
            # R18: effective settings (memory fact / app setting / Garmin / default).
            "settings": {e["key"]: {"value": e["display"], "source": e["source"]}
                         for e in all_effective(athlete)},
            "injury_note": athlete.injury_note or None,
        },
        "races": upcoming_races(athlete),
        # R17 §16: pinned facts always, then the newest others (≤ 40 in all).
        "memory": context_facts(list(MemoryFact.objects.filter(athlete=athlete)
                                     .order_by("-created_at", "-id")
                                     .values_list("text", "pinned"))),
        "last_6_weeks": weeks,
        "history_summary": history_summary(athlete),
        "active_plan": {
            "id": plan.pk, "name": plan.name, "goal": plan.goal,
            "current_phase": {"name": phase.name, "kind": phase.kind,
                              "start": phase.start, "end": phase.end} if phase else None,
        } if plan else None,
        "today_and_tomorrow": [
            {"id": w.pk, "date": w.date, "title": w.title, "kind": w.kind,
             "minutes": round(w.duration_s / 60), "status": w.status}
            for w in upcoming
        ],
        # R16: ids the edit tools need, without a get_workouts round trip.
        "next_7_days": [
            {"id": w.pk, "date": w.date, "title": w.title, "kind": w.kind,
             "minutes": round(w.duration_s / 60), "status": w.status,
             "edited_by_athlete": w.edited_by == "user"}
            for w in PlannedWorkout.objects.filter(
                athlete=athlete, date__gte=today, date__lte=today + dt.timedelta(days=6),
                plan__status=TrainingPlan.Status.ACTIVE).order_by("date", "id")[:14]
        ],
        "diet_today": {"targets": diet["targets"], "eaten": diet["eaten"]},
    }
    # R17 §10: illness mode — type, dates and counts only.
    from apps.health.illness import active as illness_active

    ill = illness_active(athlete)
    if ill is not None:
        context["illness"] = {"type": ill.type, "since": ill.start_date,
                              "paused_sessions": ill.paused_count,
                              "note": "Plan paused. Rest messaging only; use recover_illness "
                                      "when they say they're better."}
    from apps.habits.services import chat_context

    habits = chat_context(athlete)
    if habits:
        context["habits"] = habits

    # Whether any of the above is still true.
    #
    # The coach spent five weeks answering questions about Rohit's training with
    # complete confidence while his watch had been disconnected since 10 October.
    # Every figure it was given was real; none of it was current, and it had no
    # way to know. A model cannot caveat what it has not been told.
    from apps.health.freshness import sync_json

    sync = sync_json(athlete, athlete.local_today, athlete.local_now)
    if sync["level"] != "ok":
        context["data_is_stale"] = {
            **{k: sync[k] for k in
               ("level", "connected", "days_since_activity", "last_activity_date")},
            "note": "Say so before answering anything that depends on recent "
                    "training. Do not present these figures as current, and do "
                    "not guess at what has happened since.",
        }
    return f"{PERSONA}\n\nContext (already calculated):\n{json.dumps(context, default=str)}"


def _attachment_context(athlete: Athlete, attachments: list[dict]) -> str:
    """What the athlete attached, as data the model can read."""
    if not attachments:
        return ""
    from .tools import ToolRunner

    runner = ToolRunner(athlete)
    parts = []
    for ref in attachments:
        try:
            if ref["type"] == "workout":
                parts.append({"attached_workout": runner.t_get_workout(ref["id"])})
            elif ref["type"] == "activity":
                parts.append({"attached_activity": runner.t_get_activity(ref["id"])})
        except Exception:  # noqa: BLE001 — a vanished attachment is not a failed turn
            continue
    return "\n\nAttached:\n" + json.dumps(parts, default=str) if parts else ""


def clean_attachments(athlete: Athlete, raw) -> list[dict]:
    """Keep only well-formed references to the athlete's OWN objects."""
    from apps.activities.models import Activity
    from apps.diet.models import Meal
    from apps.planning.models import PlannedWorkout, TrainingPlan

    models = {"workout": PlannedWorkout, "activity": Activity,
              "plan_proposal": TrainingPlan, "meal": Meal}
    cleaned = []
    for ref in raw or []:
        if not isinstance(ref, dict) or ref.get("type") not in models:
            continue
        try:
            pk = int(ref.get("id"))
        except (TypeError, ValueError):
            continue
        if models[ref["type"]].objects.filter(athlete=athlete, pk=pk).exists():
            cleaned.append({"type": ref["type"], "id": pk})
    return cleaned


def run_turn(thread: ChatThread, content: str, attachments: list[dict]):
    """Store the user message, run the model, store the reply. Returns (user, assistant)."""
    athlete = thread.athlete
    user = ChatMessage.objects.create(
        thread=thread, role=ChatMessage.Role.USER, content=content, attachments=attachments,
    )
    assistant = ChatMessage.objects.create(
        thread=thread, role=ChatMessage.Role.ASSISTANT, status=ChatMessage.Status.PENDING,
    )
    if not thread.title:
        thread.title = content.strip().splitlines()[0][:60] if content.strip() else "New chat"
    thread.save()

    history = list(
        thread.messages.filter(status=ChatMessage.Status.DONE)
        .exclude(pk__in=[user.pk, assistant.pk])
        .exclude(role=ChatMessage.Role.TOOL)
        .order_by("-created_at", "-id")[:HISTORY_MESSAGES]
    )[::-1]
    messages = [{"role": "system", "content": system_prompt(athlete)}]
    messages += [{"role": m.role, "content": m.content} for m in history if m.content]
    messages.append({
        "role": "user",
        "content": content + _attachment_context(athlete, attachments),
    })

    runner = ToolRunner(athlete, chat_message=assistant)

    def call(conversation):
        return chat_with_tools(
            operation=OPERATION, messages=conversation, tools=TOOLS, dispatch=runner,
            max_iterations=MAX_TOOL_ITERATIONS,
            before_call=lambda model: check_budget(athlete, OPERATION, model),
            on_call=lambda stats, error: log_call(athlete, OPERATION, stats, error, PROMPT_VERSION),
        )

    try:
        text, audit = call(messages)
        text, audit, refusal = refusal_guard(athlete, messages, content, text, audit, call)
        text, audit, assistant.guard = honesty_guard(athlete, messages, text, audit, call)
        if refusal:
            assistant.guard = {**(assistant.guard or {}), "refusal": refusal}
        assistant.content = text or "Done."
        assistant.status = ChatMessage.Status.DONE
        assistant.tool_calls = json.loads(json.dumps(audit, default=str))
    except BudgetExceeded:
        assistant.content, assistant.status = BUDGET_TEXT, ChatMessage.Status.ERROR
    except AIUnavailable as exc:
        logger.warning("chat unavailable for athlete %s: %s", athlete.pk, exc)
        assistant.content, assistant.status = ERROR_TEXT, ChatMessage.Status.ERROR
    except Exception:  # noqa: BLE001 — never a 500; the error is logged with a trace
        logger.exception("chat turn failed for athlete %s", athlete.pk)
        assistant.content, assistant.status = ERROR_TEXT, ChatMessage.Status.ERROR
    # Tool side effects (a proposed plan, a logged meal) stand even if the final answer
    # failed, so their cards are attached either way.
    assistant.attachments = runner.attachments
    assistant.plan_changed = runner.plan_changed
    assistant.needs_confirmation = runner.needs_confirmation
    assistant.profile_changed = runner.profile_changed
    assistant.save()
    thread.save(update_fields=["updated_at"])

    if assistant.status == ChatMessage.Status.DONE:
        from .tasks import extract_memory

        try:
            transaction.on_commit(lambda: extract_memory.delay(assistant.pk))
        except Exception as exc:  # noqa: BLE001 — memory is a bonus; the reply is not lost
            logger.warning("could not queue memory extraction: %s", exc)
    return user, assistant


def refusal_guard(athlete, messages, request: str, text, audit, call):
    """R18 §C: an explicit change request turned down without a tool call gets one
    re-prompt to call the tool and present warnings + a confirmation instead.
    Returns (text, audit, record | None)."""
    from . import honesty

    if not honesty.explicit_change_request(request) or honesty.change_tool_called(audit):
        return text, audit, None
    sentence = honesty.declined(text)
    if not sentence:
        return text, audit, None
    record = {"fired": True, "declined": sentence, "outcome": None}
    logger.warning("refusal guard: athlete %s, reply declined an explicit request: %r",
                   athlete.pk, sentence)
    conversation = [*messages, {"role": "assistant", "content": text},
                    {"role": "user", "content": honesty.refusal_reprompt()}]
    try:
        second, more = call(conversation)
    except Exception as exc:  # noqa: BLE001 — keep the first answer
        record.update(outcome="reprompt_failed", reprompt_error=type(exc).__name__)
        return text, audit, record
    record["outcome"] = "tool_called" if honesty.change_tool_called(more) else "still_declined"
    logger.warning("refusal guard outcome for athlete %s: %s", athlete.pk, record["outcome"])
    return second or text, [*audit, *more], record


def honesty_guard(athlete, messages, text, audit, call):
    """R16 §B: a reply that claims a plan change no tool made gets one corrective
    re-prompt; still dishonest (or the re-prompt fails) → a correction line is appended.
    Returns (text, audit, guard record | None)."""
    from . import honesty

    claim = honesty.claimed_change(text)
    if not claim or honesty.mutation_succeeded(audit):
        return text, audit, None
    guard = {"fired": True, "claim": claim, "tools": [a.get("name") for a in audit],
             "outcome": None}
    logger.warning("honesty guard: athlete %s, reply claims a change no tool made: %r",
                   athlete.pk, claim)
    conversation = [*messages, {"role": "assistant", "content": text},
                    {"role": "user", "content": honesty.reprompt(audit)}]
    try:
        second, more = call(conversation)
    except Exception as exc:  # noqa: BLE001 — the first answer is kept, made honest
        guard.update(outcome="note_appended", reprompt_error=type(exc).__name__)
        logger.warning("honesty guard re-prompt failed for athlete %s: %s", athlete.pk, exc)
        return f"{text}\n\n{honesty.CORRECTION_NOTE}", audit, guard
    audit = [*audit, *more]
    if honesty.mutation_succeeded(more):
        guard["outcome"] = "tool_succeeded"
    elif honesty.claimed_change(second):
        guard["outcome"] = "note_appended"
        second = f"{second}\n\n{honesty.CORRECTION_NOTE}"
    else:
        guard["outcome"] = "corrected"
    logger.warning("honesty guard outcome for athlete %s: %s", athlete.pk, guard["outcome"])
    return second or text, audit, guard


def start_thread_with(athlete: Athlete, *, title: str, content: str, attachments: list[dict]):
    """Guide / Review: a new thread whose first exchange is already done."""
    thread = ChatThread.objects.create(athlete=athlete, title=title)
    run_turn(thread, content, clean_attachments(athlete, attachments))
    return thread
