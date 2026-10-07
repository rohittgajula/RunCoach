"""docs/DEPLOY.md §2.5: DELETE /api/auth/me/ removes the account, its rows, its files
and its sessions."""

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.athletes.models import Athlete
from apps.diet.models import Meal
from apps.ingest.models import RawFitFile

ME = "/api/auth/me/"
PASSWORD = "correct-horse-battery-1"  # conftest's athlete


@pytest.fixture(autouse=True)
def disk(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.GARMIN_TOKEN_DIR = str(tmp_path / "garmin")
    settings.MEDIA_ROOT.mkdir()
    return tmp_path


def make_files(athlete):
    fit = RawFitFile(athlete=athlete, original_name="run.fit", sha256="a" * 64, size_bytes=3)
    fit.file.save("run.fit", ContentFile(b"FIT"), save=True)
    meal = Meal(athlete=athlete, eaten_at=timezone.now(), local_date=athlete.local_today,
                meal_type="lunch", items=[])
    meal.photo.save("lunch.jpg", ContentFile(b"\xff\xd8jpeg"), save=True)
    from pathlib import Path

    tokens = Path(athlete.token_dir)
    tokens.mkdir(parents=True)
    (tokens / "garmin_tokens.json").write_text("{}")
    return Path(fit.file.path), Path(meal.photo.path), tokens


@pytest.mark.django_db
def test_wrong_password_deletes_nothing(api, athlete):
    response = api.delete(ME, {"password": "nope"}, format="json")
    assert response.status_code == 400
    assert "detail" in response.json()
    assert api.delete(ME, {}, format="json").status_code == 400
    assert User.objects.filter(pk=athlete.user_id).exists()


@pytest.mark.django_db
def test_deletion_removes_rows_files_and_tokens(api, athlete, other_athlete):
    fit, photo, tokens = make_files(athlete)
    other_fit, other_photo, other_tokens = make_files(other_athlete)
    refresh = RefreshToken.for_user(athlete.user)  # a signed-in device
    assert fit.exists() and photo.exists() and tokens.exists()

    response = api.delete(ME, {"password": PASSWORD}, format="json")
    assert response.status_code == 204
    assert response.cookies["refresh_token"].value == ""

    assert not User.objects.filter(username="tester").exists()
    assert not Athlete.objects.filter(pk=athlete.pk).exists()
    assert not Meal.objects.filter(athlete_id=athlete.pk).exists()
    assert not RawFitFile.objects.filter(athlete_id=athlete.pk).exists()
    assert not fit.exists() and not photo.exists() and not tokens.exists()
    assert BlacklistedToken.objects.filter(token__jti=refresh["jti"]).exists()

    # The other athlete is untouched, on disk too.
    assert other_fit.exists() and other_photo.exists() and other_tokens.exists()
    assert Athlete.objects.filter(pk=other_athlete.pk).exists()


@pytest.mark.django_db
def test_refresh_token_is_dead_after_deletion(client):
    """End to end through the real endpoints: register, delete, try to refresh."""
    from django.test import override_settings

    with override_settings(REGISTRATION_MODE="open"):
        r = client.post("/api/auth/register/", {"username": "gone", "password": PASSWORD},
                        content_type="application/json")
    assert r.status_code == 201
    access = r.json()["access"]
    old_refresh = r.cookies["refresh_token"].value
    r = client.delete(ME, {"password": PASSWORD}, content_type="application/json",
                      HTTP_AUTHORIZATION=f"Bearer {access}")
    assert r.status_code == 204
    # The response cleared the cookie; replay the old token as a stolen copy would.
    client.cookies["refresh_token"] = old_refresh
    assert client.post("/api/auth/refresh/").status_code == 401


@pytest.mark.django_db
def test_deletion_requires_authentication(client):
    assert client.delete(ME, {"password": "x"}, content_type="application/json").status_code == 401


def test_deletion_removes_habit_logs_and_location(api, athlete, other_athlete):
    """R8: HabitLog rows and the stored location go with the account."""
    from apps.habits.models import HabitLog

    Athlete.objects.filter(pk=athlete.pk).update(location_lat=17.39, location_lon=78.49,
                                                  location_name="Hyderabad",
                                                  location_source="city")
    for who in (athlete, other_athlete):
        HabitLog.objects.create(athlete=who, kind="smoke", at=timezone.now(), quantity=2)
    assert api.delete(ME, {"password": PASSWORD}, format="json").status_code == 204
    assert not HabitLog.objects.filter(athlete_id=athlete.pk).exists()
    assert not Athlete.objects.filter(location_lat=17.39, location_lon=78.49).exists()
    assert HabitLog.objects.filter(athlete=other_athlete).count() == 1
