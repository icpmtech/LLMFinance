"""Página web de acompanhamento do backfill de embeddings dos contratos.

Serve, numa única página, os números que interessam a quem está a olhar para o
backfill: quantos já estão feitos, quantos faltam, a que ritmo vai, quanto tempo
ainda falta e o que resta por ano. Não precisa de Flask nem de tocar no backend
da aplicação — fala diretamente com o Elasticsearch e lê os ficheiros de estado
do próprio backfill.

    python logs/backfill_pagina.py            -> http://127.0.0.1:8013
    BACKFILL_PORTA=9000 python logs/backfill_pagina.py

Endpoints:
    GET /        a página (HTML, atualiza-se sozinha a cada 5 s)
    GET /dados   o JSON que a página consome (serve para integrar noutro sítio)
    GET /saude   verificação rápida
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from api import vector_service as vs  # noqa: E402

INDICE = "contratos"
PORTA = int(os.environ.get("BACKFILL_PORTA", "8013"))
LOG = RAIZ / "logs" / "_backfill_contratos.log"
PAUSA = RAIZ / "logs" / "_backfill.pausa"
AMOSTRAS = RAIZ / "logs" / "_backfill_pagina_amostras.json"

#: De quanto em quanto tempo se recalculam os anos (é a parte caro: agregação
#: `must_not exists` sobre 2,25 M documentos).
SEGUNDOS_ANOS = 60.0
#: Quantas amostras de contagem se guardam para estimar o ritmo (1 h a 5 s).
MAX_AMOSTRAS = 720
#: Janela mínima para estimar o ritmo. Tem de ser **maior do que a cadência das
#: gravações**: cada processo escreve 768 documentos a cada ~230 s, ou seja as
#: escritas vêm em rajada e uma janela de 60 s cai quase sempre num intervalo
#: sem nenhuma escrita, dando um ritmo de 0 (parecia que estava parado).
JANELA_MINIMA = float(os.environ.get("BACKFILL_JANELA", "300"))

_amostras: List[Tuple[float, int]] = []
_anos: Dict[str, Any] = {"ts": 0.0, "linhas": []}
_trava = threading.Lock()


#: Última leitura que correu bem. Se o Elasticsearch cair (já aconteceu: o Docker
#: reinicia e o processo do ES recusa ligações), a página continua a mostrar
#: estes números com a hora da leitura, em vez de ficar em branco ou dar 500.
_ultima: Dict[str, Any] = {"ts": 0.0, "total": None, "com": None, "erro": None}


def _contagens() -> Tuple[int, int, bool, str | None]:
    """(total, com_embedding, leitura_ok, erro). Duas contagens — é rápido.

    Se o ES não responder (ou devolver `None` por falta de configuração), devolve
    a última leitura boa e diz que está velha — nunca inventa números novos.
    """
    try:
        es = vs.get_es_client()
        if es is None:
            raise RuntimeError("cliente do Elasticsearch indisponível")
        total = es.count(index=INDICE).get("count", 0)
        com = es.count(index=INDICE, body={"query": {"exists": {"field": "embedding"}}}).get("count", 0)
    except Exception as erro:  # noqa: BLE001
        _ultima["erro"] = f"{type(erro).__name__}: {erro}"
        if _ultima["total"] is None:
            raise
        return int(_ultima["total"]), int(_ultima["com"] or 0), False, _ultima["erro"]
    _ultima.update({"ts": time.time(), "total": int(total), "com": int(com), "erro": None})
    return int(total), int(com), True, None


def _por_ano() -> List[Dict[str, Any]]:
    """Documentos por ano, com e sem embedding (agregação, por isso é cacheada)."""
    es = vs.get_es_client()
    if es is None:
        # Mensagem legível no log em vez do críptico "NoneType has no attribute 'search'".
        raise RuntimeError("Elasticsearch sem ligação")
    corpo = {
        "size": 0,
        "aggs": {
            "anos": {
                "terms": {"field": "Ano", "size": 30, "order": {"_key": "desc"}},
                "aggs": {
                    "com": {"filter": {"exists": {"field": "embedding"}}},
                    "sem": {"filter": {"bool": {"must_not": {"exists": {"field": "embedding"}}}}},
                },
            }
        },
    }
    resposta = es.search(index=INDICE, body=corpo)
    linhas = []
    for balde in resposta.get("aggregations", {}).get("anos", {}).get("buckets", []):
        total = int(balde.get("doc_count") or 0)
        com = int((balde.get("com") or {}).get("doc_count") or 0)
        linhas.append({"ano": balde.get("key"), "total": total, "com": com, "sem": total - com})
    return linhas


def _atualizar_anos() -> None:
    while True:
        try:
            linhas = _por_ano()
            with _trava:
                _anos["ts"] = time.time()
                _anos["linhas"] = linhas
        except Exception as erro:  # noqa: BLE001
            print(f"[anos] falhou: {type(erro).__name__}: {erro}", flush=True)
        time.sleep(SEGUNDOS_ANOS)


def _ritmo() -> Dict[str, Any]:
    """Ritmo (docs/s) e estimativa, a partir das amostras guardadas.

    A referência é a amostra **mais recente que já tenha pelo menos
    `JANELA_MINIMA` de idade** — dá o ritmo dos últimos minutos e não a média de
    todo o histórico. Enquanto não houver histórico suficiente devolve `None`:
    numa janela mais curta do que a cadência das gravações (~240 s) o número sai
    a 0 ou inflacionado, e mais vale não mostrar nada do que mostrar errado.
    """
    with _trava:
        amostras = list(_amostras)
    if len(amostras) < 2:
        return {"docs_s": None, "janela_s": None, "eta_h": None}
    agora_ts, agora_com = amostras[-1]
    referencia = None
    for ts, com in amostras[:-1]:
        if agora_ts - ts >= JANELA_MINIMA:
            referencia = (ts, com)
        else:
            break
    if referencia is None:
        return {"docs_s": None, "janela_s": round(agora_ts - amostras[0][0], 1), "eta_h": None}
    dt = agora_ts - referencia[0]
    docs = agora_com - referencia[1]
    if dt <= 0 or docs <= 0:
        return {"docs_s": None, "janela_s": round(dt, 1), "eta_h": None}
    return {"docs_s": docs / dt, "janela_s": round(dt, 1), "eta_h": None}


def _carregar_amostras() -> None:
    """Recupera as amostras do arranque anterior (a página reinicia sem perder o ritmo)."""
    try:
        guardadas = json.loads(AMOSTRAS.read_text(encoding="utf-8"))
        limite = time.time() - 3600
        with _trava:
            _amostras.extend((float(ts), int(com)) for ts, com in guardadas if float(ts) >= limite)
    except Exception:  # noqa: BLE001 - não haver histórico não é problema
        pass


def _guardar_amostras() -> None:
    try:
        with _trava:
            copia = list(_amostras[-MAX_AMOSTRAS:])
        AMOSTRAS.write_text(json.dumps(copia), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _cauda_log(n: int = 10) -> List[str]:
    try:
        linhas = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        return [linha for linha in linhas[-n:] if linha.strip()]
    except Exception:  # noqa: BLE001
        return []


def _dados() -> Dict[str, Any]:
    total, com, ok, erro = _contagens()
    agora = time.time()
    if ok:
        # Só amostras de leituras reais: se o ES falhar, uma amostra com a mesma
        # contagem faria o ritmo parecer 0 ("parado") quando é o ES que caiu.
        with _trava:
            _amostras.append((agora, com))
            if len(_amostras) > MAX_AMOSTRAS:
                del _amostras[: len(_amostras) - MAX_AMOSTRAS]
        _guardar_amostras()
    ritmo = _ritmo()
    sem = total - com
    hora = ritmo.get("docs_s")
    if hora:
        ritmo["eta_h"] = round(sem / hora / 3600, 1)
    with _trava:
        anos = list(_anos["linhas"])
        anos_ts = _anos["ts"]
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "total": total,
        "com": com,
        "sem": sem,
        "percent": round(100.0 * com / total, 2) if total else 0.0,
        "ritmo": ritmo,
        "pausa": PAUSA.exists(),
        "es": {
            "ok": ok,
            "erro": erro,
            "ts": datetime.fromtimestamp(_ultima["ts"]).isoformat(timespec="seconds") if _ultima["ts"] else None,
        },
        "anos": anos,
        "anos_ts": datetime.fromtimestamp(anos_ts).isoformat(timespec="seconds") if anos_ts else None,
        "historico": [{"ts": ts, "com": c} for ts, c in _amostras[-120:]],
        "log": _cauda_log(),
    }


PAGINA = """<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backfill de embeddings · IQ OS</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; padding:28px; background:#0b1220; color:#e6edf7;
         font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  h1 { margin:0 0 4px; font-size:20px; }
  .sub { color:#8b9bb4; font-size:12.5px; margin-bottom:20px; }
  .grelha { display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); margin-bottom:18px; }
  .cartao { background:#131c2e; border:1px solid #1f2b42; border-radius:12px; padding:14px 16px; }
  .rotulo { color:#8b9bb4; font-size:11px; letter-spacing:.06em; text-transform:uppercase; }
  .valor { font-size:26px; font-weight:600; margin-top:6px; font-variant-numeric:tabular-nums; }
  .nota { color:#8b9bb4; font-size:11.5px; margin-top:2px; }
  .barra { height:10px; background:#1b2740; border-radius:99px; overflow:hidden; margin:6px 0 18px; }
  .barra > div { height:100%; width:0%; background:linear-gradient(90deg,#22d3ee,#14b8a6); transition:width .4s; }
  table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
  th,td { text-align:right; padding:7px 10px; border-bottom:1px solid #1c2740; }
  th:first-child,td:first-child { text-align:left; }
  th { color:#8b9bb4; font-weight:500; font-size:11.5px; text-transform:uppercase; letter-spacing:.05em; }
  .linha-ano { position:relative; }
  pre { background:#0f1728; border:1px solid #1f2b42; border-radius:10px; padding:12px;
        overflow:auto; font-size:11.5px; color:#9fb0c9; max-height:260px; }
  .aviso { display:none; background:#3b2410; border:1px solid #7c4a12; color:#fcd9a8;
           padding:9px 12px; border-radius:10px; margin-bottom:16px; }
  .aviso.on { display:block; }
  .vivo { display:inline-block; width:7px; height:7px; border-radius:99px; background:#22c55e; margin-right:6px;
          animation:pulsa 1.6s infinite; }
  @keyframes pulsa { 50% { opacity:.25 } }
  canvas { width:100%; height:70px; display:block; }
</style>
</head>
<body>
  <h1><span class="vivo"></span>Backfill de embeddings · <code>contratos</code></h1>
  <div class="sub">Atualiza-se sozinha a cada 5 segundos. Fonte: contagens no Elasticsearch e ficheiros do backfill.</div>
  <div class="aviso" id="aviso">Foi pedida <b>pausa</b>: os processos acabam o lote em curso e saem. Para retomar:
    <code>backfill.ps1 -Acao continuar</code>.</div>
  <div class="aviso" id="aviso-es"><b>Elasticsearch sem resposta</b>: os números abaixo são os da última leitura
    (<span id="es-ts">–</span>). O backfill não consegue gravar enquanto isto durar — verificar o Docker.</div>

  <div class="grelha">
    <div class="cartao"><div class="rotulo">Com embedding</div><div class="valor" id="com">–</div><div class="nota" id="pct">–</div></div>
    <div class="cartao"><div class="rotulo">Em falta</div><div class="valor" id="sem">–</div><div class="nota" id="total">–</div></div>
    <div class="cartao"><div class="rotulo">Ritmo</div><div class="valor" id="ritmo">–</div><div class="nota" id="janela">–</div></div>
    <div class="cartao"><div class="rotulo">Falta</div><div class="valor" id="eta">–</div><div class="nota" id="hora">–</div></div>
  </div>

  <div class="barra"><div id="progresso"></div></div>

  <div class="cartao" style="margin-bottom:18px">
    <div class="rotulo" style="margin-bottom:8px">Ritmo recente (embeddings por leitura)</div>
    <canvas id="grafico" width="1200" height="70"></canvas>
  </div>

  <div class="cartao" style="margin-bottom:18px">
    <div class="rotulo" style="margin-bottom:8px">Por ano <span class="nota" id="anos-ts"></span></div>
    <table id="tabela"><thead><tr><th>Ano</th><th>Total</th><th>Com</th><th>Em falta</th><th>%</th></tr></thead><tbody></tbody></table>
  </div>

  <div class="cartao">
    <div class="rotulo" style="margin-bottom:8px">Últimas linhas do log</div>
    <pre id="log">–</pre>
  </div>

<script>
const numero = (n) => (n ?? 0).toLocaleString('pt-PT');
const comCasa = (n) => (n ?? 0).toLocaleString('pt-PT', { maximumFractionDigits: 1 });

function desenhar(historico) {
  const c = document.getElementById('grafico');
  const ctx = c.getContext('2d');
  const largura = c.width, altura = c.height;
  ctx.clearRect(0, 0, largura, altura);
  if (!historico || historico.length < 2) return;
  const valores = historico.map(p => p.com);
  const base = valores[0];
  const max = Math.max(...valores) - base || 1;
  ctx.strokeStyle = '#22d3ee'; ctx.lineWidth = 2; ctx.beginPath();
  valores.forEach((v, i) => {
    const x = (i / (valores.length - 1)) * largura;
    const y = altura - ((v - base) / max) * (altura - 6) - 3;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

async function atualizar() {
  try {
    const r = await fetch('/dados', { cache: 'no-store' });
    const d = await r.json();
    document.getElementById('com').textContent = numero(d.com);
    document.getElementById('sem').textContent = numero(d.sem);
    document.getElementById('pct').textContent = d.percent.toFixed(2) + '% de ' + numero(d.total);
    document.getElementById('total').textContent = 'total ' + numero(d.total);
    document.getElementById('progresso').style.width = Math.min(100, d.percent) + '%';
    const rt = d.ritmo || {};
    document.getElementById('ritmo').textContent = rt.docs_s ? comCasa(rt.docs_s) + ' docs/s' : '–';
    document.getElementById('janela').textContent = rt.janela_s ? 'medido em ' + rt.janela_s + ' s' : 'a recolher amostras…';
    document.getElementById('eta').textContent = rt.eta_h ? comCasa(rt.eta_h) + ' h' : '–';
    document.getElementById('hora').textContent = d.ts || '';
    document.getElementById('aviso').className = 'aviso' + (d.pausa ? ' on' : '');
    const es = d.es || {};
    document.getElementById('es-ts').textContent = es.ts || '–';
    document.getElementById('aviso-es').className = 'aviso' + (es.ok === false ? ' on' : '');
    document.getElementById('anos-ts').textContent = d.anos_ts ? '· atualizado ' + d.anos_ts : '';
    const corpo = document.querySelector('#tabela tbody');
    corpo.innerHTML = (d.anos || []).map(a => {
      const pct = a.total ? (100 * a.com / a.total).toFixed(1) : '0.0';
      return '<tr><td>' + a.ano + '</td><td>' + numero(a.total) + '</td><td>' + numero(a.com) +
             '</td><td>' + numero(a.sem) + '</td><td>' + pct + '%</td></tr>';
    }).join('') || '<tr><td colspan="5">a calcular…</td></tr>';
    document.getElementById('log').textContent = (d.log || []).join('\\n');
    desenhar(d.historico);
  } catch (e) {
    document.getElementById('hora').textContent = 'sem ligação ao servidor da página';
  }
}
atualizar();
setInterval(atualizar, 5000);
</script>
</body>
</html>
"""


class Gestor(BaseHTTPRequestHandler):
    server_version = "BackfillPagina/1.0"

    def _responder(self, estado: int, corpo: bytes, tipo: str) -> None:
        try:
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            # Sem cache: a página é para ver agora, não para guardar.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(corpo)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # O browser fecha ligações do ciclo de 5 s a meio da resposta — é normal
            # e não deve encher o log com tracebacks (nem derrubar nada).
            return

    def do_GET(self) -> None:  # noqa: N802 - API do http.server
        caminho = self.path.split("?")[0]
        if caminho in ("/", "/index.html"):
            self._responder(200, PAGINA.encode("utf-8"), "text/html; charset=utf-8")
        elif caminho == "/dados":
            try:
                corpo = json.dumps(_dados(), ensure_ascii=False).encode("utf-8")
            except Exception as erro:  # noqa: BLE001
                corpo = json.dumps({"erro": f"{type(erro).__name__}: {erro}"}, ensure_ascii=False).encode("utf-8")
                self._responder(500, corpo, "application/json; charset=utf-8")
                return
            self._responder(200, corpo, "application/json; charset=utf-8")
        elif caminho == "/saude":
            self._responder(200, b'{"ok":true}', "application/json; charset=utf-8")
        else:
            self._responder(404, b"nao encontrado", "text/plain; charset=utf-8")

    def log_message(self, formato: str, *args: Any) -> None:
        # O log do http.server é ruidoso; só interessa o arranque.
        return


def _autoteste() -> int:
    """Verifica o cálculo do ritmo sem esperar minutos por amostras reais.

    Simula a cadência real: as gravações vêm em rajada de ~4 600 documentos a
    cada ~240 s, portanto a janela tem de atravessar mais do que uma rajada.
    """
    global _amostras
    falhas = 0
    agora = time.time()
    # 30 min de amostras, +4 600 documentos a cada 240 s (~19 docs/s).
    with _trava:
        _amostras = []
        for segundo in range(0, 1801, 5):
            _amostras.append((agora - 1800 + segundo, 100000 + 4600 * (segundo // 240)))
    r = _ritmo()
    esperado = 4600 / 240
    if not r["docs_s"] or abs(r["docs_s"] - esperado) / esperado > 0.25:
        print(f"FALHA ritmo: {r} (esperado ~{esperado:.1f} docs/s)")
        falhas += 1
    else:
        print(f"ritmo OK: {r['docs_s']:.1f} docs/s numa janela de {r['janela_s']} s")

    # Amostras de menos de 2 minutos ainda não dão ritmo (evita dizer 0).
    with _trava:
        _amostras = [(agora - 60, 1000), (agora, 1400)]
    r = _ritmo()
    if r["docs_s"] is not None:
        print(f"FALHA janela curta: devia ser None, veio {r}")
        falhas += 1
    else:
        print("janela curta OK: sem ritmo enquanto não há histórico suficiente")

    # Sem evolução (backfill parado) também não pode inventar ritmo.
    with _trava:
        _amostras = [(agora - 900, 5000), (agora - 300, 5000), (agora, 5000)]
    r = _ritmo()
    if r["docs_s"] is not None:
        print(f"FALHA parado: devia ser None, veio {r}")
        falhas += 1
    else:
        print("parado OK: sem ritmo quando a contagem não muda")

    with _trava:
        _amostras = []
    print("autoteste: " + ("tudo OK" if not falhas else f"{falhas} falha(s)"))
    return 1 if falhas else 0


def main() -> int:
    if "--autoteste" in sys.argv:
        return _autoteste()
    _carregar_amostras()
    threading.Thread(target=_atualizar_anos, name="anos", daemon=True).start()
    print(f"página do backfill: http://127.0.0.1:{PORTA}  (Ctrl+C para parar)", flush=True)
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Gestor)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
