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


@pytest.fixture(autouse=True)
def no_real_model_list(monkeypatch):
    """R15: the providers' models.list() is never called from tests (it fails like an
    outage unless a test patches `_fetch_ids`), the list cache is per test, the backoff
    never really sleeps, and "Check models" runs inline instead of on the broker."""
    from django.core.cache.backends.locmem import LocMemCache

    from apps.coaching import client as ai_client
    from apps.coaching import model_list, tasks as coaching_tasks

    def offline(provider):
        raise RuntimeError("network disabled in tests")

    cache = LocMemCache("model-list-tests", {})
    cache.clear()
    monkeypatch.setattr(model_list, "_fetch_ids", offline)
    monkeypatch.setattr(model_list, "cache", cache)
    slept: list = []
    monkeypatch.setattr(ai_client, "_sleep", slept.append)
    monkeypatch.setattr(coaching_tasks.check_models, "delay",
                        lambda provider, models: coaching_tasks.check_models.run(provider,
                                                                                 models))
    return slept


@pytest.fixture(autouse=True)
def fake_ai_models(settings):
    """Tests never depend on the machine's AI configuration.

    CI has no model ids in its environment; a developer's .env has real ones. Code
    that resolves a model before calling the (mocked) client then behaved differently
    in the two places — green locally, 503 in CI. Every test gets the same fake tiers;
    a test about "no model configured" sets settings.AI_MODELS itself.
    """
    settings.AI_MODELS = {"lite": "test-model", "fast": "test-model",
                          "coach": "test-model", "deep": "test-model"}


@pytest.fixture(autouse=True)
def no_real_garmin_queue(monkeypatch):
    """R11: the Garmin tasks queued after a sync (slow + intraday fetch) and by the
    backfill command never reach the real broker from a test — the dev stack's garmin
    worker would run them against the dev database. Queued calls are recorded instead."""
    from apps.ingest import tasks

    queued: list = []

    def recorder(name):
        def apply_async(args=(), kwargs=None, countdown=0, **kw):
            queued.append((name, tuple(args), dict(kwargs or {}), countdown))
        return apply_async

    for name in ("sync_slow_one", "sync_intraday_one", "backfill_intraday", "backfill_r10"):
        monkeypatch.setattr(getattr(tasks, name), "apply_async", recorder(name))
    return queued


@pytest.fixture(autouse=True)
def no_real_r13_queue(monkeypatch):
    """R13: the follow-up tasks queued after a run, a check-in, a pain report, a strength
    push or an export request never reach the real broker from a test (the dev stack's
    workers would run them against the dev database). Queued calls are recorded; tests
    call the services directly or run `.apply()` themselves."""
    from apps.athletes import tasks as athlete_tasks
    from apps.health import tasks as health_tasks
    from apps.planning import tasks as planning_tasks

    queued: list = []

    def recorder(name):
        def delay(*args, **kwargs):
            queued.append((name, args, kwargs))

        def apply_async(args=(), kwargs=None, **kw):
            queued.append((name, tuple(args), dict(kwargs or {})))
        return delay, apply_async

    for module, name in ((planning_tasks, "after_run_task"),
                         (planning_tasks, "after_checkin_task"),
                         (planning_tasks, "after_pain_task"),
                         (planning_tasks, "garmin_strength_push_task"),
                         (athlete_tasks, "build_export"),
                         # R14
                         (health_tasks, "heart_weather_task"),
                         (planning_tasks, "weather_check_task")):
        delay, apply_async = recorder(name)
        task = getattr(module, name)
        monkeypatch.setattr(task, "delay", delay)
        monkeypatch.setattr(task, "apply_async", apply_async)
    return queued


@pytest.fixture(autouse=True)
def isolated_sync_cache(monkeypatch):
    """R16 §C: the per-athlete sync lock / last-attempt keys live in a fresh in-memory
    cache per test, never the shared Redis the dev stack's athletes use."""
    from django.core.cache.backends.locmem import LocMemCache

    from apps.ingest import sync_status

    cache = LocMemCache("sync-status-tests", {})
    cache.clear()
    monkeypatch.setattr(sync_status, "cache", cache)
    return cache
