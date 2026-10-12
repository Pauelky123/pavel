import csv
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from arena.backtest import replay
from arena.engine import FEE, SLIPPAGE, decide, initial_state
from arena.market import Candle, CoinbaseMarket, DAY, Quote, validate
from arena.store import Store
from arena.strategies import STRATEGIES, signal
from arena.worker import Worker

NOW = DAY * 20000


def history(prices=None, now=NOW):
    prices = prices or [100.] * 45
    return [Candle(now - (len(prices)-i)*DAY, p) for i, p in enumerate(prices)]


def quote(price=100, id='q1', now=NOW):
    return Quote(id, now, price, price, price, 'test fixture')


class AccountingTests(unittest.TestCase):
    def buy(self, strategy=STRATEGIES[0]):
        with patch('arena.engine.signal', return_value=('BUY', 'test entry')):
            return decide(initial_state(), strategy, quote(), history(), NOW)

    def test_round_trip_with_fees_and_risk_sizing(self):
        s = STRATEGIES[0]
        state, buy = self.buy(s)
        self.assertEqual(buy['side'], 'BUY')
        pos = state['position']
        self.assertGreater(state['cash'], 0)
        self.assertLessEqual(pos['cost'], 10000*s.allocation)
        self.assertLessEqual(pos['cost']*(s.stop+2*FEE+2*SLIPPAGE), 10000*s.risk+1e-8)
        self.assertAlmostEqual(state['cash']+pos['cost'], 10000)
        sold, trade = decide(state, s, quote(120, 'q2', NOW+30), history(), NOW+30)
        self.assertEqual(trade['side'], 'SELL')
        self.assertIsNone(sold['position'])
        self.assertAlmostEqual(sold['cash'], 10000+trade['pnl'])
        self.assertAlmostEqual(sold['fees'], buy['fee']+trade['fee'])
        self.assertEqual(sold['trades'], 1)
        self.assertEqual(sold['wins'], 1)

    def test_stop_and_gap_execution_not_fictional_stop_price(self):
        state, _ = self.buy()
        stopped, trade = decide(state, STRATEGIES[0], quote(80, 'gap'), history(), NOW+30)
        self.assertIn('Стоп', trade['reason'])
        self.assertAlmostEqual(trade['price'], 80*(1-SLIPPAGE))
        self.assertLess(trade['pnl'], 0)
        self.assertEqual(stopped['losses'], 1)

    def test_drawdown_halt_persists_and_liquidates(self):
        s = replace(STRATEGIES[0], max_drawdown=.01)
        state, _ = self.buy(s)
        state, trade = decide(state, s, quote(80, 'q2'), history(), NOW+30)
        self.assertIn('Лимит просадки', trade['reason'])
        self.assertTrue(state['halted'])
        with patch('arena.engine.signal', return_value=('BUY', 'entry')):
            state, trade = decide(state, s, quote(200, 'q3'), history(), NOW+60)
        self.assertIsNone(trade)
        self.assertEqual(state['last_decision'], 'HALTED')

    def test_duplicate_quote_and_no_reentry_on_same_candle(self):
        state, _ = self.buy()
        repeated, trade = decide(state, STRATEGIES[0], quote(), history(), NOW)
        self.assertEqual(state, repeated)
        self.assertIsNone(trade)
        state, _ = decide(state, STRATEGIES[0], quote(120, 'q2'), history(), NOW+30)
        with patch('arena.engine.signal', return_value=('BUY', 'entry')):
            state, trade = decide(state, STRATEGIES[0], quote(100, 'q3'), history(), NOW+60)
        self.assertIsNone(trade)
        self.assertIn('свече уже была', state['reason'])

    def test_time_exit(self):
        state, _ = self.buy()
        with patch('arena.engine.signal', return_value=('HOLD', 'hold')):
            _, trade = decide(state, STRATEGIES[0], quote(100, 'timeout'), history(), NOW+22*DAY)
        self.assertIn('срок', trade['reason'])


