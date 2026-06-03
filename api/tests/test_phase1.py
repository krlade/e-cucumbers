"""
Phase 1 verification: auth, pairing tokens, device registration + factory reset.

Usage:
    1. Start the dev server:  python manage.py runserver
    2. Run tests:             python tests/test_phase1.py

NOTE: This script hits a live server — it creates real users/devices in the DB.
      Use a fresh DB or run `python manage.py flush` before testing.
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


# ── 1. Registration ──
print("=== 1. Register user ===")
s, b = req("POST", "/api/accounts/register/", {"username": "jan", "email": "jan@x.com", "password": "SilneHaslo123"})
print(f"  Status: {s}")
assert s == 201, f"Expected 201, got {s}: {b}"
assert "access" in b and "refresh" in b
jan_access = b["access"]
jan_refresh = b["refresh"]
print(f"  access: {jan_access[:30]}...")
print("  [PASS]")

# ── 2. Login ──
print("\n=== 2. Login ===")
s, b = req("POST", "/api/accounts/login/", {"username": "jan", "password": "SilneHaslo123"})
print(f"  Status: {s}")
assert s == 200
jan_access = b["access"]
print("  [PASS]")

# ── 3. Token refresh ──
print("\n=== 3. Token refresh ===")
s, b = req("POST", "/api/accounts/token/refresh/", {"refresh": jan_refresh})
print(f"  Status: {s}")
assert s == 200 and "access" in b
print("  [PASS]")

# ── 4. Me endpoint ──
print("\n=== 4. Me (authorized) ===")
s, b = req("GET", "/api/accounts/me/", token=jan_access)
print(f"  Status: {s}, user: {b.get('username')}")
assert s == 200 and b["username"] == "jan"
print("  [PASS]")

# ── 5. Me (unauthorized) ──
print("\n=== 5. Me (no token) ===")
s, b = req("GET", "/api/accounts/me/")
print(f"  Status: {s}")
assert s == 401
print("  [PASS]")

# ── 6. Generate pairing token (with JWT) ──
print("\n=== 6. Generate pairing token ===")
s, b = req("POST", "/api/nodes/pairing-token/", token=jan_access)
print(f"  Status: {s}")
print(f"  Token: {b.get('token')}, expires_in: {b.get('expires_in_seconds')}s")
assert s == 201
assert b["token"].startswith("TEMP-")
assert b["expires_in_seconds"] > 800  # ~15 min
pairing_token = b["token"]
print("  [PASS]")

# ── 7. Generate pairing token (no JWT) ──
print("\n=== 7. Pairing token (no auth) ===")
s, b = req("POST", "/api/nodes/pairing-token/")
print(f"  Status: {s}")
assert s in (401, 403)
print("  [PASS]")

# ── 8. Register device (valid token, first time) ──
print("\n=== 8. Register device ===")
s, b = req("POST", "/api/nodes/register-device/", {"device_id": "2137", "pairing_token": pairing_token})
print(f"  Status: {s}")
print(f"  device_id: {b.get('device_id')}, owner: {b.get('owner')}")
assert s == 200
assert b["device_id"] == "2137"
assert b["owner"] == "jan"
assert "access" in b and "refresh" in b
device_access_first = b["access"]
print("  [PASS]")

# ── 9. Reuse consumed token ──
print("\n=== 9. Reuse consumed token ===")
s, b = req("POST", "/api/nodes/register-device/", {"device_id": "9999", "pairing_token": pairing_token})
print(f"  Status: {s}")
assert s == 400
print("  [PASS]")

# ── 10. Register with non-existent token ──
print("\n=== 10. Non-existent token ===")
s, b = req("POST", "/api/nodes/register-device/", {"device_id": "9999", "pairing_token": "FAKE-0000"})
print(f"  Status: {s}")
assert s == 400
print("  [PASS]")

# ── 11. Factory reset — owner re-registers the same device ──
print("\n=== 11. Factory reset: owner re-registers device ===")
s, b = req("POST", "/api/nodes/pairing-token/", token=jan_access)
assert s == 201
repair_token = b["token"]
s, b = req("POST", "/api/nodes/register-device/", {"device_id": "2137", "pairing_token": repair_token})
print(f"  Status: {s}")
print(f"  device_id: {b.get('device_id')}, owner: {b.get('owner')}")
assert s == 200, f"Expected 200 on re-registration, got {s}: {b}"
assert b["device_id"] == "2137"
assert b["owner"] == "jan"
assert "access" in b and "refresh" in b
device_access_second = b["access"]
assert device_access_second != device_access_first, "New JWT should differ from the old one"
print("  [PASS]")

# ── 12. Factory reset — non-owner cannot hijack device ──
print("\n=== 12. Factory reset: non-owner hijack attempt ===")
# Register a second user
s, b = req("POST", "/api/accounts/register/", {"username": "hacker", "email": "hacker@x.com", "password": "SilneHaslo123"})
assert s == 201
hacker_access = b["access"]
# Hacker generates a pairing token
s, b = req("POST", "/api/nodes/pairing-token/", token=hacker_access)
assert s == 201
hacker_token = b["token"]
# Hacker tries to re-register jan's device
s, b = req("POST", "/api/nodes/register-device/", {"device_id": "2137", "pairing_token": hacker_token})
print(f"  Status: {s}")
assert s == 403, f"Expected 403 on unauthorized re-registration, got {s}: {b}"
print("  [PASS]")

# ── 13. Validation: short password ──
print("\n=== 13. Registration validation (short password) ===")
s, b = req("POST", "/api/accounts/register/", {"username": "bad", "email": "bad@x.com", "password": "short"})
print(f"  Status: {s}")
assert s == 400
print("  [PASS]")

print("\n[SUCCESS] All 13 tests passed!")
