"""Real, separate worker/API processes using an isolated synthetic market."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from arena.store import Store

CHILD = '''
import json, os, signal, time
from pathlib import Path
from arena.worker import Worker
from arena.market import Candle, DAY, Quote
class FixtureMarket:
    def fetch(self):
        now=time.time()
        price=json.loads(Path(os.environ['TEST_MARKET_FILE']).read_text())['price']
        midnight=int(now//DAY)*DAY
        prices=[100.]*44+[104.]
        candles=[Candle(midnight-(45-i)*DAY,p) for i,p in enumerate(prices)]
        return Quote('fixture:'+str(time.time_ns()),now,price,price,price,'SYNTHETIC TEST ONLY'),candles
class TestWorker(Worker):
    def step(self):
        super().step()
        return .1
worker=TestWorker(market=FixtureMarket())
signal.signal(signal.SIGTERM,lambda *_:worker.stop.set())
worker.run()
'''


class WorkerProcessTests(unittest.TestCase):
    def test_worker_trades_without_website_and_restores_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'paper.sqlite3'
            phase = Path(tmp)/'market.json'
            phase.write_text(json.dumps({'price':104}))
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0))
                port = sock.getsockname()[1]
            env = dict(os.environ,ARENA_DB=str(path),ARENA_PORT=str(port),TEST_MARKET_FILE=str(phase))
            processes=[]
            def start_api():
                process=subprocess.Popen([sys.executable,'-m','arena.api'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                processes.append(process)
                return process
            def start_worker():
                process=subprocess.Popen([sys.executable,'-c',CHILD],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                processes.append(process)
                return process
            def wait_for(check, timeout=5):
                until=time.monotonic()+timeout
                last=None
                while time.monotonic()<until:
                    try:
                        last=check()
                        if last:
                            return last
                    except (OSError,KeyError,ValueError):
                        pass
                    time.sleep(.05)
                self.fail(f'Condition failed, last={last}')
            def api_snapshot():
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/snapshot',timeout=1) as response:
                    return json.load(response)
            try:
                api=start_api()
                worker=start_worker()
                wait_for(lambda: api_snapshot()['system']['ready'])
                first=api_snapshot()
                self.assertEqual(len(first['trades']),2)
                self.assertEqual(sum(bool(a['state']['position']) for a in first['agents']),2)
                # Stop the website completely. Worker keeps analyzing independently.
                api.terminate()
                api.wait(timeout=5)
                store=Store(path)
                cycle=store.snapshot()['system']['last_cycle']
                wait_for(lambda: store.snapshot()['system'].get('last_cycle',0)>cycle)
                # Complete both take-profit exits with API still stopped.
                phase.write_text(json.dumps({'price':120}))
                wait_for(lambda: len(store.snapshot()['trades'])==4)
                result=store.snapshot()
                self.assertTrue(all(a['state']['position'] is None for a in result['agents']))
                self.assertTrue(all(a['state']['cash']>0 for a in result['agents']))
                money={a['id']:a['state']['cash'] for a in result['agents']}
                # A real worker process restart preserves balances and entry cooldown.
                worker.terminate()
                worker.wait(timeout=5)
                self.assertEqual(len(Store(path).snapshot()['trades']),4)
                worker=start_worker()
                api=start_api()
                wait_for(lambda: api_snapshot()['system']['ready'])
                wait_for(lambda: api_snapshot()['system']['last_cycle']>result['system']['last_cycle'])
                restored=api_snapshot()
                self.assertEqual(len(restored['trades']),4)
                self.assertEqual(money,{a['id']:a['state']['cash'] for a in restored['agents']})
                self.assertNotEqual(result['system']['worker_started'],restored['system']['worker_started'])
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)


if __name__=='__main__':
    unittest.main()
