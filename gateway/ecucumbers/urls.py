from django.contrib import admin
from django.urls import include, path

from accounts.views import dashboard_view
from ecucumbers.pairing_views import pairing_status, pairing_register

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("api/nodes/", include("nodes.urls")),
    # Gateway ↔ API pairing
    path("pairing/", pairing_status, name="pairing_status"),
    path("pairing/register/", pairing_register, name="pairing_register"),
]
