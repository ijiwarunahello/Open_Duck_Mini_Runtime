"""Duck-vision booth page (runs on the booth Mac, Python standard library only).

Pulls the Pi's tiny MJPEG stream and serves the full-screen page: the duck's face (a Codex
pet spritesheet) on the left and "the world as the duck sees it" on the right.

    python3 -m tools.duck_vision.booth_server --pet ~/.codex/pets/<pet-id>
    python3 -m tools.duck_vision.booth_server --pi http://192.168.0.112:8091

Open http://localhost:8090 in a browser and click once (browsers only allow sound after a
click). Frames stay in memory; nothing is saved.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.duck_vision.mjpeg import FrameSplitter, LatestFrame

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".webp": "image/webp",
}
RECONNECT_DELAY_S = 2.0
STATE_PERIOD_S = 0.1


class StateRelay:
    """Latest /state.json from the Pi, polled in the background."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._body = b'{"state": null, "age_s": null}'

    def put(self, body: bytes) -> None:
        with self._lock:
            self._body = body

    def get(self) -> bytes:
        with self._lock:
            return self._body


def poll_state(url: str, relay: StateRelay, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                relay.put(r.read())
        except OSError:
            relay.put(b'{"state": null, "age_s": null}')
            stop.wait(RECONNECT_DELAY_S)
            continue
        stop.wait(STATE_PERIOD_S)


def pull_stream(url: str, latest: LatestFrame, stop: threading.Event, log=print) -> None:
    """Keep reading the Pi's /stream.mjpg; reconnect forever (the Pi or Wi-Fi may come and go)."""
    connected = False
    while not stop.is_set():
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if not connected:
                    log(f"camera: connected to {url}")
                    connected = True
                splitter = FrameSplitter()
                while not stop.is_set():
                    data = r.read1(65536) if hasattr(r, "read1") else r.read(4096)
                    if not data:
                        break
                    for frame in splitter.feed(data):
                        latest.put(frame)
        except OSError as e:
            if connected:
                log(f"camera: lost ({e})")
            connected = False
        stop.wait(RECONNECT_DELAY_S)


def load_pet(pet_dir: str | None) -> tuple[dict | None, str | None]:
    """Return (pet.json contents, spritesheet path) or (None, None) when no pet is configured."""
    if not pet_dir:
        return None, None
    pet_dir = os.path.expanduser(pet_dir)
    with open(os.path.join(pet_dir, "pet.json"), encoding="utf-8") as f:
        meta = json.load(f)
    sheet = os.path.join(pet_dir, meta.get("spritesheetPath", "spritesheet.webp"))
    if not os.path.isfile(sheet):
        raise SystemExit(f"spritesheet not found: {sheet}")
    return meta, sheet


def make_server(latest: LatestFrame, pet_meta: dict | None, pet_sheet: str | None, port: int,
                host: str = "127.0.0.1", relay: StateRelay | None = None) -> ThreadingHTTPServer:
    relay = relay or StateRelay()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: str) -> None:
            with open(path, "rb") as f:
                body = f.read()
            self._send(200, body, CONTENT_TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._file(os.path.join(STATIC_DIR, "index.html"))
            elif path.startswith("/static/") and path[len("/static/"):] in os.listdir(STATIC_DIR):
                self._file(os.path.join(STATIC_DIR, path[len("/static/"):]))
            elif path == "/frame.jpg":
                _, frame = latest.get()
                if frame is None:
                    self._send(204, b"", "image/jpeg")
                else:
                    self._send(200, frame, "image/jpeg")
            elif path == "/state.json":
                self._send(200, relay.get(), CONTENT_TYPES[".json"])
            elif path == "/status.json":
                self._send(200, json.dumps({"frame_age_s": latest.age()}).encode(), CONTENT_TYPES[".json"])
            elif path == "/pet.json":
                if pet_meta is None:
                    self._send(404, b"no pet", "text/plain")
                else:
                    self._send(200, json.dumps(pet_meta).encode(), CONTENT_TYPES[".json"])
            elif path == "/pet-sheet" and pet_sheet:
                self._file(pet_sheet)
            else:
                self._send(404, b"not found", "text/plain")

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pi", default="http://ducktronics.local:8091", help="base URL of pi_stream")
    ap.add_argument("--pet", metavar="DIR", help="Codex pet folder (pet.json + spritesheet)")
    ap.add_argument("--port", type=int, default=8090)
    args = ap.parse_args()

    pet_meta, pet_sheet = load_pet(args.pet)
    latest = LatestFrame()
    stop = threading.Event()
    threading.Thread(target=pull_stream, args=(args.pi.rstrip("/") + "/stream.mjpg", latest, stop),
                     daemon=True).start()
    relay = StateRelay()
    threading.Thread(target=poll_state, args=(args.pi.rstrip("/") + "/state.json", relay, stop),
                     daemon=True).start()
    server = make_server(latest, pet_meta, pet_sheet, args.port, relay=relay)
    print(f"duck-vision booth: http://localhost:{args.port}  (camera {args.pi}, pet {args.pet or 'none'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
