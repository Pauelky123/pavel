"""Pure paper accounting shared by the live worker and historical replay."""
from copy import deepcopy
from .market import DAY
from .strategies import signal

INITIAL_CASH = 10_000.0
FEE = .001
SLIPPAGE = .0005
MIN_NOTIONAL = 10.0


def initial_state():
    return dict(cash=INITIAL_CASH, position=None, equity=INITIAL_CASH, peak=INITIAL_CASH,
                drawdown=0.0, max_drawdown=0.0, fees=0.0, realized_pnl=0.0,
                trades=0, wins=0, losses=0, halted=False, last_trade_candle=None,
                last_quote=None, last_decision='WAIT', reason='Ожидаем первую свежую котировку.',
                last_run=None, started_at=None)


def mark(state, price):
    position = state['position']
    # Equity is estimated net liquidation value, including exit fee and slippage.
    state['equity'] = state['cash'] + (position['qty'] * price * (1 - SLIPPAGE) * (1 - FEE) if position else 0)
    state['peak'] = max(state['peak'], state['equity'])
    state['drawdown'] = max(0, 1 - state['equity'] / state['peak'])
    state['max_drawdown'] = max(state['max_drawdown'], state['drawdown'])


def sell(state, quote, now, reason):
    pos = state['position']
    fill = quote.bid * (1 - SLIPPAGE)
    gross = pos['qty'] * fill
    fee = gross * FEE
    pnl = gross - fee - pos['cost']
    state['cash'] += gross - fee
    state['fees'] += fee
    state['realized_pnl'] += pnl
    state['trades'] += 1
    state['wins' if pnl > 0 else 'losses'] += 1
    state['position'] = None
    return dict(side='SELL', time=now, quote_time=quote.time, price=fill, qty=pos['qty'],
                fee=fee, pnl=pnl, reason=reason, quote_id=quote.id)


def decide(original, strategy, quote, candles, now):
    state = deepcopy(original)
    if state['last_quote'] == quote.id:
        return state, None
    state['last_quote'] = quote.id
    state['last_run'] = now
    state['started_at'] = state['started_at'] or now
    mark(state, quote.bid)
    if state['drawdown'] >= strategy.max_drawdown:
        state['halted'] = True  # Latched: a restart must never resume risk automatically.
    candle_id = candles[-1].time
    prices = [c.close for c in candles]
    pos = state['position']
    action, reason = signal(strategy, prices, bool(pos))
    trade = None
    if pos:
        liquidation_return = (quote.bid * (1 - SLIPPAGE) * (1 - FEE) * pos['qty']) / pos['cost'] - 1
        if state['halted']:
            action, reason = 'SELL', f'Лимит просадки {strategy.max_drawdown:.0%}: риск остановлен до ручного разбора.'
        elif liquidation_return <= -strategy.stop:
            action, reason = 'SELL', f'Стоп-лосс: результат позиции после издержек {liquidation_return:.2%}.'
        elif liquidation_return >= strategy.take:
            action, reason = 'SELL', f'Фиксация прибыли: результат позиции после издержек {liquidation_return:.2%}.'
        elif now - pos['opened_at'] >= strategy.max_days * DAY:
            action, reason = 'SELL', f'Истёк максимальный срок позиции ({strategy.max_days} дней).'
        if action == 'SELL':
            trade = sell(state, quote, now, reason)
            state['last_trade_candle'] = candle_id
    elif state['halted']:
        action, reason = 'HALTED', f'Достигнут лимит просадки {strategy.max_drawdown:.0%}; новые позиции запрещены.'
    elif action == 'BUY':
        if state['last_trade_candle'] == candle_id:
            action, reason = 'WAIT', 'Сделка на этой дневной свече уже была; ждём новое закрытие.'
        else:
            budget = min(state['cash'], state['equity'] * strategy.allocation,
                         state['equity'] * strategy.risk / (strategy.stop + 2 * FEE + 2 * SLIPPAGE))
            fill = quote.ask * (1 + SLIPPAGE)
            qty = budget / (fill * (1 + FEE))
            gross = qty * fill
            fee = gross * FEE
            if gross < MIN_NOTIONAL:
                action, reason = 'WAIT', 'Допустимый размер позиции меньше $10; вход запрещён.'
            else:
                state['cash'] -= gross + fee
                state['fees'] += fee
                state['position'] = dict(qty=qty, entry=fill, cost=gross+fee, opened_at=now,
                                         stop=fill * (1 + FEE) * (1 - strategy.stop) / ((1-SLIPPAGE)*(1-FEE)),
                                         take=fill * (1 + FEE) * (1 + strategy.take) / ((1-SLIPPAGE)*(1-FEE)))
                state['last_trade_candle'] = candle_id
                trade = dict(side='BUY', time=now, quote_time=quote.time, price=fill, qty=qty,
                             fee=fee, pnl=None, reason=reason, quote_id=quote.id)
    mark(state, quote.bid)
    if state['drawdown'] >= strategy.max_drawdown:
        state['halted'] = True
    state['last_decision'], state['reason'] = action, reason
    return state, trade
