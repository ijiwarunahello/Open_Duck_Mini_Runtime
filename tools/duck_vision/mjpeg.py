"""Split a raw MJPEG byte stream (concatenated JPEGs) into frames, and serve frames to many readers.

In JPEG entropy-coded data every 0xFF is followed by 0x00 (byte stuffing), so 0xFFD9 only
appears as the end-of-image marker. rpicam-vid MJPEG frames carry no EXIF thumbnail.
"""

from __future__ import annotations  # the booth Mac may run an older system python3

import threading
import time

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
MAX_BUFFER = 2 * 1024 * 1024  # drop garbage rather than grow without bound


class FrameSplitter:
    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf += data
        frames = []
        while True:
            start = self._buf.find(SOI)
            if start < 0:
                keep_ff = self._buf[-1:] == b"\xff"  # first half of a split SOI marker
                self._buf.clear()
                if keep_ff:
                    self._buf += b"\xff"
                break
            end = self._buf.find(EOI, start + 2)
            if end < 0:
                if start:
                    del self._buf[:start]
                break
            frames.append(bytes(self._buf[start : end + 2]))
            del self._buf[: end + 2]
        if len(self._buf) > MAX_BUFFER:
            self._buf.clear()
        return frames


class LatestFrame:
    """Holds the newest frame; readers can wait for the next one."""

    def __init__(self, clock=time.monotonic) -> None:
        self._cond = threading.Condition()
        self._frame: bytes | None = None
        self._seq = 0
        self._at = 0.0
        self._clock = clock

    def put(self, frame: bytes) -> None:
        with self._cond:
            self._frame = frame
            self._seq += 1
            self._at = self._clock()
            self._cond.notify_all()

    def get(self) -> tuple[int, bytes | None]:
        with self._cond:
            return self._seq, self._frame

    def age(self) -> float | None:
        with self._cond:
            return None if self._frame is None else self._clock() - self._at

    def wait_newer(self, seq: int, timeout: float) -> tuple[int, bytes | None]:
        with self._cond:
            self._cond.wait_for(lambda: self._seq != seq, timeout=timeout)
            return self._seq, self._frame


BOUNDARY = "duckframe"


def multipart_chunk(frame: bytes) -> bytes:
    head = f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n".encode()
    return head + frame + b"\r\n"