class StrategyTests(unittest.TestCase):
    def test_distinct_natural_entries_and_exits(self):
        trend = [100+i*.5 for i in range(43)] + [111., 124.]
        revert = [100.] * 43 + [98., 94.]
        breakout = [100.] * 44 + [104.]
        for s, prices in zip(STRATEGIES, [trend, revert, breakout]):
            action, reason = signal(s, prices)
            self.assertEqual(action, 'BUY', (s.id, reason))
        self.assertEqual(signal(STRATEGIES[0], [120.]*20+[80.]*25, True)[0], 'SELL')
        self.assertEqual(signal(STRATEGIES[1], [100.]*44+[101.], True)[0], 'SELL')
        self.assertEqual(signal(STRATEGIES[2], [100.]*44+[90.], True)[0], 'SELL')
        for s in STRATEGIES:
            self.assertEqual(signal(s, [100.]*45)[0], 'WAIT')
            self.assertTrue(signal(s, [100.]*45)[1])
            self.assertEqual(signal(s, [100.]*2)[0], 'WAIT')


class MarketTests(unittest.TestCase):
    def test_stale_future_bad_spread_and_invalid_prices_fail_closed(self):
        for q in [quote(now=NOW-61), quote(now=NOW+6), replace(quote(), price=float('nan')),
                  replace(quote(), bid=102, ask=99), replace(quote(), ask=110)]:
            with self.assertRaises(ValueError):
                validate(q, history(), NOW)

    def test_provider_excludes_open_bar_and_observes_book_changes(self):
        from datetime import datetime, timezone
        ticker = dict(trade_id=99, time=datetime.fromtimestamp(NOW, timezone.utc).isoformat(),
                      price='100', bid='99.9', ask='100.1')
        rows = [[NOW,90,110,100,101,1], [NOW-DAY,90,110,100,100,1], [NOW-2*DAY,90,110,100,100,1]]
        market = CoinbaseMarket()
        updated = dict(ticker, bid='99.8')
        with patch.object(market, '_get', side_effect=[ticker,rows,updated,rows]), patch('arena.market.time.time', return_value=NOW):
            q1, candles = market.fetch()
            q2, _ = market.fetch()
        self.assertNotEqual(q1.id, q2.id)
        self.assertEqual(len(candles),2)
        self.assertEqual(candles[-1].time,NOW-DAY)

    def test_incomplete_gapped_and_stale_candles(self):
        for cs in [history()[:-3], history()[:-1]+[Candle(NOW, 100)],
                   history()[:20]+history()[21:], history()[:-1]+[Candle(NOW-DAY, -1)]]:
            with self.assertRaises(ValueError):
                validate(quote(), cs, NOW)
        validate(quote(), history(), NOW)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'arena.sqlite3'
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def enter(self):
        with patch('arena.engine.signal', return_value=('BUY', 'test entry')):
            self.store.cycle(quote(), history(), NOW)

    def test_future_schema_is_not_silently_downgraded(self):
        with self.store.connection() as db:
            db.execute('PRAGMA user_version=2')
        with self.assertRaises(RuntimeError):
            Store(self.path)
        with self.store.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)

    def test_reopen_restart_and_sell(self):
        self.enter()
        first = self.store.snapshot(NOW)
        fresh_store = Store(self.path)
        self.assertEqual(first['agents'], fresh_store.snapshot(NOW)['agents'])
        fresh_store.cycle(quote(120, 'q2', NOW+30), history(), NOW+30)
        result = Store(self.path).snapshot(NOW+30)
        self.assertEqual(len(result['trades']), 6)
        self.assertTrue(all(a['state']['position'] is None for a in result['agents']))
        self.assertTrue(all(a['state']['trades'] == 1 for a in result['agents']))

    def test_atomic_rollback_and_retry(self):
        def crash():
            raise RuntimeError('injected before commit')
        with patch('arena.engine.signal', return_value=('BUY', 'entry')):
            with self.assertRaises(RuntimeError):
                self.store.cycle(quote(), history(), NOW, before_commit=crash)
        self.assertEqual(len(Store(self.path).snapshot(NOW)['trades']), 0)
        self.assertTrue(all(a['state']['cash'] == 10000 for a in self.store.snapshot(NOW)['agents']))
        self.enter()
        self.assertEqual(len(self.store.snapshot(NOW)['trades']), 3)

    def test_concurrent_cycles_do_not_duplicate(self):
        with patch('arena.engine.signal', return_value=('BUY', 'entry')):
            with ThreadPoolExecutor(4) as pool:
                list(pool.map(lambda _: Store(self.path).cycle(quote(), history(), NOW), range(4)))
        self.assertEqual(len(self.store.snapshot(NOW)['trades']), 3)

    def test_out_of_order_quotes_rejected(self):
        self.enter()
        with self.assertRaises(ValueError):
            self.store.cycle(quote(id='old', now=NOW-1), history(), NOW)
        with self.assertRaises(ValueError):
            self.store.cycle(quote(101), history(), NOW)

    def test_db_lease_and_readiness(self):
        self.assertTrue(self.store.acquire('a', NOW))
        self.assertFalse(Store(self.path).acquire('b', NOW+1))
        self.store.heartbeat('a', NOW, worker_started=NOW)
        self.store.cycle(quote(), history(), NOW, owner='a')
        self.assertTrue(self.store.snapshot(NOW)['system']['ready'])
        self.assertFalse(self.store.snapshot(NOW+91)['system']['ready'])
        self.assertTrue(Store(self.path).acquire('b', NOW+121))
        with self.assertRaises(RuntimeError):
            self.store.cycle(quote(id='q2', now=NOW+121), history(), NOW+121, owner='a')
        self.store.release('a')
        self.assertFalse(self.store.acquire('c', NOW+122))

    def test_worker_failure_retry_recovery(self):
        class Market:
            n = 0
            def fetch(self):
                self.n += 1
                if self.n == 1:
                    raise OSError('exchange unavailable')
                return quote(), history()
        worker = Worker(self.store, Market(), lambda: NOW, lambda: 0)
        self.assertEqual(worker.step(), 2)
        self.assertIn('exchange unavailable', self.store.snapshot(NOW)['system']['current_error'])
        self.assertEqual(worker.step(), 30)
        self.assertIsNone(self.store.snapshot(NOW)['system']['current_error'])
        self.assertTrue(self.store.snapshot(NOW)['system']['ready'])

    def test_stale_cycle_never_changes_cash(self):
        with self.assertRaises(ValueError):
            self.store.cycle(quote(now=NOW-100), history(), NOW)
        self.assertTrue(all(a['state']['cash'] == 10000 for a in self.store.snapshot(NOW)['agents']))
        self.assertEqual(self.store.snapshot(NOW)['trades'], [])


