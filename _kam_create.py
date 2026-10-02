"""Cria um servidor Kamatera, espera pela conclusao e mostra os detalhes."""

import json
import sys
import time

sys.path.insert(0, r"c:\LLMFinance")
from _kam import json_call  # noqa: E402

NAME = sys.argv[1] if len(sys.argv) > 1 else "iq-os-edge-01"
DATACENTER = sys.argv[2] if len(sys.argv) > 2 else "EU-MD"
CPU = sys.argv[3] if len(sys.argv) > 3 else "1A"
RAM = int(sys.argv[4]) if len(sys.argv) > 4 else 2048
DISK = int(sys.argv[5]) if len(sys.argv) > 5 else 20
IMAGE = sys.argv[6] if len(sys.argv) > 6 else "EU-MD:6000C29549da189eaef6ea8a31001a34"
PASSWORD = sys.argv[7] if len(sys.argv) > 7 else "Iqos2026Kam"
PUBKEY = open(r"C:\Users\pedro.mourao.martins\.ssh\iqos_kamatera_ed25519.pub").read().strip()

payload = {
    "name": NAME,
    "password": PASSWORD,
    "passwordValidate": PASSWORD,
    "ssh-key": PUBKEY,
    "datacenter": DATACENTER,
    "image": IMAGE,
    "cpu": CPU,
    "ram": RAM,
    "disk": "size=%d" % DISK,
    "dailybackup": "no",
    "managed": "no",
    "network": "name=wan,ip=auto",
    "quantity": 1,
    "billingcycle": "hourly",
    "monthlypackage": "",
    "poweronaftercreate": "yes",
}
print("payload:", json.dumps(payload, indent=1))
st, resp = json_call("POST", "/service/server", payload)
print("HTTP", st, "resp:", json.dumps(resp))
if st not in (200, 201):
    raise SystemExit("falhou a criacao")

if isinstance(resp, dict):
    cmds = resp.get("commandIds") or []
    if resp.get("password"):
        print("password gerada:", resp["password"])
else:
    cmds = resp
if not cmds:
    raise SystemExit("sem command id")
cmd_id = cmds[0]
print("command id:", cmd_id)

deadline = time.time() + 600
while time.time() < deadline:
    st, q = json_call("GET", "/service/queue?id=%s" % cmd_id)
    if isinstance(q, list) and q:
        q = q[0]
        status = q.get("status")
        print("status:", status)
        if status in ("complete", "error"):
            print("log:\n" + str(q.get("log"))[:4000])
            break
    time.sleep(5)

time.sleep(5)
for attempt in range(20):
    st, info = json_call("POST", "/service/server/info", {"name": NAME})
    if isinstance(info, list) and info:
        print("server info:", json.dumps(info[0], indent=1))
        break
    print("a aguardar info... (HTTP %s)" % st)
    time.sleep(10)
