import board
import digitalio
import random
import time
from threading import Thread, Event

LEFT_EYE_PIN = board.D24
RIGHT_EYE_PIN = board.D23


# Cycled with cycle_mode() (RB on the controller in the walk script).
MODES = ("blink", "on", "off")


class Eyes:
    def __init__(self, blink_duration=0.1, min_interval=1.0, max_interval=4.0):
        self.left_eye = digitalio.DigitalInOut(LEFT_EYE_PIN)
        self.left_eye.direction = digitalio.Direction.OUTPUT

        self.right_eye = digitalio.DigitalInOut(RIGHT_EYE_PIN)
        self.right_eye.direction = digitalio.Direction.OUTPUT

        self.blink_duration = blink_duration
        self.min_interval = min_interval
        self.max_interval = max_interval

        self.mode = MODES[0]
        self._stop_event = Event()
        # Set on a mode change or stop, so that the thread does not wait for
        # the end of the current blink interval.
        self._wake = Event()
        self._thread = Thread(target=self.run, daemon=True)
        self._thread.start()

    def _set_eyes(self, state):
        self.left_eye.value = state
        self.right_eye.value = state

    def cycle_mode(self):
        self.mode = MODES[(MODES.index(self.mode) + 1) % len(MODES)]
        self._wake.set()
        return self.mode

    def run(self):
        try:
            while not self._stop_event.is_set():
                self._wake.clear()
                if self.mode == "blink":
                    self._set_eyes(False)
                    time.sleep(self.blink_duration)
                    if self.mode != "blink" or self._stop_event.is_set():
                        continue
                    self._set_eyes(True)
                    self._wake.wait(random.uniform(self.min_interval, self.max_interval))
                else:
                    self._set_eyes(self.mode == "on")
                    self._wake.wait()
        except Exception as err:
            print(f"Error in eye thread: {err}")
            self._stop_event.set()

    def stop(self):
        self._stop_event.set()
        self._wake.set()
        self._thread.join()
        self._set_eyes(False)
        self.left_eye.deinit()
        self.right_eye.deinit()


if __name__ == "__main__":
    e = Eyes()
    try:
        while True:
            time.sleep(1)
    finally:
        e.stop()

