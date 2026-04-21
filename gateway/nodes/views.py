import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import Node

# Commands that require an integer argument
_COMMANDS_WITH_INT_ARG = {"pin_on", "pin_off", "change_delay"}

# All allowed commands (whitelist — never pass arbitrary strings to MQTT)
_ALLOWED_COMMANDS = {"set_on", "set_off", "echo"} | _COMMANDS_WITH_INT_ARG


def _get_live_device(name: str):
    """Zwraca in-memory obiekt Device z Gateway lub None."""
    try:
        from ecucumbers.mqtt_client import station
        if station and name in station.devices:
            return station.devices[name]
    except ImportError:
        pass
    return None


@login_required
def node_detail(request, name: str):
    """Strona szczegółowa węzła z panelem sterowania."""
    node = get_object_or_404(Node, name=name)
    live_device = _get_live_device(name)

    if request.method == "POST":
        command = request.POST.get("command", "").strip()
        raw_arg = request.POST.get("argument", "").strip()

        if command not in _ALLOWED_COMMANDS:
            messages.error(request, f"Nieznana komenda: '{command}'")
            return redirect("node_detail", name=name)

        if live_device is None:
            messages.error(request, "Brak połączenia z bramką MQTT — nie można wysłać komendy.")
            return redirect("node_detail", name=name)

        try:
            if command in _COMMANDS_WITH_INT_ARG:
                arg = int(raw_arg)
                getattr(live_device, command)(arg)
                messages.success(request, f"✓ Wysłano komendę '{command}' z argumentem {arg}.")
            else:
                getattr(live_device, command)()
                messages.success(request, f"✓ Wysłano komendę '{command}'.")
        except (ValueError, AttributeError) as exc:
            messages.error(request, f"Błąd wykonania komendy: {exc}")

        return redirect("node_detail", name=name)

    return render(request, "nodes/node_detail.html", {
        "node": node,
        "live_device": live_device,
        "now": datetime.datetime.now(datetime.timezone.utc),
    })
