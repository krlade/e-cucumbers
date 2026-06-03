"""
Phase 2 verification: peripherals registration and listing.

Usage:
    1. python manage.py flush --no-input
    2. python manage.py runserver   (osobny terminal)
    3. python tests/test_peripherals.py
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


# ── Setup: rejestracja użytkownika + parowanie urządzenia ──
print("=== Setup ===")
s, b = req("POST", "/api/accounts/register/",
           {"username": "jan", "email": "jan@x.com", "password": "SilneHaslo123"})
assert s == 201, f"Register failed: {b}"
jan_access = b["access"]

s, b = req("POST", "/api/nodes/pairing-token/", token=jan_access)
assert s == 201
pt = b["token"]

s, b = req("POST", "/api/nodes/register-device/",
           {"device_id": "2137", "pairing_token": pt})
assert s == 200, f"Register device failed: {b}"
device_access = b["access"]
print(f"  device JWT: {device_access[:30]}...")
print("  [OK]\n")

# ── 1. Rejestracja peryferiów przez gateway (3 lampy + 2 zraszacze) ──
print("=== 1. Register peripherals (gateway JWT) ===")
payload = {
    "device_id": "2137",
    "peripherals": [
        {"node_id": "Pico_01", "gpio": 1, "peripheral_type": "LAMP"},
        {"node_id": "Pico_02", "gpio": 2, "peripheral_type": "LAMP"},
        {"node_id": "Pico_03", "gpio": 3, "peripheral_type": "LAMP"},
        {"node_id": "Pico_04", "gpio": 4, "peripheral_type": "SPRINKLER"},
        {"node_id": "Pico_05", "gpio": 5, "peripheral_type": "SPRINKLER"},
    ],
}
s, b = req("POST", "/api/nodes/register-peripherals/", payload, token=device_access)
print(f"  Status: {s}, registered_count: {b.get('registered_count')}")
assert s == 200, f"Expected 200, got {s}: {b}"
assert b["registered_count"] == 5
peripherals = b["peripherals"]
lamps = [p for p in peripherals if p["peripheral_type"] == "LAMP"]
sprinklers = [p for p in peripherals if p["peripheral_type"] == "SPRINKLER"]
assert len(lamps) == 3, f"Expected 3 lamps, got {len(lamps)}"
assert len(sprinklers) == 2, f"Expected 2 sprinklers, got {len(sprinklers)}"
print(f"  Lampy: {len(lamps)}, Zraszacze: {len(sprinklers)}")

lamp_cmds = [c["name"] for c in lamps[0]["allowed_commands"]]
assert set(lamp_cmds) == {"TURN_ON", "TURN_OFF", "TURN_ON_FOR"}, f"Lamp commands wrong: {lamp_cmds}"
print(f"  Lampa komendy: {lamp_cmds}")

spr_cmds = [c["name"] for c in sprinklers[0]["allowed_commands"]]
assert set(spr_cmds) == {"WATER_PUMP_ON", "TURN_OFF"}, f"Sprinkler commands wrong: {spr_cmds}"
print(f"  Zraszacz komendy: {spr_cmds}")
print("  [PASS]")

# ── 2. Idempotentność — ponowna rejestracja tych samych peryferiów ──
print("\n=== 2. Idempotency: re-register same peripherals ===")
s, b = req("POST", "/api/nodes/register-peripherals/", payload, token=device_access)
print(f"  Status: {s}, registered_count: {b.get('registered_count')}")
assert s == 200
assert b["registered_count"] == 5
print("  [PASS]")

# ── 3. Blokada: user JWT nie może rejestrować peryferiów (tylko device JWT) ──
print("\n=== 3. User JWT cannot register peripherals ===")
s, b = req("POST", "/api/nodes/register-peripherals/", payload, token=jan_access)
print(f"  Status: {s}")
assert s == 403, f"Expected 403, got {s}: {b}"
print("  [PASS]")

# ── 4. Blokada: brak JWT ──
print("\n=== 4. No JWT rejected ===")
s, b = req("POST", "/api/nodes/register-peripherals/", payload)
print(f"  Status: {s}")
assert s in (401, 403)
print("  [PASS]")

# ── 5. Listowanie peryferiów przez użytkownika ──
print("\n=== 5. List peripherals (user JWT) ===")
s, b = req("GET", "/api/nodes/peripherals/?device_id=2137", token=jan_access)
print(f"  Status: {s}, count: {len(b.get('peripherals', []))}")
assert s == 200
assert len(b["peripherals"]) == 5
print("  [PASS]")

# ── 6. Blokada: inny user bez uprawnień nie widzi peryferiów ──
print("\n=== 6. Unauthorized user cannot list peripherals ===")
s, b2 = req("POST", "/api/accounts/register/",
            {"username": "ewa", "email": "ewa@x.com", "password": "SilneHaslo123"})
assert s == 201
ewa_access = b2["access"]
s, b = req("GET", "/api/nodes/peripherals/?device_id=2137", token=ewa_access)
print(f"  Status: {s}")
assert s == 403
print("  [PASS]")

# ── 7. Brakujący device_id w query params ──
print("\n=== 7. Missing device_id param ===")
s, b = req("GET", "/api/nodes/peripherals/", token=jan_access)
print(f"  Status: {s}")
assert s == 400
print("  [PASS]")

# ── 8. Walidacja: błędny peripheral_type ──
print("\n=== 8. Invalid peripheral_type ===")
bad_payload = {
    "device_id": "2137",
    "peripherals": [{"node_id": "Pico_01", "gpio": 9, "peripheral_type": "TOASTER"}],
}
s, b = req("POST", "/api/nodes/register-peripherals/", bad_payload, token=device_access)
print(f"  Status: {s}")
assert s == 400
print("  [PASS]")

print("\n[OK] All 8 peripheral tests passed!")
