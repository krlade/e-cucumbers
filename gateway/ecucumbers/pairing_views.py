"""
ecucumbers/pairing_views.py
----------------------------
Widoki GUI do zarządzania parowaniem Gateway ↔ API.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from . import api_client


@login_required
def pairing_status(request):
    """GET /pairing/ — strona statusu połączenia z API."""
    from django.conf import settings
    ctx = {
        "api_status": api_client.status,
        "api_url": getattr(settings, "API_BASE_URL", "—"),
        "device_id": getattr(settings, "API_DEVICE_ID", "—"),
        "heartbeat_interval": getattr(settings, "API_HEARTBEAT_INTERVAL", 30),
    }
    return render(request, "ecucumbers/pairing.html", ctx)


@login_required
@require_POST
def pairing_register(request):
    """POST /pairing/register/ — rejestruje gateway w API za pomocą tokenu parowania."""
    pairing_token = request.POST.get("pairing_token", "").strip()
    if not pairing_token:
        messages.error(request, "Podaj token parowania.")
        return redirect("pairing_status")

    from django.conf import settings
    device_id = getattr(settings, "API_DEVICE_ID", "gateway-01")

    try:
        result = api_client.register(pairing_token, device_id)
        messages.success(
            request,
            f"✓ Gateway sparowany pomyślnie. device_id={result.get('device_id')}, "
            f"właściciel={result.get('owner')}."
        )
    except Exception as e:
        messages.error(request, f"Błąd rejestracji: {e}")

    return redirect("pairing_status")
