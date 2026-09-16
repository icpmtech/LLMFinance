"""Servidor estático mínimo com fallback SPA (para validar o build do chat-ui)."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class SpaHandler(SimpleHTTPRequestHandler):
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
