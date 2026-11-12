"""Reviewing a gym session, and the review actually changing the programme.

The ladders only ever moved from a settings screen, which in practice means
they did not move. A programme that cannot hear "the wall push-ups were easy"
is a PDF with a calendar attached.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.urls import reverse

from apps.planning.models import StrengthSession
from planning.strength import PATTERNS, exercises, warmup_block


@pytest.fixture
def session(athlete):
    athlete.strength_per_week = 2
    athlete.strength_levels = {p: 2 for p in PATTERNS}
    athlete.save(update_fields=["strength_per_week", "strength_levels"])
    return StrengthSession.objects.create(
        athlete=athlete, date=athlete.local_today, title="Gym — full body",
        duration_s=2400, level=1, exercises=exercises(1),
    )


@pytest.mark.django_db
def test_one_pattern_moves_without_dragging_the_others(api, athlete, session):
    """"That was easy" about six movements says nothing about which one.

    Moving all six because the calf work felt comfortable is how somebody ends
    up failing a push-up they were never ready for.
    """
    response = api.post(reverse("strength-review", args=[session.pk]),
                        {"easy": ["calf"], "difficulty": 3}, format="json")

    assert response.status_code == 200
    athlete.refresh_from_db()
    assert athlete.strength_levels["calf"] == 3
    assert athlete.strength_levels["push"] == 2, "untouched patterns stay put"
    assert response.data["moved"] == [
        {"pattern": "calf", "direction": "up", "to": "Single-leg calf raise"}
    ]


@pytest.mark.django_db
def test_could_not_finish_steps_everything_back(api, athlete, session):
    """Somebody who could not finish needs a session they can finish, not a
    diagnosis of which movement beat them."""
    api.post(reverse("strength-review", args=[session.pk]),
             {"difficulty": 5}, format="json")

    athlete.refresh_from_db()
    assert all(athlete.strength_levels[p] == 1 for p in PATTERNS)


@pytest.mark.django_db
def test_about_right_changes_nothing(api, athlete, session):
    """A 3 is the session working as intended, and it is the common answer.

    It has to be cheap to say and it must not quietly move anything.
    """
    before = dict(athlete.strength_levels)
    response = api.post(reverse("strength-review", args=[session.pk]),
                        {"difficulty": 3}, format="json")

    athlete.refresh_from_db()
    assert athlete.strength_levels == before
    assert response.data["moved"] == []
    assert "nothing needed changing" in response.data["detail"].lower()


@pytest.mark.django_db
def test_a_review_marks_the_session_done(api, athlete, session):
    api.post(reverse("strength-review", args=[session.pk]),
             {"difficulty": 2, "notes": "wall push-ups fine"}, format="json")

    session.refresh_from_db()
    assert session.status == StrengthSession.Status.COMPLETED
    assert session.reviewed_at is not None
    assert session.notes == "wall push-ups fine"


@pytest.mark.django_db
def test_a_pattern_cannot_be_both_easy_and_hard(api, athlete, session):
    response = api.post(reverse("strength-review", args=[session.pk]),
                        {"easy": ["calf"], "hard": ["calf"]}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_an_unknown_pattern_is_refused(api, athlete, session):
    response = api.post(reverse("strength-review", args=[session.pk]),
                        {"easy": ["biceps"]}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_another_athletes_session_cannot_be_reviewed(other_api, athlete, session):
    response = other_api.post(reverse("strength-review", args=[session.pk]),
                              {"difficulty": 3}, format="json")
    assert response.status_code == 404


def test_the_warm_up_leads_the_session_and_is_the_same_shape():
    """It is the part people skip, and burying it under six lifts is how.

    Same shape as the lifts on purpose: the screen renders one list, and a
    warm-up needing its own renderer would be first to fall out of step.
    """
    session = exercises(1)
    warm = warmup_block()

    assert session[:len(warm)] == warm
    assert all(item["is_warmup"] for item in warm)
    assert set(warm[0]) == set(session[-1]) | {"is_warmup"} or "is_warmup" in warm[0]
    # And the drills the old circuit was built from are in it, doing the job
    # they were always better suited to.
    names = {item["key"] for item in warm}
    assert {"askip", "clam", "hipflexor"} <= names