class BacktestTests(unittest.TestCase):
    def test_future_data_cannot_change_past_fills(self):
        rows = [(NOW+i*DAY, 100+(i%17)) for i in range(100)]
        a = replay(rows)
        b = replay(rows[:75]+[(t, p*3) for t,p in rows[75:]])
        for s1,s2 in zip(a['agents'], b['agents']):
            self.assertEqual(s1['curve'][:35], s2['curve'][:35])
            self.assertEqual([t for t in s1['fills'] if t['time'] < rows[75][0]],
                             [t for t in s2['fills'] if t['time'] < rows[75][0]])

    def test_reproducible_historical_report(self):
        root = Path(__file__).resolve().parents[1]
        report = json.loads((root/'data/backtest.json').read_text())
        with (root/'data/btc_daily.csv').open() as f:
            from datetime import datetime, timezone
            rows = [(datetime.fromisoformat(r['date']).replace(tzinfo=timezone.utc).timestamp(), float(r['price'])) for r in csv.DictReader(f)]
        result = replay(rows)
        self.assertEqual(result['agents'], report['agents'])
        self.assertEqual(result['benchmark'], report['benchmark'])
        self.assertTrue(any(a['return_pct'] < 0 for a in result['agents']))


if __name__ == '__main__':
    unittest.main()
