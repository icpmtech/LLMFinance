"""Sonda temporária: compra o Relatório de Benchmark e confirma a entrega do PDF.

Faz o percurso real, por HTTP, contra o backend em execução:
encomenda → pagamento (backoffice) → PDF gerado → recibo com o link → download.
"""
import json
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, r"C:\LLMFinance\finance-llm")

BASE = "http://127.0.0.1:8002"
SLUG = "relatorio-benchmark-portugal-espanha-franca"
EMAIL = "prova.benchmark@exemplo.pt"


def call(path, payload=None, method=None, token=""):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method or ("POST" if data else "GET"))
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def encomenda_da_prova():
    with open(r"C:\LLMFinance\finance-llm\data\shop\shop.json", encoding="utf-8") as fh:
        dados = json.load(fh)
    for ordem in dados["orders"]:
        if str((ordem.get("customer") or {}).get("email") or "") == EMAIL:
            return ordem
    return None


def main():
    from api import auth_service as auth

    ordem = encomenda_da_prova()
    if ordem is None:
        print("sem encomenda de prova: correr primeiro o checkout")
        return 1
    print("encomenda:", ordem["number"], ordem["id"], "| estado:", ordem["status"], "| ficheiros:", len(ordem.get("files") or []))

    user = auth.get_user_by_email("teste@iqos.local")
    sessao = auth.create_session(user, user_agent="probe-benchmark")
    token = sessao["token"]
    try:
        if not ordem.get("files"):
            estado, corpo, _ = call(f"/shop/orders/{ordem['id']}/payment", {"method": "mbway", "status": "pago"}, token=token)
            texto_corpo = corpo.decode("utf-8", "replace")
            print("pagamento:", estado, "ok" if estado < 400 else texto_corpo[:300])

        estado, corpo, _ = call(f"/shop/orders/{ordem['id']}", token=token)
        ficheiro = (json.loads(corpo).get("files") or [{}])[0] if estado == 200 else {}
        print("ficheiro na encomenda:", json.dumps(ficheiro, ensure_ascii=False))

        estado, html, _ = call(f"/loja/encomenda/{ordem['number']}?email={EMAIL}")
        texto = html.decode("utf-8", "replace")
        print("recibo:", estado, len(texto), "bytes | bloco de relatórios:", "Os seus relatórios" in texto)
        ligacao = re.search(r'href="(/loja/encomenda/[^"]+ficheiros/[^"]+)"', texto)
        print("link no recibo:", ligacao.group(1) if ligacao else "AUSENTE")

        if ligacao:
            estado, pdf, cabecalhos = call(ligacao.group(1))
            print("download:", estado, cabecalhos.get("content-type"), len(pdf), "bytes | PDF:", pdf[:5] == b"%PDF-")
            estado, _, _ = call(ligacao.group(1).replace(EMAIL, "intruso@exemplo.pt"))
            print("download com email errado:", estado)
            with open(r"C:\LLMFinance\_benchmark_loja_prova.pdf", "wb") as fh:
                fh.write(pdf)
            print("PDF guardado para inspeção")
    finally:
        auth.revoke_session(sessao["session"]["id"])
        print("sessão de prova revogada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
