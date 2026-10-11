# Запуск и проверка 24/7

Production arena.kpd100.site не проверен и не обновлён из этой среды: домен и Coinbase API блокируются прокси (403), серверные реквизиты не настроены. Следующие команды — конкретный план запуска на сервере с разрешённым доступом. Существующая инфраструктура неизвестна: сначала проверить её; не заменять сертификаты и конфигурацию вслепую.

## Перед запуском

1. На сервере найти текущий vhost и сервис сайта (`nginx -T`, `docker compose ls`, `systemctl list-units --type=service`); проверить владельца проекта, порт 8000 и свободный локальный диск. Не запускать вторую копию на другом volume: это будет отдельная арена.
2. Проверить разрешённые GET `https://api.exchange.coinbase.com/products/BTC-USD/ticker` и `/products/BTC-USD/candles?granularity=86400`. Требуются публичные данные, не биржевые ключи. Сайт и API работают при недоступном рынке, но сделки запрещены.
3. Использовать постоянный локальный volume SQLite, не NFS. Перед обновлением создать backup SQLite. Исходная живая БД в этом репозитории отсутствует.

## Docker Compose (соответствует описанному в старом README способу VPS-запуска)

```bash
cd /opt/pavel
python3 -m unittest discover -s tests -v
python3 -m arena.backtest
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 worker
curl -fsS http://127.0.0.1:8000/live
curl -fsS http://127.0.0.1:8000/health
```

API и worker — разные контейнеры с `restart: unless-stopped`, один `arena-data` volume. Команда `docker compose down` сохраняет volume; **не использовать `down -v`**, она удаляет всю историю. API `/live` — liveness, `/health` — readiness всего цикла и отвечает 503 при stale/offline/error. Worker healthcheck проверяет readiness БД. Docker НЕ перезапускает контейнер только из-за unhealthy: нужна тревога внешнего мониторинга на `/health`, а restart policy реагирует на завершение процесса. Потоки запросов ограничены timeout, retry продолжаются при сетевых сбоях.

Проверить конкретный cycle перед объявлением запуска:

```bash
curl -fsS http://127.0.0.1:8000/api/snapshot > /tmp/arena-before.json
docker compose restart worker
curl -fsS http://127.0.0.1:8000/api/snapshot > /tmp/arena-after.json
```

Дождаться новой котировки и успешного цикла (обычно 30с; после аварийного kill прежний lease может жить до 120с). Проверить, что cash/position/history сохранены, worker_started обновлён, новые сделки не дублируют quote_id. Если нет сигнала — цикл успешен без сделки, reason конкретен. Не заставлять live worker покупать для проверки: полный BUY→SELL уже проверяется изолированными fixtures.

Закрыть браузер, остановить только API `docker compose stop api`; проверить в worker logs новые циклы, затем `docker compose start api` и свежий `/health`. Проверить restart Docker daemon/reboot в согласованное эксплуатационное окно: данные остаются, оба процесса возвращаются.

## HTTPS

Пример `deploy/nginx.conf.example` — location для существующего HTTPS vhost; сертификаты и настройки домена нужно сначала изучить на сервере. API слушает только localhost на host. После подключения проверить `nginx -t`, reload и внешний `https://arena.kpd100.site/health`, затем интерфейс desktop/mobile и две последовательные котировки. Только после этого можно говорить, что сайт обновлён; работу после закрытия браузера и перезапуска проверить отдельно. Для утверждения о круглосуточной работе нужен период наблюдения и мониторинг, один успешный запрос его не доказывает.

## Альтернатива без Docker: systemd

Python 3.11+, зависимостей pip нет. Создать системного пользователя `arena`, checkout в `/opt/pavel` (читаемый arena), установить оба unit из `deploy/` в `/etc/systemd/system`. Затем:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pavel-arena-worker pavel-arena-api
sudo systemctl status pavel-arena-worker pavel-arena-api
sudo journalctl -u pavel-arena-worker -n 50
curl -fsS http://127.0.0.1:8000/health
```

Не запускать systemd и Compose одновременно. У systemd база в `/var/lib/pavel-arena`, автоматический restart и запуск после boot. Настроить внешнюю тревогу на 503 или отсутствие `/health` более 3 минут.

## Резервная копия и восстановление

Использовать SQLite backup API, не копировать только .sqlite3 при работающем WAL. Для Compose:

```bash
docker compose exec -T worker python -c "import sqlite3; src=sqlite3.connect('/data/arena.sqlite3'); dst=sqlite3.connect('/data/backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
docker compose cp worker:/data/backup.sqlite3 ./arena-backup.sqlite3
```

Копию хранить вне этого volume. Для restore: остановить оба сервиса, восстановить из целой backup-БД с правильным владельцем 10001, удалить только stale WAL/SHM остановленной базы, затем запуск и `/health`. Истекший lease подхватится через максимум 120с. У агентов с halted=True нет автоматического возврата к торговле: сначала разбор риска; не удалять базу ради сброса рейтинга.

## Обновление и откат

Backup, зафиксированный git commit, тесты, `docker compose up -d --build`, readiness и UI. Откат к проверенному commit, rebuild и проверка: volume не удалять. Schema v1 совместима с текущим кодом. API read-only и без public endpoint для сброса/сделок. На будущем изменении схемы добавить явную миграцию, backup и тест перехода.
