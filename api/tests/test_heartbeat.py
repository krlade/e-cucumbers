"""
Heartbeat endpoint verification: command delivery flow.

Usage:
    1. python manage.py flush --no-input
    2. python manage.py runserver   (osobny terminal)
    3. python tests/test_heartbeat.py
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
assert s == 201
jan_access = b["access"]

s, b = req("POST", "/api/nodes/pairing-token/", token=jan_access)
assert s == 201
s, b = req("POST", "/api/nodes/register-device/",
           {"device_id": "2137", "pairing_token": b["token"]})
assert s == 200
device_access = b["access"]

s, b = req("POST", "/api/nodes/register-peripherals/", {
    "device_id": "2137",
    "peripherals": [
        {"node_id": "Pico_01", "gpio": 1, "peripheral_type": "LAMP"},
        {"node_id": "Pico_02", "gpio": 2, "peripheral_type": "SPRINKLER"},
    ],
}, token=device_access)
assert s == 200

# Zakolejkuj 5 komend
for _ in range(3):
    s, b = req("POST", "/api/nodes/command/",
               {"device_id": "2137", "node_id": "Pico_01", "gpio": 1, "command": ["TURN_ON"]},
               token=jan_access)
    assert s == 201
for _ in range(2):
    s, b = req("POST", "/api/nodes/command/",
               {"device_id": "2137", "node_id": "Pico_02", "gpio": 2, "command": ["WATER_PUMP_ON", 30]},
               token=jan_access)
    assert s == 201
print("  [OK]\n")

# ── 1. Heartbeat z device JWT — odbiera 5 komend ──
print("=== 1. Heartbeat receives pending commands ===")
s, b = req("POST", "/api/nodes/heartbeat/", token=device_access)
print(f"  Status: {s}, pending_count: {b.get('pending_count')}")
assert s == 200, f"Expected 200, got {s}: {b}"
assert b["device_id"] == "2137"
assert b["pending_count"] == 5
assert len(b["commands"]) == 5
# Sprawdz strukturę pierwszej komendy
cmd = b["commands"][0]
assert "node_id" in cmd and "gpio" in cmd and "command" in cmd
assert "peripheral_type" not in cmd
assert "time" not in cmd
print(f"  Przykładowa komenda: node={cmd['node_id']} gpio={cmd['gpio']} "
      f"cmd={cmd['command']}")
print("  [PASS]")

# ── 2. Kolejny heartbeat — brak pending (już dostarczone) ──
print("\n=== 2. Second heartbeat — no pending commands ===")
s, b = req("POST", "/api/nodes/heartbeat/", token=device_access)
print(f"  Status: {s}, pending_count: {b.get('pending_count')}")
assert s == 200
assert b["pending_count"] == 0
assert b["commands"] == []
print("  [PASS]")

# ── 3. Nowa komenda po heartbeat — znowu widoczna ──
print("\n=== 3. New command after heartbeat ===")
s, _ = req("POST", "/api/nodes/command/",
           {"device_id": "2137", "node_id": "Pico_01", "gpio": 1, "command": ["TURN_OFF"]},
           token=jan_access)
assert s == 201
s, b = req("POST", "/api/nodes/heartbeat/", token=device_access)
print(f"  Status: {s}, pending_count: {b.get('pending_count')}")
assert s == 200
assert b["pending_count"] == 1
assert b["commands"][0]["command"] == "TURN_OFF"
print("  [PASS]")

# ── 4. Blokada: user JWT nie może uderzać w heartbeat ──
print("\n=== 4. User JWT rejected on heartbeat ===")
s, b = req("POST", "/api/nodes/heartbeat/", token=jan_access)
print(f"  Status: {s}")
assert s == 403, f"Expected 403, got {s}: {b}"
print("  [PASS]")

# ── 5. Blokada: brak JWT ──
print("\n=== 5. No JWT rejected ===")
s, b = req("POST", "/api/nodes/heartbeat/")
print(f"  Status: {s}")
assert s in (401, 403)
print("  [PASS]")

print("\n[SUCCESS] All 5 heartbeat tests passed!")
