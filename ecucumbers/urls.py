from django.contrib import admin
from django.urls import include, path

from accounts.views import dashboard_view

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("api/nodes/", include("nodes.urls")),
]
