"""Heart-rate zones.

Uses the **heart-rate reserve** (Karvonen) method rather than a plain percentage of
maximum, because it accounts for resting heart rate — and resting heart rate is a real
measurement this system already holds, updated nightly by Garmin. Percentage-of-max
ignores it and puts a fit athlete and an unfit one in the same zones at the same
number.

    HRR = max - resting
    zone bound = resting + HRR x fraction

**No 220-age anywhere.** That formula has a standard deviation of ±10-12 bpm across
individuals, which is wide enough to put someone a full zone out. Where a measured
maximum is unavailable the zones are simply not shown — the same rule the rest of this
project follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

ZoneName = Literal["Z1", "Z2", "Z3", "Z4", "Z5"]

# Lower and upper bound as a fraction of heart-rate reserve.
ZONE_BOUNDS: dict[ZoneName, tuple[float, float]] = {
    "Z1": (0.50, 0.60),
    "Z2": (0.60, 0.70),
    "Z3": (0.70, 0.80),
    "Z4": (0.80, 0.90),
    "Z5": (0.90, 1.00),
}

ZONE_PURPOSE: dict[ZoneName, str] = {
    "Z1": "Recovery. Easy enough that it costs you nothing.",
    "Z2": "Aerobic base. The zone that builds endurance, and the one most beginners "
          "skip by running everything slightly too hard.",
    "Z3": "Steady. Useful in small amounts, but it is where easy runs drift to when "
          "you are not paying attention.",
    "Z4": "Threshold. Hard, controlled, and sparing.",
    "Z5": "Maximum. Short intervals only.",
}

ZONE_LABEL: dict[ZoneName, str] = {
    "Z1": "Recovery", "Z2": "Aerobic base", "Z3": "Steady",
    "Z4": "Threshold", "Z5": "Maximum",
}


@dataclass(frozen=True)
class Zone:
    name: ZoneName
    label: str
    low: int
    high: int
    purpose: str


@dataclass(frozen=True)
class Zones:
    resting_hr: int | None
    max_hr: int
    max_source: str        # how the maximum was arrived at — shown, never hidden
    zones: list[Zone]
    # R10 §B3: where the bounds came from, and whether the easy-zone safety cap bit.
    source: str = "heart_rate_reserve"
    lt_hr: int | None = None
    capped: bool = False

    def of(self, heart_rate: int | None) -> ZoneName | None:
        if heart_rate is None:
            return None
        if heart_rate < self.zones[0].low:
            return None          # below Z1 is not a training zone, it is sitting down
        for zone in self.zones:
            if heart_rate <= zone.high:
                return zone.name
        return "Z5"

    def band(self, name: ZoneName) -> Zone:
        return next(z for z in self.zones if z.name == name)


def build(resting_hr: int, max_hr: int, max_source: str = "measured") -> Zones | None:
    """None when the inputs cannot support zones, rather than a plausible guess."""
    if not resting_hr or not max_hr or max_hr - resting_hr < 40:
        return None

    reserve = max_hr - resting_hr
    zones = [
        Zone(
            name=name,
            label=ZONE_LABEL[name],
            low=round(resting_hr + reserve * low),
            high=round(resting_hr + reserve * high),
            purpose=ZONE_PURPOSE[name],
        )
        for name, (low, high) in ZONE_BOUNDS.items()
    ]
    return Zones(resting_hr=resting_hr, max_hr=max_hr, max_source=max_source, zones=zones)


# --- Percent of maximum: the same method and numbers a Garmin watch shows -----------
# Garmin's default running zones are 50/60/70/80/90 % of max HR, each zone starting
# where the previous one stops (zone 2 = 116-134 at a max of 193). Offered so the
# app and the watch never show the athlete two different "zone 2"s.
PERCENT_MAX_FLOORS: dict[ZoneName, float] = {
    "Z1": 0.50, "Z2": 0.60, "Z3": 0.70, "Z4": 0.80, "Z5": 0.90,
}


def build_percent_max(max_hr: int, resting_hr: int | None = None,
                      max_source: str = "measured") -> Zones | None:
    """Zones as % of max HR, Garmin-style: each zone's top is one below the next floor."""
    if not max_hr or max_hr < 120:
        return None
    floors = [int(max_hr * f + 0.5) for f in PERCENT_MAX_FLOORS.values()]  # half up, as Garmin
    zones = []
    for i, name in enumerate(PERCENT_MAX_FLOORS):
        high = floors[i + 1] - 1 if i + 1 < len(floors) else max_hr
        zones.append(Zone(name=name, label=ZONE_LABEL[name], low=floors[i], high=high,
                          purpose=ZONE_PURPOSE[name]))
    return Zones(resting_hr=resting_hr, max_hr=max_hr, max_source=max_source,
                 zones=zones, source="percent_of_max")


