import json
import threading
import time
import urllib.request

from tools.duck_vision import booth_server, pi_stream
from tools.duck_vision.mjpeg import FrameSplitter, LatestFrame, multipart_chunk


def jpeg(tag: bytes) -> bytes:
    # Entropy data never contains a bare FF D9; FF 00 is byte stuffing.
    return b"\xff\xd8" + tag + b"\xff\x00\x12" + b"\xff\xd9"


def test_splitter_handles_chunk_boundaries_and_garbage():
    a, b = jpeg(b"A"), jpeg(b"B")
    stream = b"junk" + a + b"\r\n--x\r\n" + b
    s = FrameSplitter()
    frames = []
    for i in range(len(stream)):  # one byte at a time is the worst case
        frames += s.feed(stream[i : i + 1])
    assert frames == [a, b]


def test_splitter_reads_multipart_stream():
    frames = [jpeg(bytes([i])) for i in range(3)]
    s = FrameSplitter()
    assert s.feed(b"".join(multipart_chunk(f) for f in frames)) == frames


def test_rpicam_command_asks_camera_for_tiny_frames():
    cmd = pi_stream.rpicam_command(64, 48, 10, 80)
    assert cmd[:3] == ["nice", "-n", "10"]
    assert cmd[cmd.index("--width") + 1] == "64" and cmd[cmd.index("--height") + 1] == "48"
    assert cmd[cmd.index("--codec") + 1] == "mjpeg" and cmd[-2:] == ["-o", "-"]


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_booth_relays_pi_stream_and_pet(tmp_path):
    pi_latest = LatestFrame()
    pi = pi_stream.make_server(pi_latest, 0, host="127.0.0.1")
    pi_url = serve(pi)

    (tmp_path / "pet.json").write_text(json.dumps({"id": "duck", "spritesheetPath": "spritesheet.webp"}))
    (tmp_path / "spritesheet.webp").write_bytes(b"RIFFsheet")
    meta, sheet = booth_server.load_pet(str(tmp_path))
    booth_latest = LatestFrame()
    stop = threading.Event()
    threading.Thread(target=booth_server.pull_stream, args=(pi_url + "/stream.mjpg", booth_latest, stop, lambda m: None),
                     daemon=True).start()
    booth = booth_server.make_server(booth_latest, meta, sheet, 0)
    url = serve(booth)
    try:
        with urllib.request.urlopen(url + "/frame.jpg") as r:
            assert r.status == 204  # no frame yet

        def frame_relayed(f):
            pi_latest.put(f)  # keep publishing until the relay has connected
            return booth_latest.get()[1] == f

        wait_for(lambda: frame_relayed(jpeg(b"one")))
        with urllib.request.urlopen(url + "/frame.jpg") as r:
            assert r.read() == jpeg(b"one")
        with urllib.request.urlopen(url + "/pet.json") as r:
            assert json.load(r)["id"] == "duck"
        with urllib.request.urlopen(url + "/pet-sheet") as r:
            assert r.read() == b"RIFFsheet"
        with urllib.request.urlopen(url + "/") as r:
            assert b"duck" in r.read()
        with urllib.request.urlopen(url + "/static/app.js") as r:
            assert r.status == 200
    finally:
        stop.set()
        pi.shutdown()
        booth.shutdown()


def test_booth_stops_serving_a_stale_frame_when_the_pi_goes_away():
    # LatestFrame keeps the last frame forever; the page only notices a lost camera when
    # /frame.jpg stops returning images, so the booth must not replay an old one.
    now = [0.0]
    latest = LatestFrame(clock=lambda: now[0])
    booth = booth_server.make_server(latest, None, None, 0)
    url = serve(booth)
    try:
        latest.put(jpeg(b"last"))
        now[0] = booth_server.STALE_FRAME_S - 0.1
        with urllib.request.urlopen(url + "/frame.jpg") as r:
            assert r.status == 200 and r.read() == jpeg(b"last")
        now[0] = booth_server.STALE_FRAME_S + 0.1
        with urllib.request.urlopen(url + "/frame.jpg") as r:
            assert r.status == 204
    finally:
        booth.shutdown()


def test_booth_without_pet_returns_404():
    booth = booth_server.make_server(LatestFrame(), None, None, 0)
    url = serve(booth)
    try:
        try:
            urllib.request.urlopen(url + "/pet.json")
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        booth.shutdown()


def test_telemetry_relayed_from_walk_script_to_booth():
    import socket

    from mini_bdx_runtime.mini_bdx_runtime.telemetry import Telemetry

    robot = pi_stream.RobotState()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    stop = threading.Event()
    threading.Thread(target=pi_stream.listen_telemetry, args=(robot, udp, stop), daemon=True).start()
    pi = pi_stream.make_server(LatestFrame(), 0, host="127.0.0.1", robot=robot)
    pi_url = serve(pi)

    relay = booth_server.StateRelay()
    threading.Thread(target=booth_server.poll_state, args=(pi_url + "/state.json", relay, stop), daemon=True).start()
    booth = booth_server.make_server(LatestFrame(), None, None, 0, relay=relay)
    url = serve(booth)
    try:
        with urllib.request.urlopen(url + "/state.json") as r:
            assert json.load(r)["state"] is None

        tx = Telemetry(udp.getsockname(), rate_hz=1000)
        imu = {"accelero": [0.0, 0.0, 9.8], "gyro": [0.0, 0.0, 0.0]}

        def relayed():
            tx.send(False, [0.1, 0, 0, 0, 0, 0, 0], imu)
            return json.loads(relay.get())["state"] is not None

        wait_for(relayed)
        with urllib.request.urlopen(url + "/state.json") as r:
            body = json.load(r)
        assert body["state"]["cmd"][0] == 0.1 and body["state"]["paused"] is False
        assert body["age_s"] < 1.0
    finally:
        stop.set()
        pi.shutdown()
        booth.shutdown()
        udp.close()
