"""Real process death during an open SQLite accounting transaction."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from arena.store import Store


class ProcessCrashTests(unittest.TestCase):
    def test_process_death_before_commit_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'crash.sqlite3'
            store = Store(path)
            child = '''
import os
from unittest.mock import patch
from arena.store import Store
from arena.market import Candle, Quote, DAY
now=DAY*20000
store=Store(os.environ['ARENA_DB'])
q=Quote('crash-fixture', now, 100, 100, 100, 'test fixture')
candles=[Candle(now-(45-i)*DAY,100) for i in range(45)]
with patch('arena.engine.signal', return_value=('BUY','fixture entry')):
    store.cycle(q,candles,now,before_commit=lambda:os._exit(77))
'''
            env = dict(os.environ,ARENA_DB=str(path))
            result = subprocess.run([sys.executable,'-c',child],env=env,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,77,result.stderr)
            snapshot = Store(path).snapshot()
            self.assertEqual(snapshot['trades'],[])
            self.assertTrue(all(a['state']['position'] is None and a['state']['cash']==10000 for a in snapshot['agents']))
            retry = child.replace('before_commit=lambda:os._exit(77)','before_commit=None')
            result = subprocess.run([sys.executable,'-c',retry],env=env,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(len(Store(path).snapshot()['trades']),3)
            result = subprocess.run([sys.executable,'-c',retry],env=env,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(len(Store(path).snapshot()['trades']),3)


if __name__ == '__main__':
    unittest.main()
