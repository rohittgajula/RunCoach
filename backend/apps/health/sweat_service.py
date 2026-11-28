"""His measured sweat rate, for anything that needs a hydration number.

Separate from `sweat_views` so that weather advice and the race-day plan can ask
for the rate without importing a views module, and so there is exactly one place
that decides which stored tests count.

Everything numeric is in `analysis/sweat.py`. This is the database half.
"""

from __future__ import annotations

import datetime as dt

from analysis import sweat

from .models import SweatTest


def usable_tests(athlete) -> list[dict]:
    """Stored tests reduced to what `analysis.sweat` wants, dropping any row whose
    numbers no longer survive validation — a test that cannot be turned into a rate
    must not be allowed to drag a median around."""
    out = []
    for row in SweatTest.objects.filter(athlete=athlete).only(
        "weight_before_kg", "weight_after_kg", "drank_ml", "minutes", "band", "done_on"
    ):
        try:
            measured = sweat.measure(
                weight_before_kg=row.weight_before_kg,
                weight_after_kg=row.weight_after_kg,
                drank_ml=row.drank_ml, minutes=row.minutes,
            )
        except ValueError:
            continue
        out.append({"rate_l_h": measured["rate_l_h"], "band": row.band or None,
                    "done_on": row.done_on})
    return out


def measured_rate(athlete, band: str, *, today: dt.date | None = None) -> float | None:
    """His litres per hour for one heat band, or None when he has never tested.

    Callers pass the result straight to `weather_advice.hydration(...,
    measured_l_h=...)`, where None means "use the population table as before".
    """
    if band not in sweat.BAND_RATIO:
        return None
    found = sweat.rate_for_band(
        usable_tests(athlete), band, today=today or athlete.local_today
    )
    return found["rate_l_h"] if found else None
