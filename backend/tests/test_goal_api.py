"""The goal mode, reachable without arguing with a chatbot.

The mode existed and had exactly one door: the coach. Rohit's way into it was
to type "5k between march and april with breaks" and hope the model picked the
right tool with the right arguments — and the right argument did not exist, so
the best possible outcome was a confident refusal of a goal he had not set.

These cover the door: both readings previewed side by side before anything is
written, the plan built from the one chosen, and the goal surviving a rebuild.
"""

from __future__ import annotations

import datetime as dt

import pytest

from apps.planning.models import TrainingPlan
from tests.r6_helpers import make_activity


@pytest.fixture
def running_history(athlete):
    """Enough real running for a history baseline rather than beginner defaults."""
    today = athlete.local_today
    for weeks_ago in range(4):
        for day_offset in (0, 3, 6):
            make_activity(
                athlete, today - dt.timedelta(weeks=weeks_ago, days=day_offset),
                run_s=900, walk_s=900, longest_s=392,
            )
    return athlete


def _body(**overrides):
    return {
        "target_distance_km": 5.0,
        "target_date": "2027-03-31",
        "style": "run_walk",
        **overrides,
    }


# --- preview ----------------------------------------------------------------


def test_the_preview_answers_both_readings_at_once(api, running_history):
    """Whichever one was asked about. The useful thing to know about "5 km by
    March" is that one reading of it is comfortable and the other is a long way
    off, and you cannot learn that from the reading you happened to pick."""
    response = api.post("/api/plans/goal/preview/", _body(), format="json")
    assert response.status_code == 200
    data = response.json()
    assert data["asked"] == "run_walk"
    assert set(data["styles"]) == {"run_walk", "nonstop"}


def test_the_preview_writes_nothing(api, running_history):
    """A refusal you only discover after a plan has been named and proposed is
    delivered too late to be useful, and a preview that leaves a plan behind is
    not a preview."""
    api.post("/api/plans/goal/preview/", _body(), format="json")
    assert TrainingPlan.objects.count() == 0


def test_each_style_reports_only_its_own_units(api, running_history):
    """Seconds of unbroken running against metres covered in one session. A
    zero in the wrong unit is the kind of plausible number that gets read by
    mistake, so the field is absent rather than empty."""
    data = api.post("/api/plans/goal/preview/", _body(), format="json").json()["styles"]
    assert "session_s" in data["run_walk"]
    assert "needs_continuous_s" not in data["run_walk"]
    assert "needs_continuous_s" in data["nonstop"]
    assert "session_s" not in data["nonstop"]


def test_a_run_walk_preview_says_how_long_the_attempt_takes(api, running_history):
    """The fact that decides whether somebody wants the goal."""
    data = api.post("/api/plans/goal/preview/", _body(), format="json").json()
    run_walk = data["styles"]["run_walk"]
    assert run_walk["session_s"] > 0
    assert run_walk["blended_pace_s_per_km"] > 0


def test_a_date_two_days_out_is_refused_rather_than_planned(api, running_history):
    tomorrow = (running_history.local_today + dt.timedelta(days=1)).isoformat()
    response = api.post("/api/plans/goal/preview/",
                        _body(target_date=tomorrow), format="json")
    assert response.status_code == 400


def test_an_unknown_style_is_refused(api, running_history):
    """The argument that decides which question is being answered must not
    fall back to a default when it is wrong."""
    response = api.post("/api/plans/goal/preview/",
                        _body(style="whatever"), format="json")
    assert response.status_code == 400


def test_the_preview_needs_a_login(client):
    response = client.post("/api/plans/goal/preview/", _body(),
                           content_type="application/json")
    assert response.status_code in (401, 403)


# --- creating ---------------------------------------------------------------


def test_creating_a_goal_leaves_a_proposal_named_for_what_was_asked(api, running_history):
    response = api.post("/api/plans/goal/", _body(), format="json")
    assert response.status_code == 201

    plan = TrainingPlan.objects.get()
    assert plan.status == TrainingPlan.Status.PROPOSED
    assert "walk breaks" in plan.name
    assert plan.summary["style"] == "run_walk"


