"""
Command endpoint verification: command validation, queuing, access control.

Usage:
    1. python manage.py flush --no-input
    2. python manage.py runserver   (osobny terminal)
    3. python tests/test_command.py
"""
import json
import urllib.request
import urllib.error

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


# ── Setup ──
print("=== Setup ===")
s, b = req("POST", "/api/accounts/register/",
           {"username": "jan", "email": "jan@x.com", "password": "SilneHaslo123"})
assert s == 201, f"Register failed: {b}"
jan_access = b["access"]

s, b = req("POST", "/api/nodes/pairing-token/", token=jan_access)
assert s == 201
s, b = req("POST", "/api/nodes/register-device/",
           {"device_id": "2137", "pairing_token": b["token"]})
assert s == 200
device_access = b["access"]

# Rejestracja peryferiów: lampa GPIO1, zraszacz GPIO2
s, b = req("POST", "/api/nodes/register-peripherals/", {
    "device_id": "2137",
    "peripherals": [
        {"node_id": "Pico_01", "gpio": 1, "peripheral_type": "LAMP"},
        {"node_id": "Pico_02", "gpio": 2, "peripheral_type": "SPRINKLER"},
    ],
}, token=device_access)
assert s == 200, f"Register peripherals failed: {b}"
print("  [OK]\n")

# ── 1. TURN_OFF (bez parametru) ──
print("=== 1. TURN_OFF on lamp ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 1,
    "command": ["TURN_OFF"]
}, token=jan_access)
print(f"  Status: {s}, command: {b.get('command')}, status: {b.get('status')}")
assert s == 201, f"Expected 201, got {s}: {b}"
assert b["command"] == "TURN_OFF"
assert b["time"] is None
assert b["status"] == "pending"
print("  [PASS]")

# ── 2. TURN_ON_FOR z parametrem czasu (godziny) ──
print("\n=== 2. TURN_ON_FOR lamp with time ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 1,
    "command": ["TURN_ON_FOR", 8]
}, token=jan_access)
print(f"  Status: {s}, command: {b.get('command')}, time: {b.get('time')}")
assert s == 201
assert b["command"] == "TURN_ON_FOR"
assert b["time"] == 8
print("  [PASS]")

# ── 3. WATER_PUMP_ON z parametrem czasu (minuty) ──
print("\n=== 3. WATER_PUMP_ON sprinkler with time ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_02", "gpio": 2,
    "command": ["WATER_PUMP_ON", 45]
}, token=jan_access)
print(f"  Status: {s}, command: {b.get('command')}, time: {b.get('time')}")
assert s == 201
assert b["command"] == "WATER_PUMP_ON"
assert b["time"] == 45
print("  [PASS]")

# ── 4. Nielegalna komenda dla danego typu ──
print("\n=== 4. Illegal command for peripheral type ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_02", "gpio": 2,
    "command": ["TURN_OFF"]  # TURN_OFF jest dla LAMP, nie SPRINKLER
}, token=jan_access)
print(f"  Status: {s}")
assert s == 400, f"Expected 400, got {s}: {b}"
print("  [PASS]")

# ── 5. Brak wymaganego parametru czasu ──
print("\n=== 5. Missing required time param ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 1,
    "command": ["TURN_ON_FOR"]  # brak czasu
}, token=jan_access)
print(f"  Status: {s}")
assert s == 400
print("  [PASS]")

# ── 6. Nieoczekiwany parametr czasu ──
print("\n=== 6. Unexpected time param on paramless command ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 1,
    "command": ["TURN_OFF", 5]  # TURN_OFF nie przyjmuje czasu
}, token=jan_access)
print(f"  Status: {s}")
assert s == 400
print("  [PASS]")

# ── 7. Nieistniejący GPIO ──
print("\n=== 7. Non-existent GPIO ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 99,
    "command": ["TURN_ON"]
}, token=jan_access)
print(f"  Status: {s}")
assert s == 400
print("  [PASS]")

# ── 8. Brak dostępu (inny użytkownik) ──
print("\n=== 8. No access (different user) ===")
s, b2 = req("POST", "/api/accounts/register/",
            {"username": "ewa", "email": "ewa@x.com", "password": "SilneHaslo123"})
assert s == 201
ewa_access = b2["access"]
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 1,
    "command": ["TURN_ON"]
}, token=ewa_access)
print(f"  Status: {s}")
assert s == 403
print("  [PASS]")

# ── 9. Brak JWT ──
print("\n=== 9. No JWT ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 1,
    "command": ["TURN_ON"]
})
print(f"  Status: {s}")
assert s in (401, 403)
print("  [PASS]")

print("\n✅ All 9 command tests passed!")
