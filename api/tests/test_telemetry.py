"""
Phase 2 verification: telemetry isolation and node_id filtering.

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

# ── 1. Rejestracja peryferiów z tym samym czujnikiem ──
print("=== 1. Register peripherals (Pico_01 & Pico_02 with temperature) ===")
payload = {
    "device_id": device_id,
    "peripherals": [
        {"node_id": "Pico_01", "sensor_type": "temperature"},
        {"node_id": "Pico_02", "sensor_type": "temperature"},
    ],
}
s, b = req("POST", "/api/nodes/register-peripherals/", payload, token=device_access)
assert s == 200, f"Register peripherals failed: {b}"
assert b["registered_count"] == 2
print("  [PASS]")

# ── 2. Wysyłanie różnych wartości telemetrii ──
print("\n=== 2. Send telemetry for Pico_01 and Pico_02 ===")
s, b1 = req("POST", "/api/nodes/telemetry/", {"node_id": "Pico_01", "value": 25.4}, token=device_access)
assert s == 201, f"Send telemetry Pico_01 failed: {b1}"
s, b2 = req("POST", "/api/nodes/telemetry/", {"node_id": "Pico_02", "value": 37.8}, token=device_access)
assert s == 201, f"Send telemetry Pico_02 failed: {b2}"
print("  [PASS]")

# ── 3. Pobranie telemetrii bez filtra node_id ──
print("\n=== 3. Get telemetry without node_id filter ===")
s, readings = req("GET", f"/api/nodes/telemetry/?device_id={device_id}&sensor_type=temperature", token=tomek_access)
assert s == 200, f"Get telemetry failed: {readings}"
assert len(readings) == 2, f"Expected 2 readings, got {len(readings)}"
values = [r["value"] for r in readings]
assert 25.4 in values and 37.8 in values, f"Expected values 25.4 and 37.8, got {values}"
print(f"  Received mixed values: {values}")
print("  [PASS]")

# ── 4. Pobranie telemetrii z filtrem node_id=Pico_01 ──
print("\n=== 4. Get telemetry with node_id=Pico_01 ===")
s, readings = req("GET", f"/api/nodes/telemetry/?device_id={device_id}&sensor_type=temperature&node_id=Pico_01", token=tomek_access)
assert s == 200, f"Get telemetry Pico_01 failed: {readings}"
assert len(readings) == 1, f"Expected 1 reading, got {len(readings)}"
assert readings[0]["node_id"] == "Pico_01"
assert readings[0]["value"] == 25.4
print(f"  Received Pico_01 value: {readings[0]['value']}")
print("  [PASS]")

# ── 5. Pobranie telemetrii z filtrem node_id=Pico_02 ──
print("\n=== 5. Get telemetry with node_id=Pico_02 ===")
s, readings = req("GET", f"/api/nodes/telemetry/?device_id={device_id}&sensor_type=temperature&node_id=Pico_02", token=tomek_access)
assert s == 200, f"Get telemetry Pico_02 failed: {readings}"
assert len(readings) == 1, f"Expected 1 reading, got {len(readings)}"
assert readings[0]["node_id"] == "Pico_02"
assert readings[0]["value"] == 37.8
print(f"  Received Pico_02 value: {readings[0]['value']}")
print("  [PASS]")

print("\n[SUCCESS] All telemetry isolation tests passed!")
