from django.conf import settings
from django.conf.urls.static import static
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
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
