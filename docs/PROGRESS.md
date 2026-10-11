# Прогресс арены

## 2026-10-12 (Москва)

Исходник: pavel, commit 9055ba9. Код арены и существующее развёртывание отсутствуют; production-домен недоступен из-за сетевой политики. Создан отдельный paper-only пакет.

Готово: три детерминированные стратегии, защитные выходы, риск и комиссии, общий движок live/backtest; Coinbase read-only market validation; SQLite WAL и атомарный цикл; DB lease и дедупликация; независимый worker с retry/backoff; read-only HTTP API; реальный Coin Metrics CSV с pinned revision и checksums; воспроизводимый отчёт с benchmark и ограничениями.

Проверено на этом этапе: 17 unittest (полный цикл, риск, комиссии, стоп/цель, restart, rollback при сбое, concurrent dedup, lease takeover, stale data, retry recovery, стратегии, отсутствие lookahead и воспроизводимость реального бэктеста). Frontend JS проходит syntax check.

Далее: браузерные проверки desktop/mobile, независимого запуска процессов, конфигурация развёртывания и инструкция для production. Production пока НЕ обновлён; круглосуточная работа на сервере НЕ подтверждена.
