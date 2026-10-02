"""Resumo de /service/server (opcoes de criacao de servidor)."""

import json
import sys

sys.path.insert(0, r"c:\LLMFinance")
from _kam import json_call  # noqa: E402

st, opt = json_call("GET", "/service/server")
print("HTTP", st)
if not isinstance(opt, dict):
    print(str(opt)[:2000])
    raise SystemExit(1)

print("top keys:", sorted(opt.keys()))
dcs = opt.get("datacenter") or {}
if isinstance(dcs, dict):
    print("datacenters:")
    for k, v in dcs.items():
        print("   %-8s %s" % (k, v))
else:
    print("datacenter:", dcs)

for key in ("cpu", "ram", "disk", "traffic", "billing", "networks"):
    val = opt.get(key)
    if isinstance(val, dict):
        print("\n%s keys: %s" % (key, sorted(val.keys())))
        for k, v in list(val.items())[:4]:
            s = json.dumps(v)
            print("   %-8s %s" % (k, s[:300]))
    else:
        print("\n%s: %s" % (key, json.dumps(val)[:300]))

imgs = opt.get("diskImages") or {}
if isinstance(imgs, dict):
    print("\ndiskImages datacenters:", sorted(imgs.keys()))
    for k, lst in list(imgs.items())[:1]:
        for item in (lst or [])[:200]:
            desc = (item.get("description") or "") + " " + (item.get("usageInfo") or "")
            if "ubuntu" in desc.lower() or "debian" in desc.lower():
                print("   %-10s %-34s %sGB %s" % (k, item.get("id"), item.get("sizeGB"), item.get("description")))
