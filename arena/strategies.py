"""Deterministic strategies on completed daily BTC-USD observations."""
from dataclasses import asdict, dataclass
from statistics import mean, pstdev


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    style: str
    description: str
    entry_rule: str
    exit_rule: str
    allocation: float
    risk: float
    stop: float
    take: float
    max_drawdown: float
    max_days: int
    color: str

    def public(self):
        return asdict(self)


STRATEGIES = (
    Strategy('trend', 'VECTOR', 'Следование тренду',
             'Покупает возврат цены над средней в подтверждённом восходящем тренде.',
             'SMA10 > SMA30, SMA30 растёт; закрытие пересекает SMA10 вверх.',
             'SMA10 < SMA30, стоп 5%, цель 12% или 21 день.',
             .40, .01, .05, .12, .12, 21, '#ff9457'),
    Strategy('reversion', 'ORBIT', 'Возврат к среднему',
             'Ищет статистическое отклонение в боковом рынке; избегает сильного падения.',
             'Цена ниже средней 20 дней − 1.5σ, RSI14 < 35; падение за 5 дней < 10%.',
             'Возврат к SMA20, стоп 3%, цель 6% или 7 дней.',
             .25, .006, .03, .06, .08, 7, '#6fe3c4'),
    Strategy('breakout', 'PULSE', 'Пробой диапазона',
             'Входит после нового максимума 20 дней с подтверждённым импульсом.',
             'Закрытие выше предыдущих 20 закрытий на 0.2%, импульс 5 дней > 2%.',
             'Падение ниже минимума 10 закрытий, стоп 4%, цель 10% или 14 дней.',
             .35, .008, .04, .10, .10, 14, '#a6a0ff'),
)
BY_ID = {s.id: s for s in STRATEGIES}
WARMUP = 40


def rsi(prices, period=14):
    changes = [b - a for a, b in zip(prices[-period-1:-1], prices[-period:])]
    gain = sum(max(x, 0) for x in changes) / period
    loss = sum(max(-x, 0) for x in changes) / period
    if not loss:
        return 100.0 if gain else 50.0
    return 100 - 100 / (1 + gain / loss)


def signal(strategy, prices, holding=False):
    if len(prices) < WARMUP:
        return 'WAIT', f'Прогрев: {len(prices)}/{WARMUP} закрытых дневных наблюдений.'
    p = prices[-1]
    fast, slow = mean(prices[-10:]), mean(prices[-30:])
    if strategy.id == 'trend':
        if holding:
            return ('SELL', 'SMA10 опустилась ниже SMA30: тренд потерян.') if fast < slow else ('HOLD', f'Тренд сохраняется: SMA10 {fast:.2f}, SMA30 {slow:.2f}.')
        prev_fast = mean(prices[-11:-1])
        rising = slow > mean(prices[-31:-1])
        crossed = prices[-2] <= prev_fast and p > fast
        if fast > slow and rising and crossed:
            return 'BUY', 'Цена пересекла SMA10 вверх; SMA10 выше растущей SMA30.'
        return 'WAIT', f'Ждём возврат над SMA10 при растущей SMA30. SMA10 {fast:.2f}, SMA30 {slow:.2f}; пересечение: {"да" if crossed else "нет"}.'
    if strategy.id == 'reversion':
        avg = mean(prices[-20:])
        lower = avg - 1.5 * pstdev(prices[-20:])
        strength = rsi(prices)
        momentum = p / prices[-6] - 1
        if holding:
            return ('SELL', f'Цена вернулась к SMA20 {avg:.2f}.') if p >= avg else ('HOLD', f'Ждём возврат к SMA20 {avg:.2f}; закрытие {p:.2f}.')
        if p < lower and strength < 35 and momentum > -.10:
            return 'BUY', f'Закрытие {p:.2f} ниже границы {lower:.2f}, RSI {strength:.1f}; падение ограничено.'
        return 'WAIT', f'Нет безопасной перепроданности: цена {p:.2f}, граница {lower:.2f}, RSI {strength:.1f}, импульс {momentum:.1%}.'
    ceiling = max(prices[-21:-1])
    momentum = p / prices[-6] - 1
    if holding:
        floor = min(prices[-11:-1])
        return ('SELL', f'Закрытие ниже минимума 10 дней {floor:.2f}.') if p < floor else ('HOLD', f'Пробой сохраняется; граница выхода {floor:.2f}.')
    if p > ceiling * 1.002 and momentum > .02:
        return 'BUY', f'Пробит максимум {ceiling:.2f}; импульс 5 дней {momentum:.1%}.'
    return 'WAIT', f'Ждём пробой {ceiling * 1.002:.2f}; закрытие {p:.2f}, импульс {momentum:.1%} (нужно > 2%).'
