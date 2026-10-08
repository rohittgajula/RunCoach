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


class DataVersionMiddleware:
    """R18 §B: `X-Data-Version` on every authenticated /api/ response; on a successful
    mutating request the athlete's data version is bumped and returned as `data_version`
    in a JSON-object body. AI-only and auth endpoints don't bump (generating a summary is
    not a data change, and must not mark itself stale)."""

    MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
    NO_BUMP_PREFIX = ("/api/auth/", "/api/insights/summary/", "/api/briefing/ai/",
                      "/api/coach/", "/api/admin/", "/api/garmin/sync/", "/api/sync/",
                      "/api/progress/review/")
    NO_BUMP_SUFFIX = ("/review/ai/", "/ai-review/", "/analysis/", "/guide/")

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _athlete_id(request):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None
        athlete = getattr(user, "athlete", None)
        return getattr(athlete, "pk", None)

    def _no_bump(self, path: str) -> bool:
        return path.startswith(self.NO_BUMP_PREFIX) or path.endswith(self.NO_BUMP_SUFFIX)

    def process_template_response(self, request, response):
        if request.method not in self.MUTATING or not request.path.startswith("/api/"):
            return response
        if not 200 <= response.status_code < 300:
            return response
        try:
            athlete_id = self._athlete_id(request)
        except Exception:  # noqa: BLE001
            return response
        if not athlete_id:
            return response
        from apps.athletes.versioning import bump, current

        version = current(athlete_id) if self._no_bump(request.path) else bump(athlete_id)
        data = getattr(response, "data", None)
        if isinstance(data, dict) and version:
            data["data_version"] = version
        return response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            try:
                athlete_id = self._athlete_id(request)
                if athlete_id:
                    from apps.athletes.versioning import current

                    response["X-Data-Version"] = str(current(athlete_id))
            except Exception:  # noqa: BLE001
                pass
        return response
