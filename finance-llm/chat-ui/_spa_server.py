import http.server
import socketserver
import os
import threading

DIST = r"c:/LLMFinance/finance-llm/chat-ui/dist"

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIST, **kwargs)

    def do_GET(self):
        if self.path.startswith("/assets/"):
            return super().do_GET()
        if "." not in os.path.basename(self.path):
            self.path = "/"
        return super().do_GET()

    def log_message(self, fmt, *args):
        pass

if __name__ == "__main__":
    srv = socketserver.TCPServer(("127.0.0.1", 4174), Handler, bind_and_activate=False)
    srv.allow_reuse_address = True
    srv.server_bind()
    srv.server_activate()
    print("serving 127.0.0.1:4174 from", DIST)
    srv.serve_forever()
