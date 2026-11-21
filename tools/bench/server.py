"""Bench server: streams module readings over SSE and accepts operations over a small JSON API.

Run on the Pi:  uv run python -m tools.bench.server
Run on a PC:    uv run python -m tools.bench.server --fake
"""

import argparse
import json
import math
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from tools.bench.hardware import EARS, LEDS, Hardware
from tools.bench.pins import IN_USE, RESERVED, ROLES, can_set_pull
from tools.bench.servo_logic import JOINTS, KP_CHOICES, GuardError, JogGuard, decode_status
from tools.bench.signals import EdgeLog, to_runtime_frame

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
LED_TIMEOUT_S = 30.0
EAR_HOLD_S = 0.5  # stop the software PWM after the ear has had time to reach its position (avoids jitter)
SSE_PERIOD_S = 0.1
FEET_PERIOD_S = 0.01
PINS_PERIOD_S = 0.5
SERVOS_PERIOD_S = 1.0
STATUS_PERIOD_S = 2.0
MAX_EAR_LIMIT = 1.0


class BenchState:
    def __init__(self, hw: Hardware, ear_limit: float = 0.5, clock=time.monotonic) -> None:
        self.hw = hw
        self.ear_limit = ear_limit
        self.clock = clock
        self.guard = JogGuard()
        self.edges = EdgeLog()
        self.imu_errors = 0
        self.led_until: dict[str, float] = {}
        self.ear_release_at: dict[str, float] = {}
        self.last_jpeg: bytes | None = None
        self._target: float | None = None
        self._clients = 0
        self._lock = threading.Lock()
        self._servo_lock = threading.Lock()
        self._cache: dict = {}
        self._cache_t: dict[str, float] = {}
        self._snap_json: str | None = None
        self._snap_t = -math.inf

    # --- clients -------------------------------------------------------
    def client_connected(self) -> None:
        with self._lock:
            self._clients += 1

    def client_disconnected(self) -> None:
        with self._lock:
            self._clients -= 1
            last = self._clients <= 0
            self._clients = max(self._clients, 0)
        if last:
            self.stop_all()

    def stop_all(self) -> None:
        with self._servo_lock:
            self.hw.stop_all()
        self.guard.active = None
        self._target = None
        self.led_until.clear()
        self.ear_release_at.clear()

    # --- periodic ------------------------------------------------------
    def poll_feet(self, now: float | None = None) -> None:
        t = time.time() if now is None else now  # wall clock so the log reads as time of day
        feet = self.hw.read_feet()
        for name, level in feet.items():
            self.edges.update(name, level, t)
        self._cache["feet"] = feet

    def tick(self) -> None:
        now = self.clock()
        for name, until in list(self.led_until.items()):
            if now >= until:
                del self.led_until[name]
                self.hw.set_led(name, 0)
        for side, at in list(self.ear_release_at.items()):
            if now >= at:
                del self.ear_release_at[side]
                self.hw.release_ear(side)

    def _every(self, key: str, period: float, fn):
        now = self.clock()
        if key not in self._cache or now - self._cache_t.get(key, -math.inf) >= period:
            self._cache[key] = fn()
            self._cache_t[key] = now
        return self._cache[key]

    def _read_pins(self) -> dict:
        return {
            str(bcm): {
                "func": s.func,
                "pull": s.pull,
                "level": s.level,
                "role": ROLES.get(bcm, ""),
                "can_pull": can_set_pull(bcm),
            }
            for bcm, s in self.hw.read_pins().items()
        }

    def _read_imu(self) -> dict:
        try:
            s = self.hw.read_imu()
        except Exception:
            self.imu_errors += 1
            return {"sample": None, "errors": self.imu_errors}
        norm = math.sqrt(sum(a * a for a in s.accel))
        return {
            "sample": {
                "sensor": s.accel,
                "runtime_false": to_runtime_frame(s.accel, False),
                "runtime_true": to_runtime_frame(s.accel, True),
                "gyro": s.gyro,
                "euler": s.euler,
                "norm": norm,
            },
            "errors": self.imu_errors,
        }

    def _read_servos(self) -> dict:
        try:
            with self._servo_lock:
                rows = self.hw.read_servos()
        except Exception as e:  # bus unplugged, timeout, ...
            prev = self._cache.get("servos", {}).get("rows", [])
            return {"rows": prev, "error": f"読み取りエラー: {e}"}
        return {
            "rows": [
                {**r.__dict__, "status_text": decode_status(r.status) if r.status is not None else []} for r in rows
            ],
            "error": None,
        }

    def snapshot(self) -> dict:
        self.tick()
        if "feet" not in self._cache:
            self.poll_feet()
        servos = self._every("servos", SERVOS_PERIOD_S, self._read_servos)
        now = self.clock()
        return {
            "status": self._every("status", STATUS_PERIOD_S, self.hw.pi_status),
            "pins": self._every("pins", PINS_PERIOD_S, self._read_pins),
            "feet": self._cache["feet"],
            "edges": [list(e) for e in self.edges.events[-50:]],
            "chatter": dict(self.edges.chatter),
            "imu": self._read_imu(),
            "servos": servos["rows"],
            "servo_error": servos["error"],
            "led_remaining": {k: max(0.0, v - now) for k, v in self.led_until.items()},
            "active_servo": self.guard.active,
            "ear_limit": self.ear_limit,
            "has_camera_image": self.last_jpeg is not None,
        }

    def snapshot_json(self) -> str:
        """Shared, rate-limited snapshot so several browsers do not multiply hardware reads."""
        with self._lock:
            now = self.clock()
            if self._snap_json is None or now - self._snap_t >= SSE_PERIOD_S * 0.9:
                self._snap_json = json.dumps(self.snapshot(), ensure_ascii=False)
                self._snap_t = now
            return self._snap_json

    # --- operations ----------------------------------------------------
    def handle(self, action: str, body: dict) -> dict:
        fn = getattr(self, f"_do_{action}", None)
        if fn is None:
            raise ValueError(f"不明な操作です: {action}")
        return fn(body) or {}

    def _do_stop_all(self, body: dict) -> None:
        self.stop_all()

    def _do_set_pull(self, body: dict) -> None:
        bcm, pull = int(body["bcm"]), str(body["pull"])
        if pull not in ("pu", "pd", "pn"):
            raise ValueError("pull は pu / pd / pn です")
        if bcm in RESERVED:
            raise ValueError(f"GPIO{bcm} は予約されたピンです ({ROLES.get(bcm, '')})")
        if bcm in IN_USE:
            raise ValueError(f"GPIO{bcm} は使用中のピンです ({ROLES.get(bcm, '')})")
        if not can_set_pull(bcm):
            raise ValueError(f"GPIO{bcm} は変更できません")
        self.hw.set_pull(bcm, pull)

    def _do_led(self, body: dict) -> None:
        name, duty = str(body["name"]), float(body["duty"])
        if name not in LEDS:
            raise ValueError(f"LED の名前が違います: {name}")
        duty = max(0.0, min(100.0, duty))
        self.hw.set_led(name, duty)
        if duty > 0:
            self.led_until[name] = self.clock() + LED_TIMEOUT_S
        else:
            self.led_until.pop(name, None)

    def _do_ear(self, body: dict) -> None:
        side, value = str(body["side"]), float(body["value"])
        if side not in EARS:
            raise ValueError(f"耳の左右が違います: {side}")
        value = max(-self.ear_limit, min(self.ear_limit, value))
        self.hw.set_ear(side, value, self.ear_limit)
        self.ear_release_at[side] = self.clock() + EAR_HOLD_S

    def _do_tone(self, body: dict) -> None:
        freq, volume = int(body.get("freq", 440)), float(body.get("volume", 0.1))
        if not 50 <= freq <= 5000:
            raise ValueError("周波数は 50〜5000 Hz です")
        self.hw.play_tone(freq, max(0.0, min(1.0, volume)))

    def _do_capture(self, body: dict) -> dict:
        self.last_jpeg = self.hw.capture_jpeg()
        return {"bytes": len(self.last_jpeg)}

    def _servo_id(self, body: dict) -> int:
        sid = int(body["id"])
        if sid not in JOINTS:
            raise ValueError(f"サーボ ID が違います: {sid}")
        return sid

    def _do_servo_torque_on(self, body: dict) -> dict:
        sid, kp = self._servo_id(body), int(body["kp"])
        if kp not in KP_CHOICES:
            raise GuardError(f"kp は {KP_CHOICES} から選んでください")
        with self._servo_lock:
            previous = self.guard.active
            if previous is not None and previous != sid:
                self.hw.servo_torque_off(previous)
            pos = self.hw.servo_torque_on(sid, kp)
            self.guard.torque_on(sid, pos, kp)
            self._target = pos
        self._cache_t.pop("servos", None)
        return {"position_rad": pos, "turned_off": previous if previous not in (None, sid) else None}

    def _do_servo_jog(self, body: dict) -> dict:
        sid, direction = self._servo_id(body), int(body["direction"])
        with self._servo_lock:
            current = self._target if self.guard.active == sid and self._target is not None else 0.0
            target = self.guard.jog(sid, current, direction)
            self.hw.servo_move(sid, target)
            self._target = target
        self._cache_t.pop("servos", None)
        return {"target_rad": target}

    def _do_servo_torque_off(self, body: dict) -> None:
        sid = self._servo_id(body)
        with self._servo_lock:
            self.hw.servo_torque_off(sid)
            self.guard.torque_off(sid)
            if self.guard.active is None:
                self._target = None
        self._cache_t.pop("servos", None)

    # --- background ----------------------------------------------------
    def start_feet_thread(self) -> threading.Thread:
        def loop():
            while True:
                try:
                    self.poll_feet()
                except Exception:
                    pass
                time.sleep(FEET_PERIOD_S)

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        return t


