from django.urls import path
from . import views

urlpatterns = [
    path("pairing-token/", views.CreatePairingTokenView.as_view(), name="pairing-token"),
    path("register-device/", views.RegisterDeviceView.as_view(), name="register-device"),
]
