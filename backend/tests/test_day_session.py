"""Putting your own session on a day the plan had nothing on.

Rohit: "in calender i should be able to select any date even it its a run/gym
or non-training day and there i should be able to create a plan either for run
or gym either manually or using ai".

The calendar was writable in one direction only: the coach placed days, and the
athlete could move, edit or skip what it placed — but not add. A rest day was a
day with nothing to tap.

The risk in this feature is not building the session. It is that every
automatic layout pass in this app deletes what it did not place, and would
quietly eat a session the athlete put down on purpose.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.planning import day_session as service
from apps.planning.models import PlannedWorkout, StrengthSession, TrainingPlan
from tests.r7_helpers import active_plan


@pytest.fixture
def tomorrow(athlete):
    return athlete.local_today + dt.timedelta(days=1)


# --- building ----------------------------------------------------------------


@pytest.mark.django_db
def test_a_preset_is_built_by_the_same_code_as_a_planned_session(athlete):
    """An added easy run must be the same object as a generated one — the
    athlete's own bands, the same warm-up rules, the same step grid. A second
    way of writing sessions would be a second thing to keep correct."""
    session = service.build_preset(athlete, "RUN_WALK", 30)
    assert session["duration_s"] == pytest.approx(30 * 60, abs=90)
    assert session["steps"]
    assert any(s["intensity"] == "walk" for s in session["steps"])
    assert any(s["intensity"] != "walk" for s in session["steps"])


@pytest.mark.django_db
def test_a_nonsense_length_is_refused_in_words_the_athlete_can_act_on(athlete):
    with pytest.raises(service.DayError) as exc:
        service.build_preset(athlete, "EASY", 9999)
    assert "minutes" in str(exc.value)


@pytest.mark.django_db
def test_a_gym_session_keeps_the_rungs_the_athlete_is_actually_on(athlete, tomorrow):
    """Adding a gym day must not reset anybody to wall push-ups — the
    per-pattern ladders are the whole point of the programme."""
    athlete.strength_levels = {"push": 1, "squat": 4}
    athlete.save(update_fields=["strength_levels"])
    session = service.build_gym(athlete, tomorrow)
    by_pattern = {x["pattern"]: x for x in session["exercises"] if "pattern" in x}
    assert by_pattern, session["exercises"]


# --- the past is not writable -------------------------------------------------


@pytest.mark.django_db
def test_a_past_day_is_refused(athlete):
    """The past is the record of what happened. Writing a plan onto it would
    put a session the athlete never did into the history every future plan is
    built from — and it would show as 'missed' the moment it was saved."""
    yesterday = athlete.local_today - dt.timedelta(days=1)
    with pytest.raises(service.DayError):
        service.save_run(athlete, yesterday, service.build_preset(athlete, "EASY", 30))


# --- what the athlete added is theirs ----------------------------------------


@pytest.mark.django_db
def test_an_added_run_survives_accepting_a_new_plan(athlete, tomorrow):
    """The bug this feature would otherwise have shipped with.

    Accepting a plan deletes the previous plan's future sessions. A run the
    athlete put on Tuesday would have lasted exactly as long as it took to
    accept another plan, with nothing on screen saying it had gone.
    """
    from apps.planning.plan_store import accept_plan, propose_practice_plan

    active_plan(athlete)
    added = service.save_run(athlete, tomorrow, service.build_preset(athlete, "EASY", 30))

    accept_plan(propose_practice_plan(athlete))

    added.refresh_from_db()
    assert added.status == PlannedWorkout.Status.PLANNED
    assert added.date == tomorrow
    # It moved to the new plan rather than staying on the archived one, so it
    # is still on the calendar (which filters on plan status).
    assert added.plan.status == TrainingPlan.Status.ACTIVE


@pytest.mark.django_db
def test_a_generated_run_is_still_replaced_by_a_new_plan(athlete, tomorrow):
    """The branch the rule above sits in front of: the coach's own future
    sessions are exactly what accepting a new plan is supposed to replace."""
    from apps.planning.plan_store import accept_plan, propose_practice_plan

    plan = active_plan(athlete)
    generated = PlannedWorkout.objects.create(
        athlete=athlete, plan=plan, date=tomorrow, title="Coach's run",
        kind="EASY", duration_s=1800, load=30, steps=[
            {"kind": "run", "duration_s": 1800, "intensity": "easy", "label": "Run"},
        ],
    )
    accept_plan(propose_practice_plan(athlete))
    assert not PlannedWorkout.objects.filter(pk=generated.pk).exists()


@pytest.mark.django_db
def test_an_added_gym_session_survives_the_gym_relayout(athlete, tomorrow):
    """The re-layout removes sessions off days it no longer wants. One the
    athlete asked for is not its to remove."""
    from apps.planning.strength_service import place_for

    added = service.save_gym(athlete, tomorrow, service.build_gym(athlete, tomorrow))
    place_for(athlete)
    assert StrengthSession.objects.filter(pk=added.pk).exists()


# --- the API ------------------------------------------------------------------


@pytest.mark.django_db
def test_the_day_says_what_it_can_take_before_offering(api, athlete, tomorrow):
    body = api.get(f"/api/days/{tomorrow}/").json()
    assert body["writable"] is True
    assert body["has_run"] is False and body["has_gym"] is False
    assert [p["key"] for p in body["presets"]]


@pytest.mark.django_db
def test_a_past_day_reports_itself_unwritable_rather_than_failing_later(api, athlete):
    yesterday = athlete.local_today - dt.timedelta(days=1)
    body = api.get(f"/api/days/{yesterday}/").json()
    assert body["writable"] is False
    assert body["reason"]


@pytest.mark.django_db
def test_a_preview_writes_nothing(api, athlete, tomorrow):
    """A described session is a guess at what you meant, and you should read it
    before it is on your watch."""
    response = api.post(f"/api/days/{tomorrow}/preview/",
                        {"type": "run", "preset": "EASY", "minutes": 30}, format="json")
    assert response.status_code == 200
    assert response.json()["session"]["steps"]
    assert not PlannedWorkout.objects.filter(date=tomorrow).exists()


@pytest.mark.django_db
def test_creating_puts_it_on_the_day_and_marks_it_as_the_athletes(api, athlete, tomorrow):
    response = api.post(f"/api/days/{tomorrow}/create/",
                        {"type": "run", "preset": "RUN_WALK", "minutes": 30}, format="json")
    assert response.status_code == 201

    row = PlannedWorkout.objects.get(date=tomorrow)
    assert row.created_by == "user"
    assert row.steps


@pytest.mark.django_db
def test_a_gym_session_can_be_added_to_any_day(api, athlete, tomorrow):
    response = api.post(f"/api/days/{tomorrow}/create/", {"type": "gym"}, format="json")
    assert response.status_code == 201
    assert StrengthSession.objects.get(date=tomorrow).created_by == "user"


@pytest.mark.django_db
def test_a_request_with_neither_a_description_nor_a_shape_is_refused(api, tomorrow):
    response = api.post(f"/api/days/{tomorrow}/preview/", {"type": "run"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_a_bad_date_is_refused(api):
    assert api.get("/api/days/not-a-date/").status_code == 400


@pytest.mark.django_db
def test_adding_needs_a_login(client, athlete, tomorrow):
    response = client.post(f"/api/days/{tomorrow}/create/", {"type": "gym"},
                           content_type="application/json")
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_a_run_can_be_added_with_no_plan_at_all(api, athlete, tomorrow):
    """`PlannedWorkout.plan` is not nullable, so "add a run on Tuesday" must
    not require accepting sixteen weeks of training first."""
    TrainingPlan.objects.filter(athlete=athlete).delete()
    response = api.post(f"/api/days/{tomorrow}/create/",
                        {"type": "run", "preset": "EASY", "minutes": 25}, format="json")
    assert response.status_code == 201
    assert PlannedWorkout.objects.get(date=tomorrow).plan is not None


# --- planning against the days around it -------------------------------------
#
# Rohit: "if i ask you to plan for a specific day, you need to compare that
# days future runs and past runs couple of days and plan accordingly. and if
# you wanna change future runs ask for a updated on specific day i will give
# you a go or no go."


@pytest.mark.django_db
def test_the_context_carries_both_directions(athlete, tomorrow):
    """The days behind say what the legs have had; the days ahead say what they
    are being saved for. A session written against neither is the thing this
    feature would otherwise get wrong."""
    from tests.r6_helpers import make_activity
    from tests.r7_helpers import make_workout

    make_activity(athlete, athlete.local_today - dt.timedelta(days=1))
    make_workout(athlete, tomorrow + dt.timedelta(days=1))

    context = service.day_context(athlete, tomorrow)
    assert context["recent_runs"], "nothing from the days behind"
    assert context["planned_runs"], "nothing from the days ahead"
    assert any(r["offset_days"] > 0 for r in context["planned_runs"])


@pytest.mark.django_db
def test_the_context_does_not_reach_past_the_window(athlete, tomorrow):
    """Wide enough to hold the two days that matter, not thirty that do not."""
    from tests.r6_helpers import make_activity

    make_activity(athlete, athlete.local_today - dt.timedelta(days=40))
    assert service.day_context(athlete, tomorrow)["recent_runs"] == []


class _Raw:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Described:
    def __init__(self, changes):
        self.changes = changes


@pytest.mark.django_db
def test_a_proposed_change_must_name_a_session_that_exists(athlete, tomorrow):
    """A proposal naming a session that is not there is worse than no proposal:
    it is the one the athlete says yes to without being able to check."""
    changes = service._proposed_changes(athlete, tomorrow, _Described([
        _Raw(action="skip", date=(tomorrow + dt.timedelta(days=2)).isoformat(),
             minutes=None, move_to=None, why="clash"),
    ]))
    assert changes == []


@pytest.mark.django_db
def test_a_proposal_never_lands_on_the_day_being_planned(athlete, tomorrow):
    """The day being asked about is the one the athlete IS deciding. A change
    to it is not a change to another day, it is the session itself."""
    from tests.r7_helpers import make_workout

    make_workout(athlete, tomorrow)
    changes = service._proposed_changes(athlete, tomorrow, _Described([
        _Raw(action="skip", date=tomorrow.isoformat(), minutes=None,
             move_to=None, why="clash"),
    ]))
    assert changes == []


@pytest.mark.django_db
def test_easier_that_is_not_easier_is_dropped(athlete, tomorrow):
    """A no-op dressed as a change still asks the athlete a question, and the
    honest answer to it is that there was nothing to decide."""
    from tests.r7_helpers import make_workout

    later = tomorrow + dt.timedelta(days=2)
    workout = make_workout(athlete, later)
    longer = round(workout.duration_s / 60) + 10
    changes = service._proposed_changes(athlete, tomorrow, _Described([
        _Raw(action="easier", date=later.isoformat(), minutes=longer,
             move_to=None, why="clash"),
    ]))
    assert changes == []


@pytest.mark.django_db
def test_a_real_clash_becomes_one_proposal_per_day(athlete, tomorrow):
    from tests.r7_helpers import make_workout

    later = tomorrow + dt.timedelta(days=2)
    workout = make_workout(athlete, later)
    shorter = max(service.MIN_MINUTES, round(workout.duration_s / 60) - 10)
    changes = service._proposed_changes(athlete, tomorrow, _Described([
        _Raw(action="easier", date=later.isoformat(), minutes=shorter,
             move_to=None, why="You would be running hard two days running."),
    ]))
    assert len(changes) == 1
    assert changes[0]["workout_id"] == workout.pk
    assert changes[0]["why"]


@pytest.mark.django_db
def test_nothing_changes_on_another_day_without_a_yes(api, athlete, tomorrow):
    """The rule the whole feature turns on. Adding a session must not rewrite
    the week as a side effect of being added."""
    from tests.r7_helpers import make_workout

    later = tomorrow + dt.timedelta(days=2)
    other = make_workout(athlete, later)
    before = other.duration_s

    response = api.post(f"/api/days/{tomorrow}/create/",
                        {"type": "run", "preset": "EASY", "minutes": 30}, format="json")
    assert response.status_code == 201
    assert response.json()["applied_changes"] == []

    other.refresh_from_db()
    assert other.duration_s == before
    assert other.date == later
    assert other.status == PlannedWorkout.Status.PLANNED


@pytest.mark.django_db
def test_an_approved_change_is_applied_and_only_that_one(api, athlete, tomorrow):
    """Each day its own yes: ticking one must not carry the other."""
    from tests.r7_helpers import make_workout

    shorten_day = tomorrow + dt.timedelta(days=2)
    untouched_day = tomorrow + dt.timedelta(days=3)
    shorten = make_workout(athlete, shorten_day)
    untouched = make_workout(athlete, untouched_day)
    before = untouched.duration_s

    response = api.post(f"/api/days/{tomorrow}/create/", {
        "type": "run", "preset": "EASY", "minutes": 30,
        "approved_changes": [{"workout_id": shorten.pk, "action": "skip"}],
    }, format="json")
    assert response.status_code == 201
    assert len(response.json()["applied_changes"]) == 1

    shorten.refresh_from_db()
    untouched.refresh_from_db()
    assert shorten.status == PlannedWorkout.Status.SKIPPED
    assert untouched.status == PlannedWorkout.Status.PLANNED
    assert untouched.duration_s == before


@pytest.mark.django_db
def test_an_approved_change_cannot_touch_another_athletes_session(
    api, athlete, other_athlete, tomorrow,
):
    """The id comes back from the client, so it is re-checked against the
    athlete's own rows before anything happens to it."""
    from apps.planning.models import TrainingPlan

    plan = TrainingPlan.objects.create(athlete=other_athlete, name="Theirs",
                                       status="active", generator_version="g1")
    theirs = PlannedWorkout.objects.create(
        athlete=other_athlete, plan=plan, date=tomorrow + dt.timedelta(days=2),
        title="Not yours", kind="EASY", duration_s=1800, load=30,
        steps=[{"kind": "run", "duration_s": 1800, "intensity": "easy", "label": "Run"}],
    )
    response = api.post(f"/api/days/{tomorrow}/create/", {
        "type": "run", "preset": "EASY", "minutes": 30,
        "approved_changes": [{"workout_id": theirs.pk, "action": "skip"}],
    }, format="json")
    assert response.status_code == 400

    theirs.refresh_from_db()
    assert theirs.status == PlannedWorkout.Status.PLANNED


@pytest.mark.django_db
def test_a_change_is_refused_rather_than_guessed_when_the_action_is_unknown(
    api, athlete, tomorrow,
):
    from tests.r7_helpers import make_workout

    other = make_workout(athlete, tomorrow + dt.timedelta(days=2))
    response = api.post(f"/api/days/{tomorrow}/create/", {
        "type": "run", "preset": "EASY", "minutes": 30,
        "approved_changes": [{"workout_id": other.pk, "action": "lengthen"}],
    }, format="json")
    assert response.status_code == 400
