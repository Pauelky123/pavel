"""Exit a frozen worker so Docker/systemd can restore it; market outages retry normally."""
import logging
import os
import threading
import time


class Watchdog:
    def __init__(self, timeout=150, clock=time.monotonic, terminate=lambda: os._exit(70)):
        self.timeout = timeout
        self.clock = clock
        self.terminate = terminate
        self.last_progress = clock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='worker-watchdog')

    def touch(self):
        self.last_progress = self.clock()

    def check(self):
        if self.clock() - self.last_progress > self.timeout:
            logging.critical('Worker made no progress for %.0fs; exiting for supervisor restart', self.timeout)
            self.terminate()
            return False
        return True

    def run(self):
        while not self.stop.wait(max(.01, min(5, self.timeout/4))):
            if not self.check():
                return

    def start(self):
        self.touch()
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)
