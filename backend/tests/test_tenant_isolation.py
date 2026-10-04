"""Every new endpoint refuses another athlete's objects with a 404."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.activities.models import Activity
from apps.athletes.models import MetricEntry
from apps.coaching.models import ChatThread, MemoryFact
from apps.diet.models import Meal


@pytest.fixture
def owned(athlete, proposed_plan):
    workout = proposed_plan.workouts.first()
    return {
        "plan": proposed_plan,
        "workout": workout,
        "thread": ChatThread.objects.create(athlete=athlete, title="mine"),
        "fact": MemoryFact.objects.create(athlete=athlete, text="secret"),
        "entry": MetricEntry.objects.create(athlete=athlete, kind="weight", value=70,
                                            recorded_at=timezone.now()),
        "meal": Meal.objects.create(athlete=athlete, eaten_at=timezone.now(),
                                    meal_type="lunch", items=[]),
        "activity": Activity.objects.create(athlete=athlete, source="fit_upload",
                                            started_at=timezone.now(),
                                            local_date=athlete.local_today),
    }


def test_objects_are_invisible_to_other_athletes(other_api, owned):
    o = owned
    for method, url in [
        ("get", f"/api/plans/{o['plan'].pk}/"),
        ("post", f"/api/plans/{o['plan'].pk}/accept/"),
        ("post", f"/api/plans/{o['plan'].pk}/decline/"),
        ("get", f"/api/workouts/{o['workout'].pk}/"),
        ("patch", f"/api/workouts/{o['workout'].pk}/"),
        ("post", f"/api/workouts/{o['workout'].pk}/guide/"),
        ("post", f"/api/activities/{o['activity'].pk}/review/"),
        ("patch", f"/api/chat/threads/{o['thread'].pk}/"),
        ("delete", f"/api/chat/threads/{o['thread'].pk}/"),
        ("get", f"/api/chat/threads/{o['thread'].pk}/messages/"),
        ("post", f"/api/chat/threads/{o['thread'].pk}/messages/"),
        ("delete", f"/api/memory/{o['fact'].pk}/"),
        ("delete", f"/api/metrics/entries/{o['entry'].pk}/"),
        ("patch", f"/api/diet/meals/{o['meal'].pk}/"),
        ("delete", f"/api/diet/meals/{o['meal'].pk}/"),
    ]:
        r = getattr(other_api, method)(url, {"title": "x", "content": "x", "status": "skipped"},
                                        format="json")
        assert r.status_code == 404, (method, url, r.status_code)


def test_lists_only_show_own_data(other_api, owned):
    assert other_api.get("/api/plans/").json() == []
    assert other_api.get("/api/chat/threads/").json() == []
    assert other_api.get("/api/memory/").json() == []
    assert other_api.get("/api/metrics/entries/", {"kind": "weight"}).json()["entries"] == []
    assert other_api.get("/api/diet/day/").json()["meals"] == []
    days = other_api.get("/api/calendar/").json()["days"]
    assert all(not d["items"] for d in days)


def test_attachments_to_foreign_objects_are_dropped(other_api, other_athlete, owned):
    from apps.coaching.chat import clean_attachments

    refs = [{"type": "workout", "id": owned["workout"].pk},
            {"type": "activity", "id": owned["activity"].pk}]
    assert clean_attachments(other_athlete, refs) == []


def test_unauthenticated_is_refused(client, db):
    for url in ["/api/calendar/", "/api/profile/summary/", "/api/diet/day/", "/api/plans/",
                "/api/chat/threads/", "/api/memory/"]:
        assert client.get(url).status_code == 401, url
