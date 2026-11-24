"""The comeback card: the question, and what the answer does.

The app had a journal and a morning check-in for months and neither ever asked
why he stopped. Adding a question that only recorded the reply would be adding
a survey, and a survey that changes nothing teaches the athlete to ignore the
next one — so every test here is about an answer doing something.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.planning import comeback_service as service
from apps.planning.models import TrainingPlan
from planning import comeback
from tests.r6_helpers import make_activity
from tests.r7_helpers import active_plan, make_workout


@pytest.mark.django_db
def test_a_recent_runner_is_not_asked_anything(api, athlete):
    make_activity(athlete, athlete.local_today - dt.timedelta(days=1))
    body = api.get("/api/today/comeback/").json()
    assert body["gap"] is None
    assert body["return"] is None


@pytest.mark.django_db
def test_a_fortnight_of_silence_gets_the_question(api, athlete):
    make_activity(athlete, athlete.local_today - dt.timedelta(days=13))
    body = api.get("/api/today/comeback/").json()
    assert body["gap"]["days"] == 13
    assert {a["key"] for a in body["gap"]["answers"]} == {"hurt", "much", "life"}


@pytest.mark.django_db
def test_the_week_is_always_there_gap_or_no_gap(api, athlete):
    """A week is a week. The floor does not disappear because he ran."""
    make_activity(athlete, athlete.local_today - dt.timedelta(days=1))
    body = api.get("/api/today/comeback/").json()
    assert body["week"]["floor"] >= comeback.FLOOR_MIN
    assert body["week"]["line"]


@pytest.mark.django_db
def test_the_floor_counts_the_weeks_he_missed(athlete):
    """A man who ran in one of the last six weeks has a floor of one, not of
    whatever he managed in the week he showed up."""
    today = athlete.local_today
    monday = today - dt.timedelta(days=today.weekday())
    # Three runs inside this week, whatever weekday the test runs on.
    for offset in range(3):
        make_activity(athlete, monday + dt.timedelta(days=offset))

    counts = service._weekly_counts(athlete, today)
    assert len(counts) == comeback.FLOOR_WEEKS
    assert counts[-1] == 3, counts
    assert counts[:-1] == [0] * (comeback.FLOOR_WEEKS - 1), counts
    # Five empty weeks and one good one is a floor of one, not of three.
    assert comeback.week_floor(counts) == comeback.FLOOR_MIN


# --- the answers do something -------------------------------------------------


@pytest.mark.django_db
def test_too_much_rebuilds_the_weeks_ahead(api, athlete):
    from tests.r7_helpers import tomorrow

    active_plan(athlete)
    # Barely any running, against a week the plan still wants in full. The
    # cascade only shrinks a plan that is bigger than the athlete — on the
    # first version of this test it correctly did nothing, because 720 s
    # planned against 750 s actually run is not a plan that needs shrinking.
    make_activity(athlete, athlete.local_today - dt.timedelta(days=13), run_s=240)
    for days in (2, 4, 6, 8):
        make_workout(athlete, athlete.local_today - dt.timedelta(days=days))
    future = make_workout(athlete, tomorrow(athlete, 9))
    before = future.duration_s

    response = api.post("/api/today/comeback/answer/", {"key": "much"}, format="json")
    assert response.status_code == 200
    assert response.json()["action"] == "shrink"

    future.refresh_from_db()
    assert future.duration_s < before


@pytest.mark.django_db
def test_life_got_in_the_way_changes_nothing(api, athlete):
    """Nothing is the honest answer to "life got in the way", and the card has
    to be willing to give it."""
    from tests.r7_helpers import tomorrow

    active_plan(athlete)
    make_activity(athlete, athlete.local_today - dt.timedelta(days=13))
    future = make_workout(athlete, tomorrow(athlete, 3))
    before = future.duration_s

    assert api.post("/api/today/comeback/answer/",
                    {"key": "life"}, format="json").json()["action"] == "nothing"
    future.refresh_from_db()
    assert future.duration_s == before


@pytest.mark.django_db
def test_something_hurts_routes_to_the_screen_that_asks_properly(api, athlete):
    """Illness mode asks what is wrong and for how long. Guessing those on the
    athlete's behalf would put the plan into a state they did not choose."""
    make_activity(athlete, athlete.local_today - dt.timedelta(days=13))
    body = api.post("/api/today/comeback/answer/", {"key": "hurt"}, format="json").json()
    assert body["action"] == "illness"
    assert body["result"]["go_to"] == "/health/illness"


@pytest.mark.django_db
def test_answering_quietens_the_card_rather_than_asking_again_tomorrow(api, athlete):
    """An honest "life got in the way" must not be punished with the same
    question every morning."""
    make_activity(athlete, athlete.local_today - dt.timedelta(days=13))
    assert api.get("/api/today/comeback/").json()["gap"] is not None

    api.post("/api/today/comeback/answer/", {"key": "life"}, format="json")
    assert api.get("/api/today/comeback/").json()["gap"] is None


@pytest.mark.django_db
def test_a_gap_that_carries_on_is_asked_about_again_eventually(api, athlete):
    make_activity(athlete, athlete.local_today - dt.timedelta(days=13))
    api.post("/api/today/comeback/answer/", {"key": "life"}, format="json")

    athlete.ui_state = {
        service.MARKER: (athlete.local_today
                         - dt.timedelta(days=service.QUIET_DAYS + 1)).isoformat(),
    }
    athlete.save(update_fields=["ui_state"])
    assert api.get("/api/today/comeback/").json()["gap"] is not None


@pytest.mark.django_db
def test_an_invented_answer_is_refused(api, athlete):
    assert api.post("/api/today/comeback/answer/",
                    {"key": "whatever"}, format="json").status_code == 400


@pytest.mark.django_db
def test_the_card_needs_a_login(client):
    assert client.get("/api/today/comeback/").status_code in (401, 403)


@pytest.mark.django_db
def test_a_long_gap_offers_starting_again(api, athlete):
    make_activity(athlete, athlete.local_today - dt.timedelta(days=40))
    body = api.get("/api/today/comeback/").json()
    assert body["gap"]["long"] is True
    assert "restart" in {a["key"] for a in body["gap"]["answers"]}


@pytest.mark.django_db
def test_starting_again_leaves_exactly_one_active_plan(api, athlete):
    active_plan(athlete)
    make_activity(athlete, athlete.local_today - dt.timedelta(days=40))

    body = api.post("/api/today/comeback/answer/", {"key": "restart"}, format="json").json()
    assert body["action"] == "restart"
    assert TrainingPlan.objects.filter(
        athlete=athlete, status=TrainingPlan.Status.ACTIVE).count() == 1
