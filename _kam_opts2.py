"""Descobre datacenters, tamanhos (com preco) e imagens disponiveis."""

import json
import sys

sys.path.insert(0, r"c:\LLMFinance")
from _kam import json_call  # noqa: E402

DC = sys.argv[1] if len(sys.argv) > 1 else None

st, dcs = json_call("GET", "/service/server?datacenter=1")
print("HTTP", st)
if isinstance(dcs, list):
    print("=== datacenters (%d) ===" % len(dcs))
    for d in dcs:
        print("  %-8s %-22s %s" % (d.get("id"), d.get("name"), d.get("subCategory")))
else:
    print(json.dumps(dcs)[:1000])
    raise SystemExit(1)

if not DC:
    raise SystemExit(0)

st, caps = json_call("GET", "/service/server?capabilities=1&datacenter=%s" % DC)
print("\nHTTP", st, "=== capabilities", DC, "===")
if isinstance(caps, dict):
    print("keys:", sorted(caps.keys()))
    for k in ("cpuTypes", "ramMB", "diskSizeGB", "monthlyTrafficPackage"):
        print(" ", k, "=", json.dumps(caps.get(k))[:600])
else:
    print(json.dumps(caps)[:800])

st, sizes = json_call("GET", "/service/server?sizes=1&datacenter=%s" % DC)
print("\nHTTP", st, "=== sizes", DC, "===")
if isinstance(sizes, list):
    print("n =", len(sizes))
    if sizes:
        print("keys:", sorted(sizes[0].keys()))
    sizes_sorted = sorted(
        sizes,
        key=lambda s: (s.get("priceMonthlyOn") or s.get("priceMonthly") or 9999),
    )
    for s in sizes_sorted[:25]:
        print(
            "  %-26s cpu=%-4s cores=%-3s ram=%-6s disk=%-4s priceM=%-8s priceH=%s"
            % (
                s.get("id"),
                s.get("cpuType"),
                s.get("cpuCores"),
                s.get("ramMB"),
                s.get("diskSizeGB"),
                s.get("priceMonthlyOn") or s.get("priceMonthly"),
                s.get("priceHourlyOn") or s.get("priceHourly"),
            )
        )
else:
    print(json.dumps(sizes)[:800])

st, imgs = json_call("GET", "/service/server?images=1&datacenter=%s" % DC)
print("\nHTTP", st, "=== images", DC, "(ubuntu/debian) ===")
if isinstance(imgs, list):
    print("n =", len(imgs))
    if imgs:
        print("keys:", sorted(imgs[0].keys()))
    for i in imgs:
        txt = (i.get("name", "") + " " + i.get("os", "")).lower()
        if "ubuntu" in txt or "debian" in txt:
            print(
                "  %-40s %-46s disk=%-4s ramMin=%s"
                % (i.get("id"), i.get("name"), i.get("osDiskSizeGB"), i.get("ramMBMin"))
            )
else:
    print(json.dumps(imgs)[:800])
