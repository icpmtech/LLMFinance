"""Sonda: o que a API pública da Vortal devolve por aviso (documentos)."""

from __future__ import annotations

import json
import sys

import httpx

BASE = "https://community.vortal.biz"


def main() -> int:
    token_uid = sys.argv[1]
    with httpx.Client(timeout=40, headers={"User-Agent": "Mozilla/5.0 (compatible; IQOS/1.0)"}) as c:
        if token_uid.upper().startswith("PT"):
            uid = token_uid
            dados = None
        else:
            r = c.get(
                f"{BASE}/public/api/PublicTenderDocuments/GetPublicTenderInformation",
                params={"uniqueIdentifierEncrypted": token_uid, "languageCode": "pt-PT"},
            )
            print("info status", r.status_code, "len", len(r.text))
            dados = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
            uid = ((dados or {}).get("contractNoticeUrl") or "").strip()
            print("uid", repr(uid))
            print("info keys", sorted((dados or {}).keys()))
            ti = (dados or {}).get("tenderInformation") or {}
            print("tenderIsPublished", ti.get("tenderIsPublished"), "langs", ti.get("languages"))
            dl = (dados or {}).get("documentList")
            print("documentList", json.dumps(dl, ensure_ascii=False)[:800] if dl is not None else None)

        if uid:
            for caminho in (
                f"/public/api/ContractNoticeDetail/GetContractNoticeDocuments?contractNoticeUId={uid}",
                f"/public/api/ContractNoticeDetail/GetContractNoticeDocuments?contractNoticeUId={uid}&languageCode=pt-PT",
            ):
                r = c.get(BASE + caminho)
                print("---", caminho.split("?")[1], "->", r.status_code, r.headers.get("content-type"))
                print(r.text[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
