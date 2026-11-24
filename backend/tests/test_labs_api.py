"""Storing a blood panel and reading it back."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.health.models import LabPanel


def panel(**over):
    return {
        "taken_on": "2026-11-20",
        "lab": "Thyrocare",
        "readings": [
            {"key": "ferritin", "value": 18},
            {"key": "hemoglobin", "value": 14.2},
            {"key": "tsh", "value": 2.1, "ref_low": 0.5, "ref_high": 5.5},
        ],
        **over,
    }


@pytest.mark.django_db
def test_a_panel_is_stored_and_read_back_with_its_flags(api, athlete):
    created = api.post("/api/labs/", panel(), format="json")
    assert created.status_code == 201
    body = created.json()
    assert "Ferritin" in body["headline"]

    by_key = {r["key"]: r for r in body["readings"]}
    assert by_key["ferritin"]["flagged"] is True
    assert by_key["tsh"]["range_source"] == "lab"
    assert by_key["hemoglobin"]["flagged"] is False


@pytest.mark.django_db
def test_the_standing_note_is_on_the_list_as_well_as_the_panel(api, athlete):
    api.post("/api/labs/", panel(), format="json")
    body = api.get("/api/labs/").json()
    assert "not a diagnosis" in body["standing_note"].lower()
    assert "not a diagnosis" in body["panels"][0]["standing_note"].lower()


@pytest.mark.django_db
def test_a_marker_measured_twice_becomes_a_trend(api, athlete):
    """One ferritin reading says much less than three of them do."""
    api.post("/api/labs/", panel(taken_on="2026-05-01"), format="json")
    api.post("/api/labs/", panel(taken_on="2026-11-20"), format="json")

    trends = api.get("/api/labs/").json()["trends"]
    assert len(trends["ferritin"]) == 2
    # Oldest first, so it reads as movement.
    assert trends["ferritin"][0]["taken_on"] < trends["ferritin"][1]["taken_on"]


@pytest.mark.django_db
def test_a_single_reading_is_not_a_trend(api, athlete):
    api.post("/api/labs/", panel(), format="json")
    assert "ferritin" not in api.get("/api/labs/").json()["trends"]


@pytest.mark.django_db
def test_an_unknown_marker_is_refused(api, athlete):
    assert api.post("/api/labs/", panel(readings=[{"key": "vibes", "value": 1}]),
                    format="json").status_code == 400


@pytest.mark.django_db
def test_the_same_marker_twice_in_one_panel_is_refused(api, athlete):
    body = panel(readings=[{"key": "ferritin", "value": 18},
                           {"key": "ferritin", "value": 22}])
    assert api.post("/api/labs/", body, format="json").status_code == 400


@pytest.mark.django_db
def test_an_empty_panel_is_refused(api, athlete):
    assert api.post("/api/labs/", panel(readings=[]), format="json").status_code == 400


@pytest.mark.django_db
def test_a_future_test_date_is_refused(api, athlete):
    ahead = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    assert api.post("/api/labs/", panel(taken_on=ahead), format="json").status_code == 400


@pytest.mark.django_db
def test_a_panel_can_be_deleted(api, athlete):
    pk = api.post("/api/labs/", panel(), format="json").json()["id"]
    assert api.delete(f"/api/labs/{pk}/").status_code == 204
    assert LabPanel.objects.filter(pk=pk).count() == 0


@pytest.mark.django_db
def test_one_athlete_cannot_see_or_delete_anothers(api, athlete, other_athlete):
    mine = api.post("/api/labs/", panel(), format="json").json()["id"]
    theirs = LabPanel.objects.create(athlete=other_athlete, taken_on=dt.date(2026, 1, 1))

    listed = {p["id"] for p in api.get("/api/labs/").json()["panels"]}
    assert listed == {mine}
    assert api.delete(f"/api/labs/{theirs.pk}/").status_code == 404
    assert LabPanel.objects.filter(pk=theirs.pk).exists()


@pytest.mark.django_db
def test_labs_need_a_login(client):
    assert client.get("/api/labs/").status_code in (401, 403)


@pytest.mark.django_db
def test_the_marker_list_puts_the_runner_ones_first(api, athlete):
    markers = api.get("/api/labs/markers/").json()["markers"]
    assert markers[0]["runner_key"] is True
    assert not markers[-1]["runner_key"]
