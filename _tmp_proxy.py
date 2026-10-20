"""Proxy temporário de validação: /api/* -> backend novo (8021), restante -> 8021."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _proxy(self):
        caminho = self.path
        if caminho.startswith("/api/"):
            caminho = caminho[4:]
        elif caminho == "/api":
            caminho = "/"
        comprimento = int(self.headers.get("Content-Length") or 0)
        corpo = self.rfile.read(comprimento) if comprimento else None
        cabecalhos = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in ("host", "connection", "accept-encoding", "content-length")
        }
        ligacao = http.client.HTTPConnection("127.0.0.1", 8021, timeout=180)
        ligacao.request(self.command, caminho, body=corpo, headers=cabecalhos)
        resposta = ligacao.getresponse()
        dados = resposta.read()
        self.send_response(resposta.status)
        for chave, valor in resposta.getheaders():
            if chave.lower() in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                continue
            self.send_header(chave, valor)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(dados)

    do_GET = _proxy
    do_POST = _proxy
    do_PUT = _proxy
    do_PATCH = _proxy
    do_DELETE = _proxy
    do_HEAD = _proxy

    def log_message(self, formato, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 4191), Handler).serve_forever()
