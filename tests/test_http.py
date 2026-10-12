import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from arena.api import make_handler
from arena.store import Store


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(Path(cls.tmp.name)/'http.sqlite3')
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.store))
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def test_snapshot_and_readiness_are_distinct_from_liveness(self):
        with urllib.request.urlopen(self.base+'/api/snapshot') as r:
            snapshot = json.load(r)
            self.assertEqual(r.headers['Cache-Control'],'no-store')
            self.assertEqual(snapshot['mode'],'paper')
            self.assertEqual(len(snapshot['agents']),3)
            self.assertEqual(snapshot['trades'],[])
        with urllib.request.urlopen(self.base+'/live') as r:
            self.assertEqual(r.status,200)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.base+'/health')
        self.assertEqual(error.exception.code,503)

    def test_no_trading_or_filesystem_endpoints(self):
        for path in ['/api/buy','/../README.md','/api/reset']:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base+path)
            self.assertEqual(error.exception.code,404)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(self.base+'/api/snapshot',method='POST',data=b'{}'))
        self.assertEqual(error.exception.code,501)
        self.assertEqual(self.store.snapshot()['trades'],[])

    def test_assets_and_report(self):
        for path in ['/','/app.js','/style.css','/api/backtest']:
            with urllib.request.urlopen(self.base+path) as r:
                self.assertEqual(r.status,200)
                self.assertIn("script-src 'self'",r.headers['Content-Security-Policy'])
                self.assertTrue(r.read())


if __name__ == '__main__':
    unittest.main()
