"""
Phase 2 verification: controllable nodes registration and listing.

Usage:
    1. python manage.py flush --no-input
    2. python manage.py runserver   (osobny terminal)
    3. python tests/test_nodes.py
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

# ── 1. Rejestracja węzłów przez gateway (JWT urządzenia) ──
print("=== 1. Register nodes (gateway JWT) ===")
nodes_payload = {
    "device_id": "2137",
    "nodes": [
        {"node_id": "Pico_01", "gpio": 1, "device_type": "LAMP",      "label": "Lampa glowna"},
        {"node_id": "Pico_01", "gpio": 2, "device_type": "SPRINKLER", "label": "Zraszacz lewy"},
        {"node_id": "Pico_01", "gpio": 3, "device_type": "SPRINKLER", "label": "Zraszacz prawy"},
        {"node_id": "Pico_02", "gpio": 1, "device_type": "LAMP",      "label": "Lampa boczna"},
        {"node_id": "Pico_02", "gpio": 2, "device_type": "SPRINKLER", "label": "Zraszacz tylny"},
    ],
}
s, b = req("POST", "/api/nodes/register-nodes/", nodes_payload, token=device_access)
print(f"  Status: {s}")
print(f"  registered_count: {b.get('registered_count')}")
assert s == 200, f"Expected 200, got {s}: {b}"
assert b["registered_count"] == 5
nodes = b["nodes"]
lamps = [n for n in nodes if n["device_type"] == "LAMP"]
sprinklers = [n for n in nodes if n["device_type"] == "SPRINKLER"]
assert len(lamps) == 2, f"Expected 2 lamps, got {len(lamps)}"
assert len(sprinklers) == 3, f"Expected 3 sprinklers, got {len(sprinklers)}"
print(f"  Lampy: {len(lamps)}, Zraszacze: {len(sprinklers)}")

# Sprawdz legalne komendy
lamp = lamps[0]
lamp_cmd_names = [c["name"] for c in lamp["allowed_commands"]]
assert "TURN_ON" in lamp_cmd_names
assert "TURN_OFF" in lamp_cmd_names
assert "TURN_ON_FOR" in lamp_cmd_names
print(f"  Lampa komendy: {lamp_cmd_names}")

sprinkler = sprinklers[0]
spr_cmd_names = [c["name"] for c in sprinkler["allowed_commands"]]
assert spr_cmd_names == ["WATER_PUMP_ON"]
print(f"  Zraszacz komendy: {spr_cmd_names}")
print("  [PASS]")

# ── 2. Idempotentność — ponowna rejestracja tych samych węzłów ──
print("\n=== 2. Idempotency: re-register same nodes ===")
s, b = req("POST", "/api/nodes/register-nodes/", nodes_payload, token=device_access)
print(f"  Status: {s}, registered_count: {b.get('registered_count')}")
assert s == 200
assert b["registered_count"] == 5  # te same 5, nie 10
print("  [PASS]")

# ── 3. Aktualizacja etykiety istniejącego węzła ──
print("\n=== 3. Update existing node label ===")
update_payload = {
    "device_id": "2137",
    "nodes": [{"node_id": "Pico_01", "gpio": 1, "device_type": "LAMP", "label": "Nowa etykieta"}],
}
s, b = req("POST", "/api/nodes/register-nodes/", update_payload, token=device_access)
assert s == 200
updated_node = b["nodes"][0]
assert updated_node["label"] == "Nowa etykieta", f"Label not updated: {updated_node['label']}"
print(f"  Updated label: {updated_node['label']}")
print("  [PASS]")

# ── 4. Blokada: user JWT nie może rejestrować węzłów (tylko device JWT) ──
print("\n=== 4. User JWT cannot register nodes ===")
s, b = req("POST", "/api/nodes/register-nodes/", nodes_payload, token=jan_access)
print(f"  Status: {s}")
assert s == 403, f"Expected 403, got {s}: {b}"
print("  [PASS]")

# ── 5. Blokada: brak JWT ──
print("\n=== 5. No JWT rejected ===")
s, b = req("POST", "/api/nodes/register-nodes/", nodes_payload)
print(f"  Status: {s}")
assert s in (401, 403)
print("  [PASS]")

# ── 6. Listowanie węzłów przez użytkownika ──
print("\n=== 6. List nodes (user JWT) ===")
s, b = req("GET", "/api/nodes/nodes/?device_id=2137", token=jan_access)
print(f"  Status: {s}, node count: {len(b.get('nodes', []))}")
assert s == 200
assert len(b["nodes"]) == 5
print("  [PASS]")

# ── 7. Blokada: inny user bez uprawnień nie widzi węzłów ──
print("\n=== 7. Unauthorized user cannot list nodes ===")
s, b2 = req("POST", "/api/accounts/register/",
            {"username": "ewa", "email": "ewa@x.com", "password": "SilneHaslo123"})
assert s == 201
ewa_access = b2["access"]
s, b = req("GET", "/api/nodes/nodes/?device_id=2137", token=ewa_access)
print(f"  Status: {s}")
assert s == 403
print("  [PASS]")

# ── 8. Brakujący device_id w query params ──
print("\n=== 8. Missing device_id param ===")
s, b = req("GET", "/api/nodes/nodes/", token=jan_access)
print(f"  Status: {s}")
assert s == 400
print("  [PASS]")

# ── 9. Walidacja: błędny device_type ──
print("\n=== 9. Invalid device_type ===")
bad_payload = {
    "device_id": "2137",
    "nodes": [{"node_id": "Pico_01", "gpio": 5, "device_type": "TOASTER"}],
}
s, b = req("POST", "/api/nodes/register-nodes/", bad_payload, token=device_access)
print(f"  Status: {s}")
assert s == 400
print("  [PASS]")

print("\n✅ All 9 node tests passed!")
