"""
Telemetry endpoint verification: raw payload passthrough, node_id filtering.

New format: gateway sends raw payload {"node_id": "Pico_01", "payload": {"data": 25.4}}
sensor_type is optional - resolved from ControllableNode if configured.

Usage:
    1. python manage.py flush --no-input
    2. python manage.py runserver   (osobny terminal)
    3. python tests/test_telemetry.py
"""
import json
import urllib.request
import urllib.error
import time
import random

BASE = "http://127.0.0.1:8000"


def req(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else b""
    r = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return e.code, body


# Generowanie unikalnych danych dla testu
unique_suffix = f"{int(time.time())}_{random.randint(1000, 9999)}"
username = f"tomek_{unique_suffix}"
device_id = f"dev_{unique_suffix}"

# ── Setup: rejestracja użytkownika + parowanie urządzenia ──
print(f"=== Setup with user={username} and device_id={device_id} ===")
s, b = req("POST", "/api/accounts/register/",
           {"username": username, "email": f"{username}@x.com", "password": "SilneHaslo123"})
assert s == 201, f"Register failed: {b}"
tomek_access = b["access"]

s, b = req("POST", "/api/nodes/pairing-token/", token=tomek_access)
assert s == 201
pt = b["token"]

s, b = req("POST", "/api/nodes/register-device/",
           {"device_id": device_id, "pairing_token": pt})
assert s == 200, f"Register device failed: {b}"
device_access = b["access"]
print("  [OK]\n")

# ── 1. Wysyłanie surowego payloadu z węzłów (nowy format) ──
print("=== 1. Send raw telemetry from Pico_01 and Pico_02 (no pre-registration) ===")
s, b1 = req("POST", "/api/nodes/telemetry/", {"node_id": "Pico_01", "payload": {"data": 25.4}}, token=device_access)
assert s == 201, f"Send telemetry Pico_01 failed: {b1}"
assert b1["node_id"] == "Pico_01"
assert b1["value"] == 25.4
assert b1["sensor_type"] is None  # Brak konfiguracji → sensor_type jest None
assert b1["raw_payload"] == {"data": 25.4}

s, b2 = req("POST", "/api/nodes/telemetry/", {"node_id": "Pico_02", "payload": {"data": 37.8}}, token=device_access)
assert s == 201, f"Send telemetry Pico_02 failed: {b2}"
assert b2["value"] == 37.8
assert b2["sensor_type"] is None
print("  [PASS]")

# ── 2. Konfiguracja węzła przez użytkownika (node-config) ──
print("\n=== 2. Configure node via node-config endpoint ===")
s, b = req("POST", "/api/nodes/node-config/", {
    "device_id": device_id,
    "node_id": "Pico_01",
    "sensor_type": "temperature",
    "label": "Termometr glowny"
}, token=tomek_access)
assert s == 200, f"Node config failed: {b}"
assert b["sensor_type"] == "temperature"
assert b["label"] == "Termometr glowny"
print("  [PASS]")

# ── 3. Po konfiguracji — nowe odczyty powinny mieć sensor_type ──
print("\n=== 3. After config - new readings have sensor_type ===")
s, b3 = req("POST", "/api/nodes/telemetry/", {"node_id": "Pico_01", "payload": {"data": 26.1}}, token=device_access)
assert s == 201, f"Send telemetry after config failed: {b3}"
assert b3["sensor_type"] == "temperature"
assert b3["value"] == 26.1
print("  [PASS]")

# ── 4. Pobranie telemetrii z filtrem node_id=Pico_01 ──
print("\n=== 4. Get telemetry with node_id=Pico_01 ===")
s, readings = req("GET", f"/api/nodes/telemetry/?device_id={device_id}&node_id=Pico_01", token=tomek_access)
assert s == 200, f"Get telemetry failed: {readings}"
assert len(readings) >= 2, f"Expected at least 2 readings for Pico_01, got {len(readings)}"
for r in readings:
    assert r["node_id"] == "Pico_01", f"Unexpected node_id: {r['node_id']}"
values = [r["value"] for r in readings]
print(f"  Pico_01 values: {values}")
print("  [PASS]")

# ── 5. Pobranie telemetrii z filtrem node_id=Pico_02 ──
print("\n=== 5. Get telemetry with node_id=Pico_02 ===")
s, readings = req("GET", f"/api/nodes/telemetry/?device_id={device_id}&node_id=Pico_02", token=tomek_access)
assert s == 200, f"Get telemetry Pico_02 failed: {readings}"
assert len(readings) == 1, f"Expected 1 reading for Pico_02, got {len(readings)}"
assert readings[0]["node_id"] == "Pico_02"
assert readings[0]["value"] == 37.8
assert readings[0]["sensor_type"] is None  # Pico_02 nie jest skonfigurowany
print(f"  Pico_02 value: {readings[0]['value']}")
print("  [PASS]")

# ── 6. Filtrowanie po sensor_type ──
print("\n=== 6. Filter telemetry by sensor_type=temperature ===")
s, readings = req("GET", f"/api/nodes/telemetry/?device_id={device_id}&sensor_type=temperature", token=tomek_access)
assert s == 200
# Powinny być tylko odczyty z Pico_01 po konfiguracji (jeden z b3)
for r in readings:
    assert r["sensor_type"] == "temperature"
print(f"  Temperature readings count: {len(readings)}")
print("  [PASS]")

print("\n[SUCCESS] All telemetry tests passed!")
