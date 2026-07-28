"""
Root URLconf. Everything API lives under /api/v1/ so a future v2 can coexist.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.accounts.urls_users")),
    path("api/v1/", include("apps.clients.urls")),
    path("api/v1/", include("apps.projects.urls")),
    path("api/v1/", include("apps.teams.urls")),
    path("api/v1/", include("apps.documents.urls")),
    path("api/v1/", include("apps.activities.urls")),
    path("api/v1/", include("apps.audit.urls")),
    path("api/v1/", include("apps.tickets.urls")),
    path("api/v1/", include("apps.quotations.urls")),
    path("api/v1/", include("apps.billing.urls")),
    path("api/v1/", include("apps.meetings.urls")),
    path("api/v1/", include("apps.notifications.urls")),
    path("api/v1/", include("apps.dashboard.urls")),
    path("api/v1/", include("apps.reports.urls")),
    path("api/v1/", include("apps.search.urls")),
    # OpenAPI schema + interactive docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

# In dev, Django itself serves uploaded files. In prod Nginx does this.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
