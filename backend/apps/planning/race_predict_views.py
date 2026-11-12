"""Garmin's race prediction and ours, side by side, with the reason they differ.

Both numbers already existed and were never shown together. Garmin's sit under
Health; ours is only produced for a saved race, which Rohit has none of. So the
one thing he actually asked — *how fast could I do a 5k* — had two answers in
the database and no screen.

They disagree, and the disagreement is the content:

    Garmin   5k 46:03           our range   46:54 – 74:16
    Garmin  10k 1:39:30

Garmin's 46:03 is 9:13 per kilometre held continuously for five kilometres.
Rohit's longest unbroken run is 11:39 and his running pace is about 10:04. The
number is not wrong about his aerobic fitness — it is answering a question
about a runner who runs the whole way, and he does not yet.

So the comparison is framed as *what each one assumes*, not as who is right.
Garmin's is a ceiling: what the engine could do if the legs could hold it. Ours
is a range, wide on purpose, that includes the walking he will actually take.
Showing one without the other leaves an athlete either flattered or deflated,
and the gap between them is the single most useful thing on the screen —
it closes as his continuous block grows, which is exactly what the plan is for.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.ingest.models import DailyMetrics

from .models import Race
from .services import prediction_for

#: The distances Garmin predicts, and what we can meaningfully predict beside it.
DISTANCES: tuple[tuple[str, float, str], ...] = (
    ("5k", 5.0, "race_pred_5k_s"),
    ("10k", 10.0, "race_pred_10k_s"),
    ("half", 21.1, "race_pred_half_s"),
    ("marathon", 42.2, "race_pred_marathon_s"),
)

#: Garmin stops updating its estimate without sustained running, so an old one
#: is reported with its age rather than as today's answer.
GARMIN_STALE_DAYS = 21


def _garmin_row(athlete):
    return (
        DailyMetrics.objects.filter(athlete=athlete)
        .exclude(race_pred_5k_s=None)
        .order_by("-metric_date")
        .first()
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def race_predictions(request):
    """Both predictions per distance, and what separates them."""
    athlete = request.user.athlete
    today = athlete.local_today
    row = _garmin_row(athlete)

    # Our prediction needs a date to project to. Without a saved race, project to
    # a point far enough out to be a fair comparison but near enough to mean
    # something — Garmin's answer is about today, ours is about the near future,
    # and that difference is itself worth naming.
    horizon = today + dt.timedelta(days=56)

    out = []
    for key, km, field in DISTANCES:
        garmin_s = getattr(row, field, None) if row else None
        race = Race(athlete=athlete, name=key, date=horizon, distance_km=km)
        ours = prediction_for(athlete, race)

        gap_s = None
        if garmin_s and ours.likely_finish_s:
            gap_s = round(ours.likely_finish_s - garmin_s)

        out.append({
            "key": key,
            "distance_km": km,
            "garmin_s": round(garmin_s) if garmin_s else None,
            "ours": dataclasses.asdict(ours),
            "gap_s": gap_s,
        })

    explanation = None
    if row and any(d["garmin_s"] for d in out):
        longest = max(
            (s.longest_run_s for s in _history(athlete)), default=0.0,
        )
        explanation = {
            "garmin_assumes": (
                "Garmin's figure is what your engine could do if your legs held "
                "the whole way. It is computed from heart rate against pace and "
                "takes no view on whether you can run the distance without "
                "stopping."
            ),
            "ours_assumes": (
                "Ours is a range built from your segmented runs — the running "
                "and the walking separately — so it includes the walk breaks you "
                "would actually take."
            ),
            "longest_unbroken_s": round(longest),
            "why_they_differ": (
                f"Your longest unbroken run is {longest / 60:.0f} minutes. Until "
                "that grows, the gap between the two numbers is mostly walking, "
                "not fitness — and it closes as the block grows, which is what "
                "the plan is for."
            ) if longest else None,
        }

    return Response({
        "today": today,
        "projected_to": horizon,
        "garmin_as_of": row.metric_date if row else None,
        "garmin_stale": bool(
            row and (today - row.metric_date).days > GARMIN_STALE_DAYS
        ),
        "garmin_age_days": (today - row.metric_date).days if row else None,
        "distances": out,
        "explanation": explanation,
    })


def _history(athlete):
    from .services import run_history

    return run_history(athlete)