def time_in_zones(
    samples: Iterable[tuple[float, int | None]], zones: Zones
) -> dict[str, float]:
    """Seconds spent in each zone, from (offset_s, heart_rate) pairs.

    Weighted by the real gap between samples rather than counting them: Garmin drops
    to smart recording on longer activities, and counting samples would then under-report
    exactly the long steady efforts that matter most for aerobic base.
    """
    ordered = sorted(samples, key=lambda pair: pair[0])
    totals: dict[str, float] = {name: 0.0 for name in ZONE_BOUNDS}
    totals["below"] = 0.0

    for (start, heart_rate), (next_start, _) in zip(ordered, ordered[1:]):
        gap = max(next_start - start, 0.0)
        if gap > 30:
            continue          # a gap this large is a pause, not time in a zone
        key = zones.of(heart_rate) or "below"
        totals[key] += gap

    return {name: round(seconds) for name, seconds in totals.items()}


# --- R10 §B3: zones from the lactate threshold ------------------------------------
# Fractions of lactate-threshold heart rate (Friel, running). Z5 runs to max HR.
LT_BOUNDS: dict[ZoneName, tuple[float, float]] = {
    "Z1": (0.65, 0.85),
    "Z2": (0.85, 0.89),
    "Z3": (0.89, 0.94),
    "Z4": (0.94, 1.00),
    "Z5": (1.00, None),
}
LT_MIN_HR, LT_MAX_HR = 120, 210
LT_MAX_FACTOR = 1.06       # max HR estimate when none is known (Z5's top only)
EASY = ("Z1", "Z2")


def lt_plausible(lt_hr: int | None, max_hr: int | None = None) -> bool:
    if lt_hr is None or not LT_MIN_HR <= lt_hr <= LT_MAX_HR:
        return False
    return max_hr is None or lt_hr < max_hr


def from_lactate_threshold(lt_hr: int, *, max_hr: int | None = None,
                           resting_hr: int | None = None,
                           reserve: Zones | None = None,
                           hr_ceiling: int | None = None) -> Zones | None:
    """Zones from Garmin's lactate threshold, with the easy-zone safety rule.

    **Easy zones never get harder.** Every Z1/Z2 bound is the minimum of the LT value,
    the heart-rate-reserve value (when those zones exist) and the athlete's HR ceiling,
    so an easy run never targets a higher heart rate than it did before the LT arrived.
    Z3 starts at Z2's (possibly lowered) top; the harder zones come from the LT alone.
    None for an implausible threshold.
    """
    if not lt_plausible(lt_hr, max_hr):
        return None
    top = max_hr or round(lt_hr * LT_MAX_FACTOR)
    raw: dict[str, tuple[int, int]] = {}
    for name, (low, high) in LT_BOUNDS.items():
        raw[name] = (round(lt_hr * low), top if high is None else round(lt_hr * high))

    capped = False
    for name in EASY:
        low, high = raw[name]
        limits_low, limits_high = [low], [high]
        if reserve is not None:
            band = reserve.band(name)
            limits_low.append(band.low)
            limits_high.append(band.high)
        if hr_ceiling:
            limits_low.append(hr_ceiling)
            limits_high.append(hr_ceiling)
        new = (min(limits_low), min(limits_high))
        if new != (low, high):
            capped = True
        raw[name] = new
    # Keep the zones contiguous and ordered after the cap.
    z1_low, z1_high = raw["Z1"]
    z2_low, z2_high = raw["Z2"]
    z2_low = min(max(z2_low, z1_high), z2_high)
    z1_high = min(z1_high, z2_low)
    z1_low = min(z1_low, z1_high)
    raw["Z1"], raw["Z2"] = (z1_low, z1_high), (z2_low, z2_high)
    z3_low, z3_high = raw["Z3"]
    raw["Z3"] = (z2_high, max(z3_high, z2_high))

    zones = [Zone(name=name, label=ZONE_LABEL[name], low=low, high=high,
                  purpose=ZONE_PURPOSE[name]) for name, (low, high) in raw.items()]
    return Zones(resting_hr=resting_hr, max_hr=top,
                 max_source=(reserve.max_source if reserve and max_hr else
                             "measured" if max_hr else "lactate_threshold_estimate"),
                 zones=zones, source="lactate_threshold", lt_hr=lt_hr, capped=capped)
