from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

urlpatterns = [
    # --- Web (HTML) ---
    path("register/", views.register_view, name="register"),
    path("login/", LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("manage-users/", views.manage_users_view, name="manage_users"),
    # --- API (JSON) ---
    path("api/register/", views.ApiRegisterView.as_view(), name="api-register"),
    path("api/login/", TokenObtainPairView.as_view(), name="api-login"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="api-token-refresh"),
    path("api/me/", views.MeView.as_view(), name="api-me"),
]
