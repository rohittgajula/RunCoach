"""R25: the food profile, and today's plan.

    GET/PUT /diet/profile/    what he eats and what he can cook
    GET     /diet/foods/      the table, so the UI can offer real choices
    GET     /diet/plan/       today's plan, built fresh, saved nowhere
    GET     /diet/missing/    the last two weeks' shortfalls — no model, no cost
"""

from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.coaching.client import AIUnavailable
from apps.coaching.throttles import ChatThrottle
from nutrition import foods as F

from . import dayplan
from .models import FoodProfile

SLOTS = ("breakfast", "lunch", "snack", "dinner")


class KeyListField(serializers.ListField):
    """Food keys, checked against the table on the way in.

    An unknown key here would become a filter that silently matches nothing —
    a dislike that stops excluding, or a staple that stops appearing — and
    nothing downstream would ever raise.
    """

    child = serializers.CharField(max_length=40)

    def to_internal_value(self, data):
        keys = super().to_internal_value(data)
        unknown = [k for k in keys if k not in F.BY_KEY]
        if unknown:
            raise serializers.ValidationError(f"Not foods I know: {', '.join(sorted(unknown))}.")
        return sorted(set(keys))


class ProfileSerializer(serializers.ModelSerializer):
    dislikes = KeyListField(required=False)
    staples = KeyListField(required=False)
    provided = serializers.ListField(
        child=serializers.ChoiceField(choices=SLOTS), required=False,
    )

    class Meta:
        model = FoodProfile
        fields = ["pattern", "prep", "provided", "dislikes", "staples", "notes"]


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def profile(request):
    athlete = request.user.athlete
    row, _ = FoodProfile.objects.get_or_create(athlete=athlete)
    if request.method == "PUT":
        form = ProfileSerializer(row, data=request.data, partial=True)
        form.is_valid(raise_exception=True)
        row = form.save()
    return Response({
        **ProfileSerializer(row).data,
        "patterns": [{"value": v, "label": l} for v, l in FoodProfile.Pattern.choices],
        "preps": [{"value": v, "label": l} for v, l in FoodProfile.Prep.choices],
        "slots": list(SLOTS),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def food_list(request):
    """Every food, with what one portion is — so the preferences screen can let
    him tick real things rather than type names that will not match a key."""
    row = FoodProfile.objects.filter(athlete=request.user.athlete).first()
    available = {
        f.key for f in F.allowed(row.pattern if row else "veg", row.prep if row else "none")
    }
    return Response({
        "foods": [
            {
                "key": f.key, "name": f.name, "portion": f.portion,
                "one_portion": F.describe(f.key, 1),
                "pattern": f.pattern, "prep": f.prep,
                "mess": f.mess, "slots": list(f.slots),
                "iron_mg": f.iron_mg, "haem": f.haem,
                "vitamin_c_mg": f.vitamin_c_mg,
                "note": f.note,
                "available": f.key in available,
                **F.total([(f.key, 1)]).rounded(),
            }
            for f in F.FOODS
        ],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def missing(request):
    """The two-week picture. No model call, so it is free and always available —
    the plan endpoint can 503 and this still answers."""
    athlete = request.user.athlete
    return Response(dayplan.shortfalls(athlete, athlete.local_today))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([ChatThrottle])
def plan_today(request):
    try:
        return Response(dayplan.build(request.user.athlete))
    except AIUnavailable as exc:
        return Response(
            {"detail": f"I could not put a day together right now ({exc})."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