def test_a_nonstop_goal_is_named_for_the_harder_question(api, running_history):
    api.post("/api/plans/goal/", _body(style="nonstop"), format="json")
    plan = TrainingPlan.objects.get()
    assert "without stopping" in plan.name
    assert plan.summary["style"] == "nonstop"


def test_a_proposal_does_not_reach_the_calendar(api, running_history):
    """Same rule as everywhere else here: nothing is scheduled until accepted."""
    api.post("/api/plans/goal/", _body(), format="json")
    today = running_history.local_today
    days = api.get(f"/api/calendar/?start={today}&end={today + dt.timedelta(days=20)}")
    assert days.status_code == 200
    planned = [d for d in days.json()["days"] if d.get("planned")]
    assert planned == []


def test_a_run_walk_plan_does_not_describe_itself_as_chasing_the_unbroken_block(
    api, running_history,
):
    """The shared phase copy says the unbroken block is "the number you are
    actually chasing". True of a milestone plan and of a non-stop goal, and the
    wrong quantity for somebody training to cover 5 km with walk breaks — the
    exact confusion this mode exists to remove, reappearing underneath the plan
    that removes it."""
    created = api.post("/api/plans/goal/", _body(), format="json").json()
    blurbs = " ".join(p["description"] for p in created["phases"])
    assert "unbroken block grows week by week" not in blurbs
    assert "Time on your feet" in blurbs


def test_a_nonstop_plan_keeps_the_unbroken_block_as_its_yardstick(api, running_history):
    """The branch the run-walk copy sits beside: for this goal the block really
    is the number being chased."""
    created = api.post("/api/plans/goal/", _body(style="nonstop"), format="json").json()
    blurbs = " ".join(p["description"] for p in created["phases"])
    assert "unbroken block grows week by week" in blurbs


# --- rebuilding -------------------------------------------------------------


def test_rebuilding_a_goal_plan_keeps_the_goal_and_the_style(api, running_history):
    """It did not. A goal plan has no race, and rebuild treated every race-less
    plan as a milestone plan — so pressing Rebuild turned "5 km with breaks by
    March" into an undated ladder, with nothing on screen saying the goal had
    gone."""
    created = api.post("/api/plans/goal/", _body(), format="json").json()
    api.post(f"/api/plans/{created['id']}/accept/", format="json")

    response = api.post("/api/plans/active/rebuild/", format="json")
    assert response.status_code == 200

    rebuilt = TrainingPlan.objects.get(status=TrainingPlan.Status.ACTIVE)
    assert rebuilt.summary["kind"] == "goal"
    assert rebuilt.summary["style"] == "run_walk"
    assert rebuilt.summary["target_date"] == "2027-03-31"
    assert rebuilt.summary["target_distance_km"] == 5.0


def test_a_goal_whose_date_has_passed_falls_back_rather_than_inventing_one(
    api, running_history,
):
    """Rebuilding toward yesterday is impossible and quietly moving the date
    would be setting a goal the athlete never chose."""
    created = api.post("/api/plans/goal/", _body(), format="json").json()
    api.post(f"/api/plans/{created['id']}/accept/", format="json")

    plan = TrainingPlan.objects.get(status=TrainingPlan.Status.ACTIVE)
    plan.summary = {**plan.summary, "target_date": "2026-01-01"}
    plan.save(update_fields=["summary"])

    assert api.post("/api/plans/active/rebuild/", format="json").status_code == 200
    rebuilt = TrainingPlan.objects.get(status=TrainingPlan.Status.ACTIVE)
    assert rebuilt.summary["kind"] == "practice"


def test_a_practice_plan_still_rebuilds_as_a_practice_plan(api, running_history):
    """The branch this change sits in front of."""
    from apps.planning.plan_store import accept_plan, propose_practice_plan

    accept_plan(propose_practice_plan(running_history))
    assert api.post("/api/plans/active/rebuild/", format="json").status_code == 200
    assert TrainingPlan.objects.get(
        status=TrainingPlan.Status.ACTIVE).summary["kind"] == "practice"
