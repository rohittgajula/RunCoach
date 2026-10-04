"""docs/DEPLOY.md §2.3: throttles per real client IP, all 429 {detail}."""

import pytest
from rest_framework.test import APIClient

LOGIN = "/api/auth/login/"
REGISTER = "/api/auth/register/"
REFRESH = "/api/auth/refresh/"
CONNECT = "/api/garmin/connect/"


def hammer(client, url, n, **extra):
    return [client.post(url, {}, format="json", **extra).status_code for _ in range(n)]


@pytest.mark.django_db
def test_rates_match_the_contract(settings):
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert rates["login"] == "10/min"
    assert rates["register"] == "5/hour"
    assert rates["refresh"] == "60/min"
    assert rates["garmin_connect"] == "5/hour"
    assert rates["chat"] == "150/day"


@pytest.mark.django_db
def test_login_throttles_at_ten_per_minute():
    client = APIClient()
    codes = hammer(client, LOGIN, 11)
    assert codes[:10] == [400] * 10
    assert codes[10] == 429
    assert "detail" in client.post(LOGIN, {}, format="json").json()


@pytest.mark.django_db
def test_register_throttles_at_five_per_hour(settings):
    settings.REGISTRATION_MODE = "open"
    codes = hammer(APIClient(), REGISTER, 6)
    assert codes[5] == 429 and 429 not in codes[:5]


@pytest.mark.django_db
def test_refresh_throttles_at_sixty_per_minute():
    codes = hammer(APIClient(), REFRESH, 61)
    assert codes[:60] == [401] * 60
    assert codes[60] == 429


@pytest.mark.django_db
def test_garmin_connect_is_per_ip_not_per_user(api, other_api):
    """Five attempts from one address, whichever accounts they come from."""
    codes = hammer(api, CONNECT, 3) + hammer(other_api, CONNECT, 3)
    assert codes[:5] == [400] * 5  # missing credentials; never reaches Garmin
    assert codes[5] == 429


@pytest.mark.django_db
def test_class_scoped_throttles_actually_apply(monkeypatch, api):
    """ChatThrottle on @api_view functions used to be inert: ScopedRateThrottle
    only read view.throttle_scope, which a function view never has."""
    from rest_framework.throttling import SimpleRateThrottle

    # The rates dict is bound at import, so patch it rather than settings.
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "chat", "2/day")
    codes = [api.post("/api/diet/meals/estimate/", {}, format="multipart").status_code
             for _ in range(3)]
    assert 429 not in codes[:2] and codes[2] == 429


@pytest.mark.django_db
def test_cf_connecting_ip_separates_clients_when_trusted(settings):
    settings.TRUST_CF_CONNECTING_IP = True
    client = APIClient()
    a = hammer(client, LOGIN, 11, HTTP_CF_CONNECTING_IP="203.0.113.5")
    b = hammer(client, LOGIN, 1, HTTP_CF_CONNECTING_IP="198.51.100.7")
    assert a[10] == 429
    assert b == [400]


@pytest.mark.django_db
def test_cf_connecting_ip_is_ignored_when_not_trusted(settings):
    settings.TRUST_CF_CONNECTING_IP = False
    client = APIClient()
    hammer(client, LOGIN, 10, HTTP_CF_CONNECTING_IP="203.0.113.5")
    assert hammer(client, LOGIN, 1, HTTP_CF_CONNECTING_IP="198.51.100.7") == [429]


@pytest.mark.django_db
def test_x_forwarded_for_cannot_reset_the_counter():
    client = APIClient()
    hammer(client, LOGIN, 10, HTTP_X_FORWARDED_FOR="1.1.1.1")
    assert hammer(client, LOGIN, 1, HTTP_X_FORWARDED_FOR="2.2.2.2") == [429]


def test_middleware_ignores_garbage_header(settings, rf):
    from config.middleware import RealClientIPMiddleware

    settings.TRUST_CF_CONNECTING_IP = True
    seen = {}
    mw = RealClientIPMiddleware(lambda r: seen.setdefault("ip", r.META["REMOTE_ADDR"]))
    mw(rf.get("/", HTTP_CF_CONNECTING_IP="not-an-ip", REMOTE_ADDR="10.0.0.1"))
    assert seen["ip"] == "10.0.0.1"
    seen.clear()
    mw(rf.get("/", HTTP_CF_CONNECTING_IP="2001:db8::1", REMOTE_ADDR="10.0.0.1"))
    assert seen["ip"] == "2001:db8::1"
