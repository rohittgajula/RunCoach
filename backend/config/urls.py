from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from .health import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/", include("apps.athletes.urls")),
    path("api/", include("apps.ingest.urls")),
    path("api/", include("apps.activities.urls")),
    path("api/", include("apps.planning.urls")),
    path("api/", include("apps.coaching.urls")),
    path("api/", include("apps.journal.urls")),
    path("api/", include("apps.diet.urls")),
]

# Meal photos in development. `static()` is a no-op when DEBUG is off — production
# needs a real file server or object storage in front of MEDIA_ROOT.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
