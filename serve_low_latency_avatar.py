from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import sleep
from typing import Dict, Tuple


_SERVERS: Dict[Tuple[Path, int], ThreadingHTTPServer] = {}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def start_server(port: int = 8765, directory: str | Path | None = None) -> str:
    base_dir = Path(directory or ".").resolve()
    key = (base_dir, port)

    if key not in _SERVERS:
        handler = partial(QuietHandler, directory=str(base_dir))
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        _SERVERS[key] = server

    return f"http://127.0.0.1:{port}"


if __name__ == "__main__":
    url = start_server()
    print(f"Serving low-latency avatar demo at {url}/low_latency_avatar_demo.html")

    try:
        while True:
            sleep(3600)
    except KeyboardInterrupt:
        pass
