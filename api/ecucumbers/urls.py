from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from accounts.views import dashboard_view, simulation_view

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("simulation/", simulation_view, name="simulation"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),          # HTML views
    path("api/accounts/", include("accounts.api_urls")),  # API JSON
    path("api/nodes/", include("nodes.urls")),             # API JSON
    # OpenAPI schema + Swagger UI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
