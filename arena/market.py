"""Public read-only Coinbase data. Invalid or old observations fail closed."""
import json
import math
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime

DAY = 86400
MAX_QUOTE_AGE = 60
BASE_URL = 'https://api.exchange.coinbase.com'


@dataclass(frozen=True)
class Quote:
    id: str
    time: float
    price: float
    bid: float
    ask: float
    source: str = 'Coinbase Exchange · BTC-USD'

    def public(self):
        return asdict(self)


@dataclass(frozen=True)
class Candle:
    time: float
    close: float


def validate(quote, candles, now):
    if not all(math.isfinite(x) and x > 0 for x in (quote.price, quote.bid, quote.ask)):
        raise ValueError('Некорректная цена рынка')
    if quote.bid > quote.ask or (quote.ask - quote.bid) / quote.price > .02:
        raise ValueError('Спред котировки превышает 2% или стакан некорректен')
    if not math.isfinite(quote.time) or quote.time > now + 5 or now - quote.time > MAX_QUOTE_AGE:
        raise ValueError('Котировка устарела (>60с) или имеет будущее время; торговля остановлена')
    if not quote.id or not candles:
        raise ValueError('Нет идентификатора котировки или закрытых свечей')
    for index, c in enumerate(candles):
        if not math.isfinite(c.close) or c.close <= 0 or not math.isfinite(c.time):
            raise ValueError('Некорректная свеча')
        if c.time + DAY > now:
            raise ValueError('Незакрытая свеча запрещена')
        if index and c.time - candles[index-1].time != DAY:
            raise ValueError('Разрыв или дубликат в дневной истории')
    if now - (candles[-1].time + DAY) >= DAY + 120:
        raise ValueError('Дневная история устарела')


class CoinbaseMarket:
    def _get(self, path):
        req = urllib.request.Request(BASE_URL + path, headers={'User-Agent': 'PavelPaperArena/1.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=12) as response:
            return json.load(response)

    def fetch(self):
        ticker = self._get('/products/BTC-USD/ticker')
        rows = self._get('/products/BTC-USD/candles?granularity=86400')
        now = time.time()
        # Best bid/ask can change without a new trade. Identify the full observed
        # book snapshot so protective exits still react to spread movements.
        quote_id = f"coinbase:{ticker['trade_id']}:{float(ticker['bid'])}:{float(ticker['ask'])}"
        quote = Quote(quote_id, datetime.fromisoformat(ticker['time'].replace('Z', '+00:00')).timestamp(),
                      float(ticker['price']), float(ticker['bid']), float(ticker['ask']))
        candles = sorted((Candle(float(r[0]), float(r[4])) for r in rows if float(r[0]) + DAY <= now), key=lambda c: c.time)
        validate(quote, candles, now)
        return quote, candles
