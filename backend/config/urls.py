from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from .health import health, live

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/health/live/", live, name="health-live"),
    path("api/", include("apps.athletes.urls")),
    path("api/", include("apps.ingest.urls")),
    path("api/", include("apps.activities.urls")),
    path("api/", include("apps.planning.urls")),
    path("api/", include("apps.coaching.urls")),
    path("api/", include("apps.journal.urls")),
    path("api/", include("apps.diet.urls")),
    path("api/", include("apps.habits.urls")),
    # R10
    path("api/", include("apps.health.urls")),
    path("api/", include("apps.gear.urls")),
    path("api/", include("apps.reminders.urls")),
]

# Raw MEDIA_URL in development only. `static()` is a no-op when DEBUG is off; meal
# photos then go out as signed URLs (apps/diet/media.py) and nothing else is public.
# R13 §15: data exports live under MEDIA_ROOT/exports/ and are never served here — only
# through the authenticated one-time download (apps/athletes/export.py).
def media(request, path):
    import posixpath

    from django.http import Http404
    from django.views.static import serve

    clean = posixpath.normpath(path).lstrip("/")
    if clean == "exports" or clean.startswith("exports/"):
        raise Http404
    return serve(request, clean, document_root=settings.MEDIA_ROOT)


if settings.DEBUG:
    from django.urls import re_path

    prefix = settings.MEDIA_URL.lstrip("/")
    urlpatterns += [re_path(rf"^{prefix}(?P<path>.*)$", media)]
