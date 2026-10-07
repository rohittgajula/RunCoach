"""Shared glue for the R10 Health endpoints: ranges and per-day data readers."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from rest_framework.exceptions import APIException

RANGES = {"7d": 7, "4w": 28, "3m": 91, "6m": 182, "1y": 365}


class BadRequest(APIException):
    """400 {detail: str}."""

    status_code = 400
    default_code = "bad_request"


def parse_range(request, default: str) -> str:
    value = request.query_params.get("range") or default
    if value not in RANGES:
        raise BadRequest("range must be one of 7d, 4w, 3m, 6m, 1y.")
    return value


def window(athlete, range_key: str) -> tuple[dt.date, dt.date]:
    end = athlete.local_today
    return end - dt.timedelta(days=RANGES[range_key] - 1), end


def ranged(range_key: str, start: dt.date, end: dt.date) -> dict:
    return {"range": range_key, "start": start, "end": end}


def zone_of(athlete) -> ZoneInfo:
    try:
        return ZoneInfo(athlete.timezone or "UTC")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def metrics_rows(athlete, start: dt.date, end: dt.date) -> list:
    from apps.ingest.models import DailyMetrics

    return list(DailyMetrics.objects.filter(athlete=athlete, metric_date__gte=start,
                                            metric_date__lte=end).order_by("metric_date"))


def first_last_change(values: list, digits: int = 1):
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return None
    diff = present[-1] - present[0]
    return round(diff) if digits == 0 else round(diff, digits)
