"""Servidor estático mínimo com fallback SPA (para validar o build do chat-ui)."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class SpaHandler(SimpleHTTPRequestHandler):
    """Serve o `dist/` com fallback SPA.

    Cabeçalhos de cache: o HTML (e o service worker) **nunca** ficam em cache —
    senão o browser continua a pedir o bundle antigo depois de um novo `build`
    (o `index.html` referencia ficheiros com hash). Os `/assets/*` com hash são
    imutáveis e podem ficar em cache longa.
    """

    def end_headers(self):
        name = Path(self.path.split("?")[0]).name
        if name.endswith(".html") or name in ("", "/", "sw.js", "manifest.webmanifest"):
            self.send_header("Cache-Control", "no-store, must-revalidate")
        elif "/assets/" in self.path and "." in name:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        super().end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        if not Path(path).exists() and "." not in Path(self.path).name:
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, *args):  # silencia o log
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, default=5175)
    args = parser.parse_args()
    handler = partial(SpaHandler, directory=args.root)
    ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
