"""Validação da importação dos Contratos Públicos do Portal Base (dados.gov.pt).

Corre contra o backend (por omissão `http://127.0.0.1:8000`, dentro do container)
e verifica, de ponta a ponta:

1. `GET  /base-impic/recursos`  — catálogo por ano e volumetria do índice;
2. `GET  /base-impic/formato/{ano}` — o **formato real** do ZIP do ano atual;
3. `GET  /base-impic/amostra/{ano}` — o que vai ser indexado (registos normalizados);
4. `POST /base-impic/importar`   — importação de ensaio (`--limite`), com progresso;
5. `POST /base-impic/cancelar/{ano}` — paragem a meio (ensaio separado).

Uso:
    python -u logs/_validar_base_impic.py [--base http://127.0.0.1:8000]
                                         [--ano 2026] [--limite 3000] [--sem-cancelar]

Corre tanto dentro do container (`/app/logs/...`, base 8000) como no anfitrião
(`--base http://127.0.0.1:8002`), por isso a raiz do projeto entra no `sys.path`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

FALHAS: List[str] = []


def verificar(condicao: bool, descricao: str, detalhe: Any = "") -> None:
    estado = "OK " if condicao else "FALHA"
    print(f"[{estado}] {descricao}" + (f" · {detalhe}" if detalhe != "" else ""))
    if not condicao:
        FALHAS.append(descricao)


def _por_ano(indice: Dict[str, Any], ano: int) -> int:
    return next((int(item["contratos"]) for item in indice.get("por_ano") or [] if int(item["ano"]) == ano), 0)


def _esperar(cliente: httpx.Client, ano: int, *, segundos: float = 900.0) -> Dict[str, Any]:
    inicio = time.time()
    ultimo: Dict[str, Any] = {}
    while time.time() - inicio < segundos:
        estado = cliente.get("/base-impic/estado").json()
        ultimo = (estado.get("trabalhos") or {}).get(str(ano)) or {}
        print(
            f"    {ultimo.get('estado')} · {ultimo.get('fase')} · lidos={ultimo.get('registos')}"
            f" novos={ultimo.get('indexados')} ja_existiam={ultimo.get('ignorados')}"
            f" erros={ultimo.get('erros')} lotes={ultimo.get('lotes')}"
        )
        if ultimo.get("estado") in ("concluido", "erro", "cancelado"):
            return ultimo
        time.sleep(3)
    return ultimo


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Valida a importação do Portal Base para o Elasticsearch.")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--ano", type=int, default=0, help="0 = ano atual do conjunto")
    parser.add_argument("--limite", type=int, default=3000, help="contratos a importar no ensaio")
    parser.add_argument("--sem-cancelar", action="store_true", help="não testar o cancelamento")
    args = parser.parse_args()

    from api import auth_service

    utilizadores = auth_service.list_users(1) or [{}]
    token = auth_service.create_session(utilizadores[0]).get("token", "")
    cliente = httpx.Client(base_url=args.base, timeout=900, headers={"Authorization": f"Bearer {token}"})

    # 1. Catálogo
    recursos = cliente.get("/base-impic/recursos")
    verificar(recursos.status_code == 200, "GET /base-impic/recursos responde 200", f"HTTP {recursos.status_code}")
    catalogo = recursos.json() if recursos.status_code == 200 else {}
    ano = args.ano or int(catalogo.get("ano_atual") or 0)
    zip_ano = next((r for r in catalogo.get("recursos") or [] if str(r.get("ano")) == str(ano) and r.get("formato") == "zip"), None)
    verificar(bool(zip_ano), f"o conjunto tem ZIP de {ano}", (zip_ano or {}).get("titulo", ""))
    verificar(len(catalogo.get("recursos") or []) >= 2, "catálogo com ficheiros por ano", f"{len(catalogo.get('recursos') or [])} recursos")
    indice_antes = catalogo.get("indice") or {}
    verificar(bool(indice_antes.get("disponivel")), "índice `contratos` acessível", f"total={indice_antes.get('total')}")
    print(f"    ano atual: {catalogo.get('ano_atual')} · anos: {catalogo.get('anos')}")
    print(f"    cache local: {len(catalogo.get('em_cache') or [])} ZIP")

    # 2. Formato do ZIP
    formato = cliente.get(f"/base-impic/formato/{ano}").json()
    verificar(formato.get("forma") == "array JSON", "forma do JSON detetada", formato.get("forma"))
    verificar(bool(formato.get("membro_json")), "membro JSON dentro do ZIP", formato.get("membro_json"))
    verificar((formato.get("total_campos") or 0) > 20, "campos por contrato", formato.get("total_campos"))
    verificar(formato.get("indice_destino") == "contratos", "índice de destino", formato.get("indice_destino"))
    print(f"    membro: {formato.get('membro_json')} · {round((formato.get('membro_bytes') or 0) / 1048576, 1)} MB descomprimido")
    print("    primeiros campos:", ", ".join(c["nome"] for c in (formato.get("campos") or [])[:8]))

    # 3. Amostra normalizada
    amostra = cliente.get(f"/base-impic/amostra/{ano}", params={"registos": 3}).json()
    itens = amostra.get("itens") or []
    verificar(len(itens) == 3, "amostra com 3 contratos normalizados", len(itens))
    verificar(all(i.get("idcontrato") for i in itens), "amostra com `idcontrato`", [i.get("idcontrato") for i in itens])
    for item in itens[:2]:
        print(f"    {item.get('idcontrato')} · {item.get('precoContratual')} € · {str(item.get('objectoContrato'))[:70]}")

    # 4. Importação de ensaio
    arranque = cliente.post("/base-impic/importar", json={"ano": ano, "limite": args.limite, "descarregar": True})
    verificar(arranque.status_code == 200, "POST /base-impic/importar aceito", f"HTTP {arranque.status_code}")
    if arranque.status_code != 200:
        print(arranque.text[:400])
        return 1
    print(f"    {arranque.json().get('mensagem')}")
    estado = _esperar(cliente, ano)
    verificar(estado.get("estado") == "concluido", "importação terminou sem erro", estado.get("mensagem"))
    verificar(int(estado.get("registos") or 0) == args.limite, "todos os registos pedidos foram lidos", estado.get("registos"))
    verificar(
        int(estado.get("indexados") or 0) + int(estado.get("ignorados") or 0) == args.limite,
        "cada contrato lido foi indexado ou ignorado (já existia)",
        f"{estado.get('indexados')} novos + {estado.get('ignorados')} já existiam",
    )
    verificar(int(estado.get("erros") or 0) == 0, "sem erros de indexação", estado.get("erros"))
    verificar(int(estado.get("lotes") or 0) >= 1, "indexação em lotes", f"{estado.get('lotes')} lote(s)")

    # 5. Repetir a importação: não pode acrescentar **nada**
    indice_depois = cliente.get("/base-impic/estado").json().get("indice") or {}
    repeticao = cliente.post("/base-impic/importar", json={"ano": ano, "limite": args.limite, "descarregar": False})
    verificar(repeticao.status_code == 200, "segunda importação aceita", f"HTTP {repeticao.status_code}")
    estado2 = _esperar(cliente, ano)
    verificar(estado2.get("estado") == "concluido", "segunda importação terminou", estado2.get("mensagem"))
    verificar(
        int(estado2.get("indexados") or 0) == 0,
        "segunda importação não indexa nada (só entra o que não existe)",
        f"novos={estado2.get('indexados')}",
    )
    verificar(
        int(estado2.get("ignorados") or 0) == args.limite,
        "os contratos repetidos foram contados como já existentes",
        f"já existiam={estado2.get('ignorados')} de {args.limite}",
    )
    indice_final = cliente.get("/base-impic/estado").json().get("indice") or {}
    verificar(
        _por_ano(indice_final, ano) == _por_ano(indice_depois, ano),
        f"repetir a importação não altera a contagem de {ano}",
        f"{_por_ano(indice_depois, ano)} → {_por_ano(indice_final, ano)}",
    )

    # 6. Cancelamento
    if not args.sem_cancelar:
        cliente.post("/base-impic/importar", json={"ano": ano, "limite": None, "descarregar": False})
        time.sleep(4)
        pedido = cliente.post(f"/base-impic/cancelar/{ano}")
        verificar(pedido.status_code == 200, "POST /base-impic/cancelar aceito", f"HTTP {pedido.status_code}")
        estado3 = _esperar(cliente, ano, segundos=600)
        verificar(estado3.get("estado") == "cancelado", "importação cancelada parou", estado3.get("estado"))

    print()
    if FALHAS:
        print(f"{len(FALHAS)} verificação(ões) falhada(s):")
        for item in FALHAS:
            print("  -", item)
        return 1
    print("Todas as verificações passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
