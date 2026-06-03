"""
Command endpoint verification: command validation, queuing, access control.

New architecture: commands are sent directly by node_id + gpio,
no pre-registration of ControllableNode required.
All 4 commands (TURN_ON, TURN_OFF, TURN_ON_FOR, WATER_PUMP_ON) are valid for any gpio.

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
print("  [OK] — brak potrzeby rejestracji peryferow!\n")

# ── 1. TURN_OFF (bez parametru) ──
print("=== 1. TURN_OFF on Pico_01 GPIO1 ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 1,
    "command": ["TURN_OFF"]
}, token=jan_access)
print(f"  Status: {s}, command: {b.get('command')}, status: {b.get('status')}")
assert s == 201, f"Expected 201, got {s}: {b}"
assert b["command"] == "TURN_OFF"
assert b["time"] is None
assert b["status"] == "pending"
# human_description sprawdzamy też
assert "human_description" in b
assert b["human_description"] == "Wyłączono"
print("  [PASS]")

# ── 2. TURN_ON_FOR z parametrem czasu ──
print("\n=== 2. TURN_ON_FOR with time ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 1,
    "command": ["TURN_ON_FOR", 8]
}, token=jan_access)
print(f"  Status: {s}, command: {b.get('command')}, time: {b.get('time')}")
assert s == 201
assert b["command"] == "TURN_ON_FOR"
assert b["time"] == 8
assert b["human_description"] == "Włączono na 8 min"
print("  [PASS]")

# ── 3. WATER_PUMP_ON z parametrem czasu ──
print("\n=== 3. WATER_PUMP_ON on any GPIO (no pre-registration required) ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_02", "gpio": 2,
    "command": ["WATER_PUMP_ON", 45]
}, token=jan_access)
print(f"  Status: {s}, command: {b.get('command')}, time: {b.get('time')}")
assert s == 201
assert b["command"] == "WATER_PUMP_ON"
assert b["time"] == 45
assert b["human_description"] == "Nawadnianie przez 45 min"
print("  [PASS]")

# ── 4. Nielegalna nazwa komendy ──
print("\n=== 4. Invalid command name ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 1,
    "command": ["INVALID_CMD"]
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

# ── 7. GPIO powyżej max (40) ──
print("\n=== 7. GPIO value exceeds max (40) ===")
s, b = req("POST", "/api/nodes/command/", {
    "device_id": "2137", "node_id": "Pico_01", "gpio": 99,
    "command": ["TURN_ON"]
}, token=jan_access)
print(f"  Status: {s}")
assert s == 400, f"Expected 400, got {s}: {b}"
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

# ── 10. Heartbeat odbiera komendy + zapisuje last_heartbeat ──
print("\n=== 10. Heartbeat receives queued commands ===")
s, b = req("POST", "/api/nodes/heartbeat/", token=device_access)
assert s == 200, f"Heartbeat failed: {b}"
print(f"  device_id: {b.get('device_id')}, pending_count: {b.get('pending_count')}")
# Powinny być co najmniej te 4 komendy zakolejkowane
assert b.get("pending_count", 0) == 3, f"Expected 3 commands (from tests 1,2,3), got {b.get('pending_count')}"
# Sprawdź format komendy
for cmd in b.get("commands", []):
    assert cmd["command"] in ["TURN_ON", "TURN_OFF"], f"Unexpected command in heartbeat: {cmd['command']}"
print("  [PASS]")

print("\n[SUCCESS] All 10 command tests passed!")
