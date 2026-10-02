"""Procura um endpoint/parametro de preco na API Kamatera."""

import json
import sys

sys.path.insert(0, r"c:\LLMFinance")
from _kam import call  # noqa: E402

CANDS = [
    "/service/server?info=1",
    "/service/server?info=1&datacenter=EU&cpu=1A&ram=1024&disk=5",
    "/service/server?price=1&datacenter=EU&cpu=1A&ram=1024&disk=5",
    "/service/server?pricing=1&datacenter=EU&cpu=1A&ram=1024&disk=5",
    "/service/server?cost=1&datacenter=EU&cpu=1A&ram=1024&disk=5",
    "/service/server?estimate=1&datacenter=EU&cpu=1A&ram=1024&disk=5",
    "/service/server?calc=1&datacenter=EU&cpu=1A&ram=1024&disk=5",
    "/service/price?datacenter=EU&cpu=1A&ram=1024&disk=5",
    "/service/pricing?datacenter=EU&cpu=1A&ram=1024&disk=5",
    "/service/account",
    "/service/account/info",
    "/service/user",
    "/service/billing",
]

for path in CANDS:
    st, txt = call("GET", path)
    txt = txt.replace("\n", " ")
    print("%-70s HTTP %-4s %s" % (path, st, txt[:220]))
    print()
