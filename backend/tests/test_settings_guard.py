"""docs/DEPLOY.md §1: the env contract and the startup guard."""

import secrets

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.security import (
    DEV_SECRET_KEY, check_production_settings, production_problems,
    resolve_registration_mode,
)

GOOD_KEY = secrets.token_urlsafe(64)
HOSTS = ["runcoach.rohitgajula.in"]


def test_debug_accepts_the_dev_key():
    check_production_settings(True, DEV_SECRET_KEY, ["*"])


@pytest.mark.parametrize("key", [None, "", DEV_SECRET_KEY, "short-key", "a" * 80,
                                 "django-insecure-" + "x1y2z3" * 10])
def test_production_refuses_a_weak_key(key):
    with pytest.raises(ImproperlyConfigured):
        check_production_settings(False, key, HOSTS)


def test_production_refuses_wildcard_hosts():
    assert production_problems(False, GOOD_KEY, ["*"])
    assert production_problems(False, GOOD_KEY, [])


def test_production_accepts_a_real_key_and_host():
    check_production_settings(False, GOOD_KEY, HOSTS)


@pytest.mark.parametrize("value,debug,expected", [
    (None, True, "open"), (None, False, "invite"), ("", False, "invite"),
    ("closed", True, "closed"), ("OPEN", False, "open"), (" invite ", True, "invite"),
    ("bogus", True, "closed"),  # unknown fails closed, not open
])
def test_registration_mode(value, debug, expected):
    assert resolve_registration_mode(value, debug) == expected


def test_settings_module_refuses_to_load_in_production_with_dev_key():
    """The guard is actually wired into settings.py, not just defined."""
    import os
    import subprocess
    import sys

    env = {**os.environ, "DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": DEV_SECRET_KEY,
           "DJANGO_ALLOWED_HOSTS": "runcoach.rohitgajula.in"}
    code = "import config.settings"
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                            text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr

    env["DJANGO_SECRET_KEY"] = GOOD_KEY
    env["DJANGO_SECURE"] = "1"
    code = ("import config.settings as s; assert not s.DEBUG; "
            "assert s.SECURE_HSTS_SECONDS == 31536000 and s.SESSION_COOKIE_SECURE; "
            "assert s.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https'); "
            "assert not getattr(s, 'SECURE_SSL_REDIRECT', False); "
            "assert s.REGISTRATION_MODE == 'invite'; "
            "assert 'Manifest' in s.STORAGES['staticfiles']['BACKEND']")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                            text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert result.returncode == 0, result.stderr


def test_whitenoise_sits_right_after_security_middleware():
    from django.conf import settings

    mw = settings.MIDDLEWARE
    assert mw.index("whitenoise.middleware.WhiteNoiseMiddleware") == (
        mw.index("django.middleware.security.SecurityMiddleware") + 1
    )
