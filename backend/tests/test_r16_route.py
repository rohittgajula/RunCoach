"""R16: GET /activities/{id}/route/?full=1 — the owner's untrimmed route."""

import pytest

from tests.test_r11_api import gps_run


@pytest.fixture(autouse=True)
def local_cache(monkeypatch):
    from django.core import cache as cache_module
    from django.core.cache.backends.locmem import LocMemCache

    local = LocMemCache("r16-route-tests", {})
    local.clear()
    monkeypatch.setattr(cache_module, "cache", local)


def test_full_route_is_untrimmed_for_the_owner(api, other_api, athlete):
    activity = gps_run(athlete)
    assert athlete.map_hide_endpoints is True
    default = api.get(f"/api/activities/{activity.pk}/route/").json()
    assert default["hidden_endpoints"] is True and default["points"][0]["dist_m"] >= 200
    full = api.get(f"/api/activities/{activity.pk}/route/", {"full": 1}).json()
    assert full["hidden_endpoints"] is False and full["trimmed_m"] == 0
    assert full["points"][0]["dist_m"] == 0
    # the default call is still trimmed afterwards (separate cache entry)
    again = api.get(f"/api/activities/{activity.pk}/route/").json()
    assert again["points"][0]["dist_m"] >= 200
    # share output keeps trimming
    share = api.get(f"/api/activities/{activity.pk}/share-data/").json()
    assert share["route"]["hidden_endpoints"] is True
    # isolation unchanged
    assert other_api.get(f"/api/activities/{activity.pk}/route/",
                         {"full": 1}).status_code == 404
