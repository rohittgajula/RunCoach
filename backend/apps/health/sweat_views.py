"""R26 §1: sweat tests — his own litres per hour, in place of a population table.

    GET    /health/sweat/        his tests, his rate per heat band, today's plan
    POST   /health/sweat/        one test (two weigh-ins and a duration)
    DELETE /health/sweat/{id}/   remove one

Everything numeric comes from `analysis/sweat.py`, which is pure and has no idea
this file exists. This module's whole job is to find the weather the run happened
in, hand the numbers over, and turn a ValueError into a 400 he can read.

The response always carries what the app *would* have guessed from
`weather_advice.SWEAT_L_H`, next to what he actually measured. Two reasons: the
difference is the entire argument for doing the test, and a measured rate that
lands on the table value is information too.
"""

from __future__ import annotations

import datetime as dt

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analysis import sweat, weather_advice
from apps.planning.models import PlannedWorkout

from .models import SweatTest
from .sweat_service import usable_tests

#: Said on every response. The app measures and arithmetises; it does not treat.
STANDING_NOTE = (
    "This is your own measurement, not medical advice. Losing more than about 2% of "
    "your body weight on a run costs performance; much more than that in heat is a "
    "reason to stop, not to push."
)

RUN_KINDS_WORTH_TESTING = ("LONG", "TEMPO", "INTERVALS", "EASY", "RACE")


class TestIn(serializers.Serializer):
    done_on = serializers.DateField()
    weight_before_kg = serializers.FloatField()
    weight_after_kg = serializers.FloatField()
    drank_ml = serializers.IntegerField(min_value=0, max_value=sweat.MAX_DRANK_ML,
                                        required=False, default=0)
    minutes = serializers.IntegerField(min_value=1, max_value=600)
    # Optional: he can type what it felt like, or leave it and let the weather say.
    feels_like_c = serializers.FloatField(required=False, allow_null=True)
    activity_id = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True,
                                 default="")

    def validate_done_on(self, value: dt.date) -> dt.date:
        if value > dt.date.today() + dt.timedelta(days=1):
            raise serializers.ValidationError("That date is in the future.")
        return value


def _band_for(athlete, day: dt.date, feels_like: float | None) -> tuple[str, float | None]:
    """The heat band the run was in, and the temperature it came from.

    His own number wins when he typed one: he was there. Otherwise today's weather,
    and only today's — the forecast API cannot be asked about last Tuesday, and
    guessing a band for a past run would quietly file it under the wrong one.
    """
    if feels_like is not None:
        return weather_advice.heat_band(feels_like, None), feels_like
    if day != athlete.local_today:
        return "", None
    try:
        from apps.ingest.weather_services import weather_today

        body = weather_today(athlete, include_run=False)
    except Exception:  # noqa: BLE001 — no weather is a fine outcome, not an error
        return "", None
    if not body.get("available"):
        return "", None
    now = body.get("now") or {}
    temp = now.get("feels_like")
    if temp is None:
        return "", None
    return weather_advice.heat_band(temp, now.get("dew_point")), temp


def _test_json(row: SweatTest) -> dict:
    """Stored columns plus everything derived from them. A test that cannot be
    re-derived (the arithmetic has moved on and this row no longer passes) still
    shows its raw numbers rather than vanishing."""
    out = {
        "id": row.pk, "done_on": row.done_on, "minutes": row.minutes,
        "weight_before_kg": row.weight_before_kg, "weight_after_kg": row.weight_after_kg,
        "drank_ml": row.drank_ml, "band": row.band or None,
        "feels_like_c": row.feels_like_c, "note": row.note,
        "activity_id": row.activity_id,
    }
    try:
        out.update(sweat.measure(
            weight_before_kg=row.weight_before_kg, weight_after_kg=row.weight_after_kg,
            drank_ml=row.drank_ml, minutes=row.minutes,
        ))
        out["usable"] = True
    except ValueError as exc:
        out["usable"] = False
        out["problem"] = str(exc)
    return out


