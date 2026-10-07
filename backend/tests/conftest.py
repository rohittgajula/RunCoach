import pytest
from django.contrib.auth.models import User

from apps.athletes.models import Athlete


@pytest.fixture
def athlete(db):
    user = User.objects.create_user("tester", password="correct-horse-battery-1")
    return Athlete.objects.create(
        user=user, display_name="Tester", timezone="Asia/Kolkata"
    )


@pytest.fixture
def api(athlete):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(athlete.user)
    return client


@pytest.fixture
def other_athlete(db):
    user = User.objects.create_user("intruder", password="correct-horse-battery-2")
    return Athlete.objects.create(user=user, display_name="Intruder", timezone="UTC")


@pytest.fixture
def other_api(other_athlete):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(other_athlete.user)
    return client


@pytest.fixture
def proposed_plan(athlete):
    """A 10 km plan, 10 weeks out, proposed but not accepted."""
    import datetime as dt

    from apps.planning.plan_store import propose_plan

    return propose_plan(
        athlete, race_name="Test 10K",
        race_date=athlete.local_today + dt.timedelta(weeks=10), distance_km=10.0,
    )


@pytest.fixture(autouse=True)
def isolated_throttle_cache(monkeypatch):
    """Throttle counters in a fresh in-memory cache per test.

    The real cache is the shared Redis, so counters from one test run (or the dev
    server) leaked into the next and the register throttle started 429ing test_auth
    when the whole suite ran. Flushing Redis instead would also wipe the Garmin circuit
    breaker, which is worse.
    """
    from django.core.cache.backends.locmem import LocMemCache
    from rest_framework.throttling import SimpleRateThrottle

    # LocMemCache instances with the same name share storage, so clear it explicitly.
    cache = LocMemCache("throttle-tests", {})
    cache.clear()
    monkeypatch.setattr(SimpleRateThrottle, "cache", cache)


@pytest.fixture(autouse=True)
def no_real_weather(monkeypatch):
    """R8 §D: Open-Meteo is never called from tests. Every weather fetch fails (an
    outage) unless a test patches `apps.ingest.weather._get_json` itself, and the
    weather / progress caches are a fresh in-memory cache per test (never the shared
    Redis the dev server uses)."""
    from django.core.cache.backends.locmem import LocMemCache

    from apps.ingest import weather

    def offline(url, params):
        raise weather.WeatherUnavailable("network disabled in tests")

    cache = LocMemCache("weather-tests", {})
    cache.clear()
    monkeypatch.setattr(weather, "_get_json", offline)
    monkeypatch.setattr(weather, "cache", cache)
    from apps.activities import progress

    monkeypatch.setattr(progress, "cache", cache)
    return cache