_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}


def make_server(state: BenchState, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _static(self, name: str) -> None:
            if name not in os.listdir(STATIC_DIR):
                self._send(404, b"not found", "text/plain")
                return
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                body = f.read()
            self._send(200, body, _CONTENT_TYPES.get(os.path.splitext(name)[1], "application/octet-stream"))

        def do_GET(self):
            path = unquote(self.path.split("?", 1)[0])
            if path == "/":
                self._static("index.html")
            elif path.startswith("/static/"):
                self._static(path[len("/static/"):])
            elif path == "/camera.jpg":
                if state.last_jpeg is None:
                    self._send(404, b"no image", "text/plain")
                else:
                    self._send(200, state.last_jpeg, "image/jpeg")
            elif path == "/events":
                self._events()
            else:
                self._send(404, b"not found", "text/plain")

        def _events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            state.client_connected()
            try:
                while True:
                    self.wfile.write(f"data: {state.snapshot_json()}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(SSE_PERIOD_S)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                state.client_disconnected()

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if not path.startswith("/api/"):
                self._send(404, b"not found", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                result = state.handle(path[len("/api/"):], body)
            except (GuardError, ValueError, KeyError, TypeError) as e:
                msg = f"必要な値がありません: {e}" if isinstance(e, KeyError) else str(e)
                self._json(400, {"ok": False, "error": msg})
                return
            except Exception as e:  # hardware failure
                self._json(500, {"ok": False, "error": f"ハードウェアのエラー: {e}"})
                return
            self._json(200, {"ok": True, **result})

    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    return srv


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Open Duck bench: module-by-module checks in the browser")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--fake", action="store_true", help="ハードウェアなしで作り物の値を使う")
    p.add_argument("--ear-limit", type=float, default=0.5, help="耳の可動範囲 (最大 1.0)")
    args = p.parse_args(argv)
    if not 0 < args.ear_limit <= MAX_EAR_LIMIT:
        print(f"--ear-limit は 0 より大きく {MAX_EAR_LIMIT} 以下にしてください", file=sys.stderr)
        return 2

    if args.fake:
        from tools.bench.hardware import FakeHardware

        hw: Hardware = FakeHardware()
    else:
        from tools.bench.preflight import find_conflicts

        conflicts = find_conflicts()
        if conflicts:
            print("起動しません:", *conflicts, sep="\n  ", file=sys.stderr)
            return 1
        from tools.bench.real_hardware import RealHardware

        hw = RealHardware()

    state = BenchState(hw, ear_limit=args.ear_limit)
    srv = make_server(state, args.port)
    state.start_feet_thread()

    def shutdown(signum, frame):
        state.stop_all()
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    print(f"bench: http://0.0.0.0:{args.port}/ {'(fake)' if args.fake else ''}")
    try:
        srv.serve_forever()
    finally:
        state.stop_all()
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
