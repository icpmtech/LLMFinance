"""Cliente minimo da API Kamatera (uso interno de deploy)."""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

import os

BASE = os.environ.get("KAM_BASE", "https://cloudcli.cloudwm.com")
CID = "857154af5cc5614aa80541c9a065d1b0"
SEC = "0ac5c2f150617ed277b3764fa7b0893e"


def call(method, path, data=None, form=False, timeout=180):
    url = BASE + path
    headers = {"AuthClientId": CID, "AuthSecret": SEC}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, "ERROR: %r" % (exc,)


def json_call(method, path, data=None, form=False):
    status, text = call(method, path, data=data, form=form)
    try:
        return status, json.loads(text)
    except Exception:  # noqa: BLE001
        return status, text


if __name__ == "__main__":
    method_ = sys.argv[1]
    path_ = sys.argv[2]
    payload = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    is_form = len(sys.argv) > 4 and sys.argv[4] == "form"
    st, val = json_call(method_, path_, payload, form=is_form)
    print("HTTP", st)
    if isinstance(val, str):
        print(val[:8000])
    else:
        print(json.dumps(val, indent=1)[:8000])
