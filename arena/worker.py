"""Independent 24/7 paper worker. The website never starts or drives trading."""
import logging
import os
import random
import signal
import threading
import time
import uuid
from .market import CoinbaseMarket
from .store import Store

log = logging.getLogger('arena.worker')


class Worker:
    def __init__(self, store=None, market=None, clock=time.time, rng=random.random):
        self.store = store or Store()
        self.market = market or CoinbaseMarket()
        self.clock = clock
        self.rng = rng
        self.owner = str(uuid.uuid4())
        self.failures = 0
        self.started = False
        self.stop = threading.Event()

    def step(self):
        now = self.clock()
        if not self.store.acquire(self.owner, now):
            log.warning('Another worker holds the database lease; execution skipped')
            return 10
        fields = {'worker_started': now} if not self.started else {}
        self.store.heartbeat(self.owner, now, **fields)
        self.started = True
        try:
            quote, candles = self.market.fetch()
            now = self.clock()
            self.store.cycle(quote, candles, now, owner=self.owner)
            self.store.heartbeat(self.owner, now)
            self.failures = 0
            log.info('Analyzed fresh quote %s; paper cycle committed', quote.id)
            return 30
        except Exception as exc:
            self.failures += 1
            delay = min(60, 2 ** min(self.failures, 6)) + self.rng()*3
            now = self.clock()
            self.store.error(f'{type(exc).__name__}: {exc}', now, now+delay)
            log.warning('Market cycle blocked; retry in %.1fs: %s', delay, exc)
            return delay

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    delay = self.step()
                except Exception:
                    log.exception('Worker/storage failure; retry in 10s')
                    delay = 10
                self.stop.wait(delay)
        finally:
            self.store.release(self.owner)


def main():
    logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'), format='%(asctime)s %(levelname)s %(message)s')
    worker = Worker()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: worker.stop.set())
    worker.run()


if __name__ == '__main__':
    main()
