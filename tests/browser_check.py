"""Optional Playwright integration: isolated synthetic fixtures, never live DB.
Run: python tests/browser_check.py (requires playwright and Chromium).
"""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import tempfile
import os
import shutil
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from arena.api import make_handler
from arena.market import Candle, DAY, Quote
from arena.store import Store


def main():
    out = Path('artifacts')
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp)/'browser-fixture.sqlite3')
        server = ThreadingHTTPServer(('127.0.0.1',0),make_handler(store))
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base = 'http://127.0.0.1:'+str(server.server_port)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
                page = browser.new_page(viewport={'width':1440,'height':1000})
                errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base)
                page.wait_for_selector('.agent-card')
                page.wait_for_selector('#history-results table')
                assert page.locator('.agent-card').count()==3
                assert page.locator('#trade-list tbody tr').count()==0
                assert page.locator('#capital-chart .empty-state').count()==1
                assert page.locator('#connection').get_attribute('data-status')=='offline'
                page.get_by_role('button',name='Бэктест',exact=True).click()
                assert page.locator('.chart-line').count()==4
                for width in (320,390,768,1440,1920):
                    page.set_viewport_size({'width':width,'height':900})
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'), width
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(out/'browser-mobile.png'),full_page=True)

                now=time.time()
                midnight=int(now//DAY)*DAY
                prices=[100.]*44+[104.]
                candles=[Candle(midnight-(45-i)*DAY,price) for i,price in enumerate(prices)]
                assert store.acquire('browser-fixture',now)
                store.heartbeat('browser-fixture',now,worker_started=now)
                store.cycle(Quote('fixture-buy',now,104,104,104,'SYNTHETIC TEST ONLY'),candles,now,owner='browser-fixture')
                page.reload()
                page.wait_for_selector('#trade-list tbody tr')
                assert page.locator('#trade-list tbody tr').count()==2
                assert page.locator('.state-tag.open').count()==2
                assert page.locator('#connection').get_attribute('data-status')=='running'
                page.locator('#trade-filter').select_option('trend')
                assert page.locator('#trade-list tbody tr').count()==1
                page.locator('#rules-trend summary').click()
                # Refresh while keeping expanded rules and the trade filter.
                now=time.time()
                store.cycle(Quote('fixture-sell',now,120,120,120,'SYNTHETIC TEST ONLY'),candles,now,owner='browser-fixture')
                expect(page.locator("#trade-count")).to_have_text("2",timeout=15000)
                assert page.locator('#rules-trend').get_attribute('open') is not None
                assert page.locator('#trade-filter').input_value()=='trend'
                assert page.locator('#trade-list tbody tr').count()==2
                assert page.locator('.state-tag.open').count()==0
                page.set_viewport_size({'width':1440,'height':1000})
                page.screenshot(path=str(out/'browser-fixture-roundtrip.png'),full_page=True)

                # API failure: preserve previous data and explicitly show lost connection.
                page.route('**/api/snapshot',lambda route:route.abort())
                expect(page.locator("#connection")).to_contain_text("Связь с API потеряна",timeout=15000)
                assert page.locator('#trade-count').inner_text()=='2'
                assert page.locator('.state-tag.open').count()==0
                page.unroute('**/api/snapshot')
                expect(page.locator("#connection")).to_have_attribute("data-status","running",timeout=15000)
                assert errors==[],errors
                browser.close()
                print('Browser checks passed: empty/live/history, 5 widths, natural BUY→SELL, filters, expanded rules, API failure/recovery; no JS errors.')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__=='__main__':
    main()
