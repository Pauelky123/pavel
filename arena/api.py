"""Read-only HTTP API and static UI, separate from the trading worker."""
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .store import Store

ROOT = Path(__file__).resolve().parent
REPORT = ROOT.parent / 'data' / 'backtest.json'
STATIC = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            try:
                if path == '/api/snapshot':
                    self.respond(200, store.snapshot())
                elif path == '/health':
                    system = store.snapshot()['system']
                    self.respond(200 if system['ready'] else 503, system)
                elif path == '/live':
                    self.respond(200, {'api': 'alive', 'mode': 'paper'})
                elif path == '/api/backtest':
                    if REPORT.exists():
                        self.respond(200, json.loads(REPORT.read_text()))
                    else:
                        self.respond(404, {'error': 'Бэктест ещё не выполнен'})
                elif path in STATIC:
                    filename, kind = STATIC[path]
                    self.respond(200, (ROOT/'static'/filename).read_bytes(), kind)
                else:
                    self.respond(404, {'error': 'Not found'})
            except Exception:
                logging.exception('HTTP request failed')
                self.respond(503, {'error': 'Хранилище временно недоступно'})

        def respond(self, status, body, kind='application/json; charset=utf-8'):
            payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store' if kind.startswith('application/json') else 'no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)
    return Handler


def main():
    server = ThreadingHTTPServer((os.environ.get('ARENA_HOST', '127.0.0.1'), int(os.environ.get('ARENA_PORT', '8000'))), make_handler(Store()))
    logging.basicConfig(level=logging.INFO)
    logging.info('Paper Arena API listening on %s', server.server_address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
