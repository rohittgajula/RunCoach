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
                     "needs_confirmation": assistant.needs_confirmation})


def fact_json(fact: MemoryFact) -> dict:
    return {"id": fact.pk, "text": fact.text, "source": fact.source, "created_at": fact.created_at}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def memory(request):
    athlete = request.user.athlete
    if request.method == "POST":
        text = str(request.data.get("text") or "").strip()
        if not text:
            return Response({"detail": "text is required."}, status=400)
        fact = add_fact(athlete, text, MemoryFact.Source.MANUAL)
        if fact is None:
            existing = next(
                f for f in MemoryFact.objects.filter(athlete=athlete)
                if f.text.lower().rstrip(".") == " ".join(text.split())[:300].lower().rstrip(".")
            )
            return Response(fact_json(existing), status=200)
        return Response(fact_json(fact), status=status.HTTP_201_CREATED)
    return Response([fact_json(f) for f in MemoryFact.objects.filter(athlete=athlete)])


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def memory_delete(request, pk: int):
    fact = MemoryFact.objects.filter(athlete=request.user.athlete, pk=pk).first()
    if fact is None:
        return Response({"detail": "Not found."}, status=404)
    fact.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
