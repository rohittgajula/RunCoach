"""Signed, expiring URLs for meal photos (docs/DEPLOY.md §2.4).

An <img src> cannot send an Authorization header, so the URL itself carries the
permission: `/api/media/signed/<path>?exp=<unix>&sig=<hmac>`. Only the owner's own
meal JSON ever contains a URL for their path, the signature binds path and expiry,
and anything else — a changed path, a later expiry, a stale link — is a 404.
"""

import mimetypes
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from django.conf import settings
from django.http import FileResponse, Http404
from django.utils.crypto import constant_time_compare, salted_hmac

SALT = "runcoach.media.signed"
SIGNED_PREFIX = "/api/media/signed/"
# Only these top-level media directories are ever served. FIT files are not.
SERVABLE_ROOTS = {"meals"}


def _signature(path: str, exp: int) -> str:
    return salted_hmac(SALT, f"{path}:{exp}", algorithm="sha256").hexdigest()


def _clean(path: str) -> str | None:
    """The path if it is a plain relative path under a servable root, else None."""
    if not path or "\\" in path or "\x00" in path:
        return None
    # Split by hand: PurePosixPath would quietly normalise "a//b" and "a/./b".
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts) or parts[0] not in SERVABLE_ROOTS:
        return None
    return path


def signed_url(path: str, ttl: int | None = None, now: float | None = None) -> str | None:
    clean = _clean(path)
    if clean is None:
        return None
    exp = int((now if now is not None else time.time()) + (ttl or settings.SIGNED_MEDIA_TTL_SEC))
    query = urlencode({"exp": exp, "sig": _signature(clean, exp)})
    return f"{SIGNED_PREFIX}{quote(clean)}?{query}"


def verify(path: str, exp: str | None, sig: str | None, now: float | None = None) -> str | None:
    """The clean path when the signature is valid and unexpired, else None."""
    clean = _clean(path)
    if clean is None or not exp or not sig:
        return None
    try:
        exp_int = int(exp)
    except ValueError:
        return None
    if exp_int < (now if now is not None else time.time()):
        return None
    if not constant_time_compare(sig, _signature(clean, exp_int)):
        return None
    return clean


def serve_signed(request, path: str):
    clean = verify(path, request.GET.get("exp"), request.GET.get("sig"))
    if clean is None:
        raise Http404
    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / clean).resolve()
    # Belt and braces after _clean: a symlink must not lead out of MEDIA_ROOT either.
    if root not in target.parents or not target.is_file():
        raise Http404
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    response = FileResponse(target.open("rb"), content_type=content_type)
    remaining = max(0, int(request.GET["exp"]) - int(time.time()))
    response["Cache-Control"] = f"private, max-age={remaining}"
    response["X-Content-Type-Options"] = "nosniff"
    return response
