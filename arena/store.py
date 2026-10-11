"""SQLite WAL transactions: accounting, fills and equity are committed together."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from .engine import INITIAL_CASH, decide
from .market import validate
from .strategies import STRATEGIES


def db_path():
    return os.environ.get('ARENA_DB', 'runtime/arena.sqlite3')


class Store:
    def __init__(self, path=None):
        self.path = str(path or db_path())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trades(
                    id INTEGER PRIMARY KEY, agent_id TEXT NOT NULL, quote_id TEXT NOT NULL,
                    time REAL NOT NULL, data TEXT NOT NULL, UNIQUE(agent_id, quote_id));
                CREATE TABLE IF NOT EXISTS equity(
                    agent_id TEXT NOT NULL, bucket INTEGER NOT NULL, time REAL NOT NULL,
                    equity REAL NOT NULL, drawdown REAL NOT NULL, PRIMARY KEY(agent_id,bucket));
                CREATE TABLE IF NOT EXISTS processed_quotes(id TEXT PRIMARY KEY, time REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS errors(
                    id INTEGER PRIMARY KEY, time REAL NOT NULL, message TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lease(
                    id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, expires REAL NOT NULL);
                PRAGMA user_version=1;
            ''')
            from .engine import initial_state
            for s in STRATEGIES:
                db.execute('INSERT OR IGNORE INTO agents VALUES (?,?)', (s.id, json.dumps(initial_state())))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def set_meta(db, key, value):
        db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))

    def acquire(self, owner, now, ttl=120):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM lease WHERE id=1').fetchone()
            if row and row['owner'] != owner and row['expires'] > now:
                return False
            db.execute('INSERT INTO lease VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner, expires=excluded.expires', (owner, now+ttl))
            return True

    def release(self, owner):
        with self.connection() as db:
            db.execute('DELETE FROM lease WHERE owner=?', (owner,))

    def heartbeat(self, owner, now, **fields):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM lease WHERE id=1').fetchone()
            if not row or row['owner'] != owner or row['expires'] <= now:
                raise RuntimeError('Worker lost lease')
            self.set_meta(db, 'heartbeat', now)
            for k, v in fields.items():
                self.set_meta(db, k, v)

    def error(self, message, now, retry_at=None):
        with self.connection() as db:
            self.set_meta(db, 'current_error', str(message)[:1000])
            self.set_meta(db, 'retry_at', retry_at)
            db.execute('INSERT INTO errors(time,message) VALUES (?,?)', (now, str(message)[:1000]))
            db.execute('DELETE FROM errors WHERE id NOT IN (SELECT id FROM errors ORDER BY id DESC LIMIT 100)')

    def cycle(self, quote, candles, now, owner=None, before_commit=None):
        validate(quote, candles, now)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if owner:
                row = db.execute('SELECT * FROM lease WHERE id=1').fetchone()
                if not row or row['owner'] != owner or row['expires'] <= now:
                    raise RuntimeError('Worker lost lease before execution')
            last = db.execute("SELECT value FROM meta WHERE key='quote'").fetchone()
            if last and quote.time < json.loads(last['value'])['time']:
                raise ValueError('Котировка пришла раньше уже обработанной; торговля остановлена')
            if last and quote.id == json.loads(last['value'])['id'] and quote.public() != json.loads(last['value']):
                raise ValueError('Повторный идентификатор котировки с другим содержимым')
            processed = db.execute('SELECT 1 FROM processed_quotes WHERE id=?', (quote.id,)).fetchone()
            if not processed:
                db.execute('INSERT INTO processed_quotes VALUES (?,?)', (quote.id, quote.time))
            for strategy in STRATEGIES:
                state = json.loads(db.execute('SELECT state FROM agents WHERE id=?', (strategy.id,)).fetchone()['state'])
                new, trade = (state, None) if processed else decide(state, strategy, quote, candles, now)
                db.execute('UPDATE agents SET state=? WHERE id=?', (json.dumps(new), strategy.id))
                if trade:
                    db.execute('INSERT INTO trades(agent_id,quote_id,time,data) VALUES (?,?,?,?)', (strategy.id, quote.id, now, json.dumps(trade)))
                db.execute('INSERT INTO equity VALUES (?,?,?,?,?) ON CONFLICT(agent_id,bucket) DO UPDATE SET time=excluded.time,equity=excluded.equity,drawdown=excluded.drawdown',
                           (strategy.id, int(now//3600), now, new['equity'], new['drawdown']))
            self.set_meta(db, 'quote', quote.public())
            self.set_meta(db, 'last_cycle', now)
            self.set_meta(db, 'candle_time', candles[-1].time)
            self.set_meta(db, 'candle_count', len(candles))
            self.set_meta(db, 'current_error', None)
            self.set_meta(db, 'retry_at', None)
            db.execute('DELETE FROM processed_quotes WHERE time < ?', (now-2*86400,))
            # Bounded history: ~one year of hourly equity for every agent.
            db.execute('DELETE FROM equity WHERE bucket < ?', (int(now//3600)-24*366,))
            if before_commit:
                before_commit()  # Failure injection for transaction recovery tests.

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        with self.connection() as db:
            db.execute('BEGIN')  # A consistent snapshot across all tables.
            meta = {r['key']: json.loads(r['value']) for r in db.execute('SELECT * FROM meta')}
            agents = []
            for strategy in STRATEGIES:
                state = json.loads(db.execute('SELECT state FROM agents WHERE id=?', (strategy.id,)).fetchone()['state'])
                state['return_pct'] = (state['equity']/INITIAL_CASH-1)*100
                state['win_rate'] = state['wins']/state['trades']*100 if state['trades'] else None
                curve = [dict(r) for r in db.execute('SELECT time,equity,drawdown FROM (SELECT * FROM equity WHERE agent_id=? ORDER BY bucket DESC LIMIT 1000) ORDER BY bucket', (strategy.id,))]
                agents.append(dict(**strategy.public(), state=state, curve=curve))
            agents.sort(key=lambda a: a['state']['equity'], reverse=True)
            trades = [dict(id=r['id'], agent_id=r['agent_id'], **json.loads(r['data'])) for r in db.execute('SELECT * FROM trades ORDER BY id DESC LIMIT 100')]
            errors = [dict(r) for r in db.execute('SELECT time,message FROM errors ORDER BY id DESC LIMIT 10')]
        quote = meta.get('quote')
        quote_fresh = bool(quote and -5 <= now-quote['time'] <= 60)
        worker_alive = bool(meta.get('heartbeat') and 0 <= now-meta['heartbeat'] <= 90)
        cycle_fresh = bool(meta.get('last_cycle') and 0 <= now-meta['last_cycle'] <= 90)
        ready = worker_alive and cycle_fresh and quote_fresh and not meta.get('current_error')
        status = 'running' if ready else ('blocked' if worker_alive else 'offline')
        return dict(mode='paper', symbol='BTC-USD', initial_cash=INITIAL_CASH, server_time=now,
                    system=dict(status=status, ready=ready, worker_alive=worker_alive,
                                quote_fresh=quote_fresh, cycle_fresh=cycle_fresh, **meta),
                    agents=agents, trades=trades, errors=errors)
