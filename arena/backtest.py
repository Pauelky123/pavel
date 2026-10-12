"""Daily replay at the next observation, no future bars and no live DB writes."""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from .engine import FEE, INITIAL_CASH, SLIPPAGE, decide, initial_state, mark, sell
from .market import Candle, DAY, Quote, validate
from .strategies import STRATEGIES, WARMUP

ROOT = Path(__file__).resolve().parents[1]


def replay(rows):
    states = {s.id: initial_state() for s in STRATEGIES}
    curves = {s.id: [] for s in STRATEGIES}
    fills = {s.id: [] for s in STRATEGIES}
    start = rows[WARMUP][0]
    for i in range(WARMUP, len(rows)):
        now, price = rows[i]
        # A dated reference rate is observed at `now`; only previous rates are signals.
        candles = [Candle(t-DAY, p) for t, p in rows[max(0,i-100):i]]
        q = Quote(f'historical:{now}', now, price, price, price, 'Coin Metrics PriceUSD daily reference')
        validate(q, candles, now)
        for s in STRATEGIES:
            state, trade = decide(states[s.id], s, q, candles, now)
            states[s.id] = state
            if trade:
                fills[s.id].append(trade)
            curves[s.id].append(dict(time=now, equity=round(state['equity'], 4)))
    end, final = rows[-1]
    q = Quote('terminal-liquidation', end, final, final, final, 'Coin Metrics')
    for s in STRATEGIES:
        state = states[s.id]
        if state['position']:
            fills[s.id].append(sell(state, q, end, 'Закрытие в конце тестового периода'))
            mark(state, final)
            curves[s.id][-1]['equity'] = round(state['equity'], 4)
    qty = INITIAL_CASH / (rows[WARMUP][1]*(1+SLIPPAGE)*(1+FEE))
    benchmark = []
    peak, maxdd = INITIAL_CASH, 0
    for t, p in rows[WARMUP:]:
        equity = qty*p*(1-SLIPPAGE)*(1-FEE)
        peak = max(peak, equity)
        maxdd = max(maxdd, 1-equity/peak)
        benchmark.append(dict(time=t, equity=round(equity, 4)))
    return dict(start=start, end=end, observations=len(rows)-WARMUP,
                benchmark=dict(name='Buy & hold BTC', equity=benchmark[-1]['equity'],
                               return_pct=(benchmark[-1]['equity']/INITIAL_CASH-1)*100,
                               max_drawdown=maxdd, curve=benchmark),
                agents=[dict(id=s.id, name=s.name, equity=states[s.id]['equity'],
                             return_pct=(states[s.id]['equity']/INITIAL_CASH-1)*100,
                             max_drawdown=states[s.id]['max_drawdown'], fees=states[s.id]['fees'],
                             closed_trades=states[s.id]['trades'], halted=states[s.id]['halted'],
                             curve=curves[s.id], fills=fills[s.id]) for s in STRATEGIES])


def main():
    path = ROOT/'data'/'btc_daily.csv'
    source = json.loads((ROOT/'data'/'history_source.json').read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != source['dataset_sha256']:
        raise ValueError('Historical dataset checksum mismatch')
    with path.open() as f:
        rows = [(datetime.fromisoformat(r['date']).replace(tzinfo=timezone.utc).timestamp(), float(r['price'])) for r in csv.DictReader(f)]
    report = replay(rows)
    report.update(source=source, initial_cash=INITIAL_CASH, fee_rate=FEE, slippage_rate=SLIPPAGE,
                  interval='daily', model='Сигнал из предыдущих дневных цен; исполнение по следующему дневному наблюдению. Без оптимизации параметров.',
                  limitations=['Нет внутридневных OHLC: стопы проверяются только на дневных наблюдениях; возможны проскоки.',
                               'Справочные цены Coin Metrics отличаются от Coinbase. Спред в истории неизвестен.',
                               'Комиссия 0.1% и проскальзывание 0.05% на каждой стороне — допущение, не тариф биржи.',
                               'Достижение лимита просадки останавливает агента до конца теста; прибыль не гарантируется.'])
    (ROOT/'data'/'backtest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    for a in report['agents']:
        print(f"{a['name']}: {a['return_pct']:.2f}%, DD {a['max_drawdown']:.2%}, closed {a['closed_trades']}, fees ${a['fees']:.2f}, halted {a['halted']}")
    print(f"Buy & hold: {report['benchmark']['return_pct']:.2f}%, DD {report['benchmark']['max_drawdown']:.2%}")


if __name__ == '__main__':
    main()
