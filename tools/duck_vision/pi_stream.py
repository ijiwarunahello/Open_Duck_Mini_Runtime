"""Duck-vision sender (runs on the Pi, separate from the walk script).

Captures a tiny MJPEG stream with rpicam-vid and serves it over HTTP. The camera is asked
for 64x48 directly, so no full-resolution image exists anywhere (the camera looks up at
visitors). Nothing is written to disk.

    .venv/bin/python -m tools.duck_vision.pi_stream            # on the Pi
    python -m tools.duck_vision.pi_stream --fake DIR            # on a PC, cycles DIR/*.jpg

Routes: /stream.mjpg (multipart), /frame.jpg (latest), /state.json, /health (json).

/state.json relays the walk script's telemetry datagrams (`--telemetry 127.0.0.1:8092` or
DUCK_TELEMETRY on the walk script): paused flag, stick commands, accelerometer, gyro.
Stop it (Ctrl-C / kill) and the camera is released; the walk script is not involved.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.duck_vision.mjpeg import BOUNDARY, FrameSplitter, LatestFrame, multipart_chunk

RESTART_DELAY_S = 2.0


class RobotState:
    """Latest telemetry datagram from the walk script."""

    def __init__(self, clock=time.monotonic) -> None:
        self._lock = threading.Lock()
        self._state: dict | None = None
        self._at = 0.0
        self._clock = clock

    def put(self, state: dict) -> None:
        with self._lock:
            self._state, self._at = state, self._clock()

    def snapshot(self) -> dict:
        with self._lock:
            if self._state is None:
                return {"state": None, "age_s": None}
            return {"state": self._state, "age_s": round(self._clock() - self._at, 3)}


def listen_telemetry(robot: RobotState, sock: socket.socket, stop: threading.Event) -> None:
    sock.settimeout(1.0)
    while not stop.is_set():
        try:
            data = sock.recv(4096)
        except socket.timeout:
            continue
        except OSError:
            return
        try:
            robot.put(json.loads(data))
        except ValueError:
            pass


def rpicam_command(width: int, height: int, fps: int, quality: int) -> list[str]:
    return [
        "nice", "-n", "10",  # the 50 Hz walk loop has priority
        "rpicam-vid", "-n", "-t", "0",
        "--codec", "mjpeg", "--quality", str(quality),
        "--width", str(width), "--height", str(height),
        "--framerate", str(fps),
        "-o", "-",
    ]  # fmt: skip


def run_camera(latest: LatestFrame, cmd: list[str], stop: threading.Event, log=print) -> None:
    while not stop.is_set():
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as e:
            log(f"camera: {e}")
            stop.wait(RESTART_DELAY_S)
            continue
        splitter = FrameSplitter()
        try:
            while not stop.is_set():
                data = proc.stdout.read1(65536)
                if not data:
                    break
                for frame in splitter.feed(data):
                    latest.put(frame)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        if not stop.is_set():
            log("camera: rpicam-vid exited, restarting")
            stop.wait(RESTART_DELAY_S)


def run_fake(latest: LatestFrame, directory: str, fps: int, stop: threading.Event) -> None:
    files = sorted(glob.glob(os.path.join(directory, "*.jpg")))
    if not files:
        raise SystemExit(f"no .jpg in {directory}")
    frames = [open(f, "rb").read() for f in files]
    i = 0
    while not stop.is_set():
        latest.put(frames[i % len(frames)])
        i += 1
        stop.wait(1.0 / fps)


def make_server(latest: LatestFrame, port: int, host: str = "0.0.0.0",
                robot: RobotState | None = None) -> ThreadingHTTPServer:
    robot = robot or RobotState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/frame.jpg":
                _, frame = latest.get()
                if frame is None:
                    self._send(503, b"no frame yet", "text/plain")
                else:
                    self._send(200, frame, "image/jpeg")
            elif path == "/state.json":
                self._send(200, json.dumps(robot.snapshot()).encode(), "application/json")
            elif path == "/health":
                age = latest.age()
                self._send(200, json.dumps({"frame_age_s": age}).encode(), "application/json")
            elif path == "/stream.mjpg":
                self._stream()
            else:
                self._send(404, b"not found", "text/plain")

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            seq = -1
            try:
                while True:
                    new_seq, frame = latest.wait_newer(seq, timeout=5.0)
                    if new_seq == seq or frame is None:
                        continue  # camera stalled; keep the connection and wait
                    seq = new_seq
                    self.wfile.write(multipart_chunk(frame))
                    self.wfile.flush()
            except OSError:
                pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--width", type=int, default=64)
    ap.add_argument("--height", type=int, default=48)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument("--fake", metavar="DIR", help="cycle DIR/*.jpg instead of the camera")
    ap.add_argument("--telemetry-port", type=int, default=8092, help="UDP port the walk script sends to")
    args = ap.parse_args()

    latest = LatestFrame()
    stop = threading.Event()
    if args.fake:
        target = lambda: run_fake(latest, args.fake, args.fps, stop)  # noqa: E731
    else:
        cmd = rpicam_command(args.width, args.height, args.fps, args.quality)
        target = lambda: run_camera(latest, cmd, stop)  # noqa: E731
    threading.Thread(target=target, daemon=True).start()

    robot = RobotState()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", args.telemetry_port))
    threading.Thread(target=listen_telemetry, args=(robot, udp, stop), daemon=True).start()

    server = make_server(latest, args.port, robot=robot)
    print(f"duck-vision: http://0.0.0.0:{args.port}/stream.mjpg ({args.width}x{args.height} @ {args.fps} fps)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
