"""Request middleware for running behind Cloudflare + Traefik (docs/DEPLOY.md)."""

import ipaddress

from django.conf import settings


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


class RealClientIPMiddleware:
    """Set REMOTE_ADDR from CF-Connecting-IP when TRUST_CF_CONNECTING_IP is on.

    Throttles key on REMOTE_ADDR, which behind the proxies is a Cloudflare edge or
    Traefik — every user would share one bucket. The header is only trusted when the
    setting says so: the firewall admits only Cloudflare ranges in production, and
    anywhere else the header is whatever the client chose to send.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.TRUST_CF_CONNECTING_IP:
            real = _valid_ip(request.META.get("HTTP_CF_CONNECTING_IP", ""))
            if real:
                request.META["REMOTE_ADDR"] = real
        return self.get_response(request)


class HealthProbeMiddleware:
    """Answer the two health paths before host validation.

    kubelet probes send Host=<pod IP>, which ALLOWED_HOSTS rightly rejects
    (CommonMiddleware calls get_host()). The probes carry no user data, so they are
    answered here, ahead of that check.
    """

    PATHS = {"/api/health/", "/api/health/live/"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in ("GET", "HEAD") and request.path_info in self.PATHS:
            from .health import health, live

            return live(request) if request.path_info.endswith("/live/") else health(request)
        return self.get_response(request)
