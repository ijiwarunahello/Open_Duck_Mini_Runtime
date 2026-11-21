import json
import threading
import urllib.error
import urllib.request

import pytest

from tools.bench.hardware import FakeHardware
from tools.bench.server import BenchState, make_server


class Resp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def json(self):
        return json.loads(self._body)


def post(base, action, body):
    req = urllib.request.Request(
        f"{base}/api/{action}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return Resp(r.status, r.read())
    except urllib.error.HTTPError as e:
        return Resp(e.code, e.read())


def read_first_sse_event(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        for raw in r:
            line = raw.decode().strip()
            if line.startswith("data: "):
                return json.loads(line[6:])
    raise AssertionError("no SSE event")


@pytest.fixture
def fake_hw():
    return FakeHardware()


@pytest.fixture
def server_url(fake_hw):
    srv = make_server(BenchState(fake_hw), 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
