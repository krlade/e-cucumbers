from django.urls import path
from . import views

urlpatterns = [
    path("pairing-token/", views.CreatePairingTokenView.as_view(), name="pairing-token"),
    path("register-device/", views.RegisterDeviceView.as_view(), name="register-device"),
    path("register-peripherals/", views.RegisterPeripheralsView.as_view(), name="register-peripherals"),
    path("peripherals/", views.ListPeripheralsView.as_view(), name="list-peripherals"),
    path("node-config/", views.NodeConfigView.as_view(), name="node-config"),
    path("command/", views.SendCommandView.as_view(), name="send-command"),
    path("heartbeat/", views.HeartbeatView.as_view(), name="heartbeat"),
    path("telemetry/", views.TelemetryView.as_view(), name="telemetry"),
    path("telemetry-nodes/", views.TelemetryNodesView.as_view(), name="telemetry-nodes"),
    path("user-devices/", views.ListDevicesView.as_view(), name="user-devices"),
]
