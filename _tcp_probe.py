import socket
import time

HOST = "45.147.251.188"
PORT = 22

for i in range(3):
    t0 = time.time()
    try:
        s = socket.create_connection((HOST, PORT), timeout=15)
        dt = time.time() - t0
        print("tentativa %d: TCP OK em %.2fs (peer=%s)" % (i + 1, dt, s.getpeername()))
        s.close()
    except Exception as exc:  # noqa: BLE001
        dt = time.time() - t0
        print("tentativa %d: FALHA em %.2fs -> %r" % (i + 1, dt, exc))
    time.sleep(1)
