"""Noticing that the watch stopped talking.

Rohit's Garmin session died on 10 October. For five weeks Today showed a plan
built on October data, the coach answered with full confidence, and his 5 km
projection was computed from a watch that had stopped reporting. Nothing was
wrong with any individual number; all of them were simply old, and nothing said
so.

Being wrong quietly is worse than being disconnected, and that is what these
tests are for.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from analysis.freshness import SYNC_QUIET_HOURS, SYNC_STALE_DAYS, sync_verdict

TODAY = dt.date(2026, 11, 12)
NOW = dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.timezone.utc)


def verdict(**overrides):
    base = dict(
        today=TODAY, connected=True, now=NOW,
        last_sync_at=NOW - dt.timedelta(hours=3),
        last_activity_date=TODAY - dt.timedelta(days=1),
    )
    return sync_verdict(**{**base, **overrides})


def test_a_disconnected_watch_is_always_broken_however_recent_the_last_sync():
    """Severity is about consequence, not duration.

    A watch disconnected two hours ago is already broken, because nothing more
    will arrive until somebody acts. Grading this by elapsed time would stay
    quiet for two days about a problem that is total from the first minute.
    """
    result = verdict(connected=False, last_sync_at=NOW - dt.timedelta(hours=2))
    assert result["level"] == "broken"
    assert result["action"] == "reconnect"
    assert "disconnected" in result["headline"].lower()


def test_rohits_actual_situation_reads_as_broken_and_names_the_date():
    """The exact case this was built for."""
    result = sync_verdict(
        today=TODAY, connected=False, now=NOW,
        last_sync_at=dt.datetime(2026, 10, 10, 8, 44, tzinfo=dt.timezone.utc),
        last_activity_date=dt.date(2026, 10, 9),
    )
    assert result["level"] == "broken"
    assert "10 October" in result["detail"]
    assert result["days_since_activity"] == 34
    # It must say the screen is affected, not merely that a sync failed.
    assert "computed from" in result["detail"]


def test_a_quiet_night_is_not_a_banner():
    """People have rest days. A watch that synced this morning is fine."""
    assert verdict()["level"] == "ok"
    assert verdict()["headline"] == ""


def test_silence_becomes_worth_mentioning_then_worth_worrying_about():
    quiet = verdict(last_sync_at=NOW - dt.timedelta(hours=SYNC_QUIET_HOURS + 6))
    assert quiet["level"] == "quiet"
    assert quiet["action"] == "sync"

    stale = verdict(last_sync_at=NOW - dt.timedelta(days=SYNC_STALE_DAYS + 2))
    assert stale["level"] == "stale"
    # Past a week it is the PLAN that is suspect, not just the dashboard.
    assert "plan" in stale["detail"].lower()


def test_never_synced_does_not_crash_or_cry_wolf():
    """A brand-new athlete has no last sync and no activities."""
    result = sync_verdict(today=TODAY, connected=True, now=NOW,
                          last_sync_at=None, last_activity_date=None)
    assert result["level"] == "ok"
    assert result["days_since_activity"] is None


@pytest.mark.django_db
def test_today_carries_the_verdict(api, athlete):
    """It has to reach the screen, not just exist."""
    from django.urls import reverse

    athlete.garmin_connected = False
    athlete.garmin_last_sync = timezone.now() - dt.timedelta(days=33)
    athlete.save(update_fields=["garmin_connected", "garmin_last_sync"])

    response = api.get(reverse("today"))
    assert response.status_code == 200
    sync = response.data["freshness"]["sync"]
    assert sync["level"] == "broken"
    assert sync["action"] == "reconnect"


@pytest.mark.django_db
def test_the_coach_is_told_when_its_figures_are_old(athlete):
    """A model cannot caveat what it has not been told.

    Every number the coach was given was real. None of it was current, and it
    had no way to know — so it answered with confidence about a picture five
    weeks out of date.
    """
    from apps.coaching.chat import system_prompt

    athlete.garmin_connected = False
    athlete.garmin_last_sync = timezone.now() - dt.timedelta(days=33)
    athlete.save(update_fields=["garmin_connected", "garmin_last_sync"])

    prompt = system_prompt(athlete)
    assert "data_is_stale" in prompt
    assert "Do not present these figures as current" in prompt


@pytest.mark.django_db
def test_a_healthy_connection_adds_nothing_to_the_prompt(athlete):
    """No warning, and no tokens spent saying there is no warning."""
    from apps.coaching.chat import system_prompt

    athlete.garmin_connected = True
    athlete.garmin_last_sync = timezone.now()
    athlete.save(update_fields=["garmin_connected", "garmin_last_sync"])

    assert "data_is_stale" not in system_prompt(athlete)
