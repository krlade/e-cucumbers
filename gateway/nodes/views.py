import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .models import Node, ScheduledCommand, SCHEDULABLE_COMMANDS, SCHEDULABLE_COMMANDS_INT_ARG

# Commands that require an integer argument (for manual dispatch)
_COMMANDS_WITH_INT_ARG = {"pin_on", "pin_off", "change_delay", "get_format"}

# All allowed commands (whitelist — never pass arbitrary strings to MQTT)
_ALLOWED_COMMANDS = {"set_on", "set_off", "echo", "get_pins"} | _COMMANDS_WITH_INT_ARG


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

    schedules = ScheduledCommand.objects.filter(node_name=name)
    return render(request, "nodes/node_detail.html", {
        "node": node,
        "live_device": live_device,
        "now": datetime.datetime.now(datetime.timezone.utc),
        "schedules": schedules,
        "schedulable_commands": SCHEDULABLE_COMMANDS,
        "schedulable_int_arg_commands": SCHEDULABLE_COMMANDS_INT_ARG,
    })


# ---------------------------------------------------------------------------
# API — jednorazowe komendy
# ---------------------------------------------------------------------------

@login_required
def node_get_pins(request, name: str):
    """POST /api/nodes/<name>/pins/ — wysyła komendę get_pins do urządzenia przez MQTT."""
    try:
        live = _get_live_device(name)
        if live is None:
            return JsonResponse({"result": "error", "detail": "Brak połączenia z bramką MQTT."}, status=503)
        live.get_pins()
        return JsonResponse({"result": "sent"})
    except Exception as exc:
        return JsonResponse({"result": "error", "detail": str(exc)}, status=500)


@login_required
def node_get_format(request, name: str):
    """POST/GET /api/nodes/<name>/format/ — wysyła komendę get_format do urządzenia przez MQTT."""
    try:
        live = _get_live_device(name)
        if live is None:
            return JsonResponse({"result": "error", "detail": "Brak połączenia z bramką MQTT."}, status=503)
        live.get_format()
        return JsonResponse({"result": "sent"})
    except Exception as exc:
        return JsonResponse({"result": "error", "detail": str(exc)}, status=500)

@login_required
def node_get_logs(request, name: str):
    """GET /api/nodes/<name>/logs/ — pobiera najnowsze logi."""
    try:
        live = _get_live_device(name)
        if live is not None:
            return JsonResponse({"logs": live.logs_history})
        node = get_object_or_404(Node, name=name)
        return JsonResponse({"logs": node.logs or []})
    except Exception as exc:
        return JsonResponse({"result": "error", "detail": str(exc)}, status=500)

@login_required
def node_get_status(request, name: str):
    """GET /api/nodes/<name>/status/ — pobiera najnowszy status do odświeżenia UI."""
    try:
        node = get_object_or_404(Node, name=name)
        return JsonResponse({
            "last_seen_ago": node.last_seen_ago,
            "last_seen": node.last_seen.strftime("%d.%m.%Y %H:%M:%S") if node.last_seen else "",
            "sensor_last_value": node.sensor_last_value,
            "sensor_unit": node.sensor_unit,
        })
    except Exception as exc:
        return JsonResponse({"result": "error", "detail": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# Scheduler CRUD
# ---------------------------------------------------------------------------

@login_required
def schedule_add(request, name: str):
    """POST — dodaje nowy harmonogram komendy dla węzła."""
    if request.method != "POST":
        return redirect("node_detail", name=name)

    command = request.POST.get("command", "").strip()
    raw_interval = request.POST.get("interval_seconds", "").strip()
    raw_arg = request.POST.get("argument", "").strip()

    if command not in SCHEDULABLE_COMMANDS:
        messages.error(request, f"Nieznana komenda: '{command}'")
        return redirect("node_detail", name=name)

    try:
        interval = int(raw_interval)
        if interval < 1:
            raise ValueError
    except ValueError:
        messages.error(request, "Interwał musi być liczbą całkowitą >= 1.")
        return redirect("node_detail", name=name)

    argument = None
    if command in SCHEDULABLE_COMMANDS_INT_ARG:
        try:
            argument = int(raw_arg)
        except ValueError:
            messages.error(request, f"Komenda '{command}' wymaga argumentu całkowitego.")
            return redirect("node_detail", name=name)

    # Upewnij się, że węzeł istnieje
    get_object_or_404(Node, name=name)

    sc = ScheduledCommand.objects.create(
        node_name=name,
        command=command,
        argument=argument,
        interval_seconds=interval,
        enabled=True,
    )

    from nodes import scheduler as sched_module
    sched_module.add_or_replace(sc)

    messages.success(request, f"✓ Dodano harmonogram: {sc}")
    return redirect("node_detail", name=name)


@login_required
def schedule_delete(request, name: str, sc_id: int):
    """POST — usuwa harmonogram."""
    sc = get_object_or_404(ScheduledCommand, pk=sc_id, node_name=name)
    from nodes import scheduler as sched_module
    sched_module.remove(sc.pk)
    sc.delete()
    messages.success(request, "Harmonogram usunięty.")
    return redirect("node_detail", name=name)


@login_required
def schedule_toggle(request, name: str, sc_id: int):
    """POST — włącza/wyłącza harmonogram."""
    sc = get_object_or_404(ScheduledCommand, pk=sc_id, node_name=name)
    from nodes import scheduler as sched_module
    sched_module.toggle(sc.pk, not sc.enabled)
    status = "aktywowany" if not sc.enabled else "wstrzymany"
    messages.success(request, f"Harmonogram {status}.")
    return redirect("node_detail", name=name)
