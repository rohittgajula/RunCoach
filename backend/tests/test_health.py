import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_reports_both_dependencies(client):
    response = client.get(reverse("health"))
    body = response.json()

    assert response.status_code == 200, body
    assert body == {"status": "ok", "db": True, "redis": True}


def test_liveness_needs_no_dependencies(client, monkeypatch):
    """Liveness must not touch the db or Redis — an outage there is a readiness
    failure (stop routing), not a reason to restart the pod."""
    from config import health

    def boom():
        raise AssertionError("liveness touched a dependency")

    monkeypatch.setattr(health, "_check_db", boom)
    monkeypatch.setattr(health, "_check_redis", boom)
    response = client.get(reverse("health-live"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_probes_answer_any_host_header(client, settings):
    """kubelet probes use Host=<pod IP>, which ALLOWED_HOSTS rejects for real pages."""
    settings.ALLOWED_HOSTS = ["runcoach.example.com"]
    assert client.get("/api/health/live/", HTTP_HOST="10.42.0.7:8000").status_code == 200
    assert client.get("/api/health/", HTTP_HOST="10.42.0.7:8000").status_code == 200
    assert client.get("/api/auth/registration/", HTTP_HOST="10.42.0.7:8000").status_code == 400
