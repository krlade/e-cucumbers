from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

urlpatterns = [
    path("register/", views.ApiRegisterView.as_view(), name="api-register"),
    path("login/", TokenObtainPairView.as_view(), name="api-login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="api-token-refresh"),
    path("me/", views.MeView.as_view(), name="api-me"),
]
