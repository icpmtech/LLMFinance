import json
import sys
import urllib.request
import urllib.error

BASE = "https://sabemos.studio"
EMAIL = "teste@teste.com"
PASSWORD = "teste123"

# Login
req = urllib.request.Request(
    f"{BASE}/api/auth/login",
    data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=15) as r:
    login = json.loads(r.read().decode("utf-8"))

token = login["token"]
print("token", token[:20])

# Get profile
req = urllib.request.Request(
    f"{BASE}/api/auth/me",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(req, timeout=15) as r:
    me = json.loads(r.read().decode("utf-8"))

pages = me["preferences"].get("iframe_pages", [])
hermes = next(p for p in pages if p["id"] == "iqos-hermes-agent")
print("before", hermes["url"])
hermes["url"] = "https://sabemos.studio/hermes-agent/"

# Update profile
patch = {"preferences": {"iframe_pages": pages}}
req = urllib.request.Request(
    f"{BASE}/api/auth/me",
    data=json.dumps(patch).encode("utf-8"),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    method="PATCH",
)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        update = json.loads(r.read().decode("utf-8"))
    print("update status", r.status)
except urllib.error.HTTPError as e:
    update = json.loads(e.read().decode("utf-8"))
    print("update error status", e.code, "body", update)

# Verify
req = urllib.request.Request(
    f"{BASE}/api/auth/me",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(req, timeout=15) as r:
    me2 = json.loads(r.read().decode("utf-8"))

hermes2 = next(p for p in me2["preferences"]["iframe_pages"] if p["id"] == "iqos-hermes-agent")
print("after", hermes2["url"])