def _rates(usable: list[dict], today: dt.date) -> dict:
    """His rate in each band, beside what the table would have said."""
    out = {}
    for band in sweat.BANDS:
        measured = sweat.rate_for_band(usable, band, today=today)
        out[band] = {
            "table_l_h": weather_advice.SWEAT_L_H[band],
            "measured": measured,
            # The drinking plan the app will actually use for this band.
            "plan": sweat.drink_plan(
                measured["rate_l_h"] if measured else weather_advice.SWEAT_L_H[band], None
            ),
        }
    return out


def _today_plan(athlete, usable: list[dict], today: dt.date) -> dict | None:
    """Today's planned run, costed in fluid. The point of the whole feature: not
    "drink a lot", but "this run, at this rate, puts you 1.9% down"."""
    workout = (PlannedWorkout.objects
               .filter(athlete=athlete, date=today, kind__in=RUN_KINDS_WORTH_TESTING)
               .order_by("id").first())
    if workout is None or not workout.duration_s:
        return None
    minutes = workout.duration_s / 60.0
    band, temp = _band_for(athlete, today, None)
    # No weather to be had: assume the middle band rather than refuse to answer,
    # and `feels_like_c: null` in the response is how the screen knows to say so.
    band = band or "warm"
    measured = sweat.rate_for_band(usable, band, today=today)
    rate = measured["rate_l_h"] if measured else weather_advice.SWEAT_L_H[band]
    plan = sweat.drink_plan(rate, minutes)
    weight = athlete.weight_kg
    out = {
        "title": workout.title, "kind": workout.kind, "minutes": round(minutes),
        "band": band, "feels_like_c": temp,
        # His actual provenance, not just measured-or-not: a rate scaled from a
        # test he did in different weather is his, but it is not a measurement of
        # today, and a screen that calls it one is overclaiming.
        "source": measured["source"] if measured else "table",
        "from_band": measured.get("from_band") if measured else None,
        "plan": plan,
    }
    if weight:
        out["if_you_drink_nothing"] = sweat.loss_at(rate, minutes, weight, 0.0)
        out["if_you_follow_the_plan"] = sweat.loss_at(
            rate, minutes, weight, plan["during_ml_per_h"])
    return out


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def sweat_tests(request):
    athlete = request.user.athlete
    today = athlete.local_today

    if request.method == "POST":
        form = TestIn(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        # Reject before storing. A test that cannot be turned into a rate is not a
        # row worth keeping, and the reason is more useful than the row.
        try:
            sweat.measure(
                weight_before_kg=data["weight_before_kg"],
                weight_after_kg=data["weight_after_kg"],
                drank_ml=data["drank_ml"], minutes=data["minutes"],
                # Only on the way in. Re-checking a stored test against his current
                # profile weight would quietly drop good old tests once he has
                # gained or lost 15 kg, and the test was true when he did it.
                expected_kg=athlete.weight_kg,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        band, temp = _band_for(athlete, data["done_on"], data.get("feels_like_c"))
        row = SweatTest.objects.create(
            athlete=athlete, done_on=data["done_on"],
            weight_before_kg=data["weight_before_kg"],
            weight_after_kg=data["weight_after_kg"],
            drank_ml=data["drank_ml"], minutes=data["minutes"],
            feels_like_c=temp, band=band, note=data["note"],
            activity_id=data.get("activity_id") or None,
        )
        return Response(_test_json(row), status=status.HTTP_201_CREATED)

    rows = [_test_json(r) for r in SweatTest.objects.filter(athlete=athlete)]
    usable = usable_tests(athlete)
    return Response({
        "tests": rows,
        "rates": _rates(usable, today),
        "today": _today_plan(athlete, usable, today),
        "how_to": {
            "steps": [
                "Weigh yourself in as little as possible, right before the run.",
                "Note everything you drink while you are out, in ml.",
                "Towel off and weigh yourself again, in the same clothes as before.",
            ],
            "best_run": (
                f"A run of {sweat.MIN_MINUTES} minutes or more, in the weather you "
                "usually run in. One test is enough to beat the guess; one per season "
                "keeps it honest."
            ),
        },
        "standing_note": STANDING_NOTE,
    })


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def sweat_test_detail(request, pk: int):
    deleted, _ = SweatTest.objects.filter(athlete=request.user.athlete, pk=pk).delete()
    if not deleted:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(status=status.HTTP_204_NO_CONTENT)
