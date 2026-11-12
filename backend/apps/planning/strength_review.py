"""Reviewing a gym session, and letting the review move the programme.

The ladders in `planning/strength.py` only ever moved from a settings screen,
which in practice means they did not move. A programme that cannot hear "the
wall push-ups were easy" is a PDF with a calendar attached.

Two things are recorded, and they are different questions.

**How the session went, as one number.** Used for the ends only: a 1 means the
whole thing was too easy and a 5 means it could not be finished. A 3 is the
session working as intended and changes nothing, which is the common case and
should be cheap to say.

**Which movements were easy or impossible, per pattern.** Because "that was
easy" about six movements says nothing about which of them it was easy for, and
moving all six because the calf work was comfortable is how somebody ends up
failing a push-up they were never ready for.

Only the next session changes. Nothing here rewrites a session already done,
and nothing reaches into the running plan — a hard gym session is not evidence
about Thursday's run.
"""

from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from planning.strength import MAX_LEVEL, PATTERNS, graduate, rung_name

from .models import StrengthSession

logger = logging.getLogger(__name__)

#: Only the ends of the scale move anything. 2 and 4 are "slightly off", which
#: is what a programme is supposed to feel like most weeks.
TOO_EASY = 1
COULD_NOT_FINISH = 5


class ReviewSerializer(serializers.Serializer):
    difficulty = serializers.IntegerField(min_value=1, max_value=5, required=False)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    easy = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    hard = serializers.ListField(child=serializers.CharField(), required=False, default=list)

    def validate(self, attrs):
        unknown = (set(attrs.get("easy", [])) | set(attrs.get("hard", []))) - set(PATTERNS)
        if unknown:
            raise serializers.ValidationError(
                {"easy": f"Not movement patterns: {', '.join(sorted(unknown))}."}
            )
        both = set(attrs.get("easy", [])) & set(attrs.get("hard", []))
        if both:
            raise serializers.ValidationError(
                {"easy": f"Cannot be both easy and hard: {', '.join(sorted(both))}."}
            )
        return attrs


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def strength_review(request, pk: int):
    """Record how a session went and move the ladders accordingly."""
    session = StrengthSession.objects.filter(athlete=request.user.athlete, pk=pk).first()
    if session is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    form = ReviewSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data
    athlete = request.user.athlete

    levels = dict(athlete.strength_levels or {})
    easy = list(data.get("easy", []))
    hard = list(data.get("hard", []))

    # A 5 steps everything back. Somebody who could not finish does not need a
    # diagnosis of which movement beat them; they need the next session to be
    # one they can finish.
    if data.get("difficulty") == COULD_NOT_FINISH:
        hard = list(PATTERNS)
    # A 1 with nothing named is taken at its word rather than ignored — the
    # alternative is a screen that asks how it went and then does nothing.
    elif data.get("difficulty") == TOO_EASY and not easy:
        easy = list(PATTERNS)

    moved: list[dict] = []
    for pattern in easy:
        before = max(1, min(int(levels.get(pattern, 1)), MAX_LEVEL))
        levels = graduate(levels, pattern, 1)
        if levels[pattern] != before:
            moved.append({
                "pattern": pattern, "direction": "up",
                "to": rung_name(pattern, levels[pattern]),
            })
    for pattern in hard:
        before = max(1, min(int(levels.get(pattern, 1)), MAX_LEVEL))
        levels = graduate(levels, pattern, -1)
        if levels[pattern] != before:
            moved.append({
                "pattern": pattern, "direction": "down",
                "to": rung_name(pattern, levels[pattern]),
            })

    session.difficulty = data.get("difficulty")
    session.notes = data.get("notes", "")
    session.moved_up = easy
    session.moved_down = hard
    session.reviewed_at = timezone.now()
    if session.status == StrengthSession.Status.PLANNED:
        session.status = StrengthSession.Status.COMPLETED
    session.save(update_fields=[
        "difficulty", "notes", "moved_up", "moved_down", "reviewed_at", "status",
    ])

    athlete.strength_levels = levels
    athlete.save(update_fields=["strength_levels", "updated_at"])

    # Only sessions still ahead are rebuilt. Rewriting one already done would
    # change the record of what was actually lifted.
    from .strength_service import place_for

    placed = place_for(athlete)

    logger.info(
        "strength review: athlete %s session %s difficulty=%s moved=%s",
        athlete.pk, session.pk, session.difficulty, moved,
    )
    return Response({
        "session_id": session.pk,
        "difficulty": session.difficulty,
        "moved": moved,
        "levels": levels,
        "upcoming_rebuilt": placed.get("created", 0) + placed.get("updated", 0)
        if isinstance(placed, dict) else 0,
        "detail": (
            "Noted — nothing needed changing." if not moved
            else "Your next session has been adjusted."
        ),
    })
