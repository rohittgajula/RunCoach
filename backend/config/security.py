"""Startup checks for the environment contract (docs/DEPLOY.md §1).

Plain functions with no Django imports beyond the exception, so settings.py can call
them while it is still loading and the tests can call them with any inputs.
"""

from django.core.exceptions import ImproperlyConfigured

DEV_SECRET_KEY = "dev-insecure-key-change-me"
MIN_SECRET_KEY_LENGTH = 50
REGISTRATION_MODES = ("open", "invite", "closed")


def production_problems(debug: bool, secret_key: str | None, allowed_hosts: list[str]) -> list[str]:
    """Everything wrong with these settings for DEBUG=0. Empty in DEBUG."""
    if debug:
        return []
    problems = []
    key = secret_key or ""
    if not key:
        problems.append("DJANGO_SECRET_KEY is not set.")
    elif key == DEV_SECRET_KEY or key.startswith("django-insecure"):
        problems.append("DJANGO_SECRET_KEY is the development default.")
    elif len(key) < MIN_SECRET_KEY_LENGTH or len(set(key)) < 5:
        problems.append(
            f"DJANGO_SECRET_KEY is too short or too repetitive "
            f"(need {MIN_SECRET_KEY_LENGTH}+ random characters)."
        )
    hosts = [h for h in allowed_hosts if h.strip()]
    if not hosts or "*" in hosts:
        problems.append("DJANGO_ALLOWED_HOSTS must name the real host(s), not '*'.")
    return problems


def check_production_settings(debug: bool, secret_key: str | None, allowed_hosts: list[str]) -> None:
    """Refuse to start a non-DEBUG process with a forgeable key or open host header."""
    problems = production_problems(debug, secret_key, allowed_hosts)
    if problems:
        raise ImproperlyConfigured("Refusing to start with DEBUG=0: " + " ".join(problems))


def resolve_registration_mode(value: str | None, debug: bool) -> str:
    """`open` in DEBUG and `invite` otherwise, unless REGISTRATION_MODE says.

    An unknown value fails closed rather than open.
    """
    if not value:
        return "open" if debug else "invite"
    value = value.strip().lower()
    return value if value in REGISTRATION_MODES else "closed"
