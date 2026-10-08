"""Chat threads, messages and memory (spec §5). Everything scoped to the athlete."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .chat import clean_attachments, run_turn
from .models import ChatMessage, ChatThread, MemoryFact
from .throttles import ChatThrottle
from .tools import add_fact

MAX_CONTENT = 4000


def thread_json(thread: ChatThread) -> dict:
    return {"id": thread.pk, "title": thread.title, "updated_at": thread.updated_at,
            "created_at": thread.created_at}


def attachments_json(athlete, refs: list[dict]) -> list[dict]:
    """Expand {type, id} references. Anything deleted since is simply left out."""
    from apps.activities.models import Activity
    from apps.diet.models import Meal
    from apps.diet.services import meal_json
    from apps.planning.models import PlannedWorkout, TrainingPlan
    from apps.planning.presenters import activity_card, plan_summary, workout_json

    out = []
    for ref in refs or []:
        kind, pk = ref.get("type"), ref.get("id")
        if kind == "workout":
            obj = PlannedWorkout.objects.filter(athlete=athlete, pk=pk).select_related("phase").first()
            if obj:
                out.append({"type": "workout", "workout": workout_json(obj)})
        elif kind == "activity":
            obj = Activity.objects.filter(athlete=athlete, pk=pk).select_related("metrics").first()
            if obj:
                out.append({"type": "activity", "activity": activity_card(athlete, obj)})
        elif kind == "plan_proposal":
            obj = TrainingPlan.objects.filter(athlete=athlete, pk=pk).select_related("race").first()
            if obj:
                out.append({"type": "plan_proposal", "plan": plan_summary(obj, athlete.local_today)})
        elif kind == "meal":
            obj = Meal.objects.filter(athlete=athlete, pk=pk).first()
            if obj:
                out.append({"type": "meal", "meal": meal_json(obj)})
    return out


def message_json(athlete, message: ChatMessage) -> dict:
    return {
        "id": message.pk, "role": message.role, "content": message.content,
        "attachments": attachments_json(athlete, message.attachments),
        "status": message.status, "created_at": message.created_at,
        # R16 §B: the "Plan updated" chip.
        "plan_changed": message.plan_changed or [],
        "needs_confirmation": message.needs_confirmation,
        # R18 §C: settings changed through update_profile.
        "profile_changed": message.profile_changed or [],
    }


def _thread(request, pk):
    return ChatThread.objects.filter(athlete=request.user.athlete, pk=pk).first()


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def threads(request):
    athlete = request.user.athlete
    if request.method == "POST":
        title = str(request.data.get("title") or "")[:120]
        return Response(thread_json(ChatThread.objects.create(athlete=athlete, title=title)),
                        status=status.HTTP_201_CREATED)
    return Response([
        {"id": t.pk, "title": t.title, "updated_at": t.updated_at}
        for t in ChatThread.objects.filter(athlete=athlete)
    ])


@api_view(["PATCH", "DELETE", "GET"])
@permission_classes([IsAuthenticated])
def thread_detail(request, pk: int):
    thread = _thread(request, pk)
    if thread is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "DELETE":
        thread.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == "PATCH":
        title = str(request.data.get("title") or "").strip()[:120]
        if not title:
            return Response({"detail": "title is required."}, status=400)
        thread.title = title
        thread.save(update_fields=["title", "updated_at"])
    return Response(thread_json(thread))


class _ChatPostThrottle(ChatThrottle):
    """Only POSTs (model turns) are throttled; reading messages is free."""

    def allow_request(self, request, view):
        return request.method != "POST" or super().allow_request(request, view)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([_ChatPostThrottle])
def messages(request, pk: int):
    thread = _thread(request, pk)
    if thread is None:
        return Response({"detail": "Not found."}, status=404)
    athlete = request.user.athlete
    if request.method == "GET":
        rows = thread.messages.exclude(role=ChatMessage.Role.TOOL)
        return Response([message_json(athlete, m) for m in rows])

    content = str(request.data.get("content") or "").strip()
    if not content:
        return Response({"detail": "Say something first."}, status=400)
    if len(content) > MAX_CONTENT:
        return Response({"detail": f"Keep it under {MAX_CONTENT} characters."}, status=400)
    attachments = clean_attachments(athlete, request.data.get("attachments"))
    user, assistant = run_turn(thread, content, attachments)
    return Response({"user": message_json(athlete, user),
                     "assistant": message_json(athlete, assistant),
                     "plan_changed": assistant.plan_changed or [],
                     "needs_confirmation": assistant.needs_confirmation,
                     "profile_changed": assistant.profile_changed or []})


def fact_json(fact: MemoryFact, applied: set | None = None) -> dict:
    from analysis.memory_facts import CATEGORIES
    from apps.athletes.profile_params import applied_parameter_ids, parameter_json

    category = fact.category if fact.category in CATEGORIES else "other"
    if applied is None:
        applied = applied_parameter_ids(fact.athlete)
    return {"id": fact.pk, "text": fact.text, "category": category,
            "category_label": CATEGORIES[category],
            "source": "app" if fact.source == MemoryFact.Source.MANUAL else fact.source,
            "pinned": fact.pinned, "created_at": fact.created_at,
            "updated_at": fact.updated_at or fact.created_at, "edited": fact.edited,
            # R18: what this fact sets (memory is the live source of these parameters).
            "parameters": [parameter_json(p, applied) for p in fact.parameters.all()],
            "parse_pending": fact.parse_pending}


PRIVATE_DETAIL = "The private habit is never stored in the coach's memory."


def _ordered(athlete):
    return MemoryFact.objects.filter(athlete=athlete).order_by("-pinned", "-created_at", "-id")


def _fact_fields(athlete, data: dict, fact: MemoryFact | None = None) -> dict | Response:
    from analysis.memory_facts import CATEGORIES, MAX_PINNED, mentions_private_habit

    out: dict = {}
    if "text" in data or fact is None:
        text = " ".join(str(data.get("text") or "").split())
        if not text:
            return Response({"detail": "text is required."}, status=400)
        if len(text) > 300:
            return Response({"detail": "text must be at most 300 characters."}, status=400)
        if mentions_private_habit(text):
            return Response({"detail": PRIVATE_DETAIL}, status=400)
        out["text"] = text
    if "category" in data and data["category"] is not None:
        if data["category"] not in CATEGORIES:
            return Response({"detail": "category must be health, schedule, goals or other."},
                            status=400)
        out["category"] = data["category"]
    if "pinned" in data:
        if not isinstance(data["pinned"], bool):
            return Response({"detail": "pinned must be true or false."}, status=400)
        if data["pinned"] and not (fact and fact.pinned):
            pinned = MemoryFact.objects.filter(athlete=athlete, pinned=True).count()
            if pinned >= MAX_PINNED:
                return Response({"detail": f"At most {MAX_PINNED} facts can be pinned."},
                                status=400)
        out["pinned"] = data["pinned"]
    return out


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def memory(request):
    from analysis.memory_facts import CATEGORIES, ORDER

    athlete = request.user.athlete
    if request.method == "POST":
        data = request.data if isinstance(request.data, dict) else {}
        fields = _fact_fields(athlete, data)
        if isinstance(fields, Response):
            return fields
        key = fields["text"].lower().rstrip(".")
        existing = next((f for f in MemoryFact.objects.filter(athlete=athlete)
                         if f.text.lower().rstrip(".") == key), None)
        if existing is not None:
            return Response(fact_json(existing), status=200)
        fact = add_fact(athlete, fields["text"], MemoryFact.Source.MANUAL,
                        category=fields.get("category"), pinned=fields.get("pinned", False))
        return Response(fact_json(fact), status=status.HTTP_201_CREATED)
    from apps.athletes.profile_params import applied_parameter_ids

    applied = applied_parameter_ids(athlete)        # also parses facts never parsed
    facts = [fact_json(f, applied) for f in _ordered(athlete).prefetch_related("parameters")]
    if str(request.query_params.get("grouped", "")).lower() in ("1", "true"):
        return Response({"count": len(facts), "pinned": sum(1 for f in facts if f["pinned"]),
                         "groups": [{"key": key, "label": CATEGORIES[key],
                                     "facts": [f for f in facts if f["category"] == key]}
                                    for key in ORDER]})
    return Response(facts)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def memory_delete(request, pk: int):
    athlete = request.user.athlete
    fact = MemoryFact.objects.filter(athlete=athlete, pk=pk).first()
    if fact is None:
        return Response({"detail": "Not found."}, status=404)
    if request.method == "PATCH":
        data = request.data if isinstance(request.data, dict) else {}
        fields = _fact_fields(athlete, data, fact)
        if isinstance(fields, Response):
            return fields
        if not fields:
            return Response({"detail": "Send text, category and/or pinned."}, status=400)
        if "text" in fields:
            key = fields["text"].lower().rstrip(".")
            if any(f.text.lower().rstrip(".") == key
                   for f in MemoryFact.objects.filter(athlete=athlete).exclude(pk=fact.pk)):
                return Response({"detail": "The coach already knows this."}, status=400)
            if fields["text"] != fact.text:
                fact.edited = True
        for k, v in fields.items():
            setattr(fact, k, v)
        fact.save()
        return Response(fact_json(fact))
    fact.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def fact_parameter(request, pk: int, pid: int):
    """R18: confirm or reject one parsed parameter of a memory fact."""
    from apps.athletes.profile_params import parameter_json, resolve, sync_plan_fields
    from django.utils import timezone

    from .models import FactParameter

    athlete = request.user.athlete
    param = FactParameter.objects.filter(athlete=athlete, fact_id=pk, pk=pid).first()
    if param is None:
        return Response({"detail": "Not found."}, status=404)
    action = (request.data or {}).get("action") if isinstance(request.data, dict) else None
    if action not in ("confirm", "reject"):
        return Response({"detail": "action must be confirm or reject."}, status=400)
    if action == "confirm":
        param.status, param.needs_review = FactParameter.Status.ACTIVE, False
        param.conflict, param.effective_at = "", timezone.now()
    else:
        param.status, param.needs_review = FactParameter.Status.REJECTED, False
    param.save()
    sync_plan_fields(athlete, force_param_ids=(param.pk,) if action == "confirm" else ())
    param.refresh_from_db()
    athlete.refresh_from_db()
    effective = resolve(athlete, param.key)
    return Response({"parameter": parameter_json(param, {effective["parameter_id"]}),
                     "effective": effective})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def profile_effective(request):
    """R18: every profile parameter's effective value and where it comes from."""
    from apps.athletes.profile_params import effective_json

    return Response(effective_json(request.user.athlete))
