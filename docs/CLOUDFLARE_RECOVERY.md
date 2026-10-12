# Восстановление arena.kpd100.site: Cloudflare 1033

Скриншот пользователя от 2026-10-12 09:53:23 UTC показывает **Error 1033 / Cloudflare Tunnel error**. Для настроенного туннеля нет доступного здорового соединения с cloudflared. Это отдельный инфраструктурный сбой: изменение HTML или merge репозитория его не исправляет. Точная причина (остановка сервера/процесса, неверный token, заблокированный исходящий трафик) требует доступа к connector и его журналам.

Из текущей среды HTTP CONNECT к домену и Coinbase заблокирован политикой (403); серверных учётных данных, VPN, токена/аккаунта Cloudflare здесь нет. Туннель не восстановлен. Не создавать новый домен/туннель вслепую и не заменять существующую DNS-запись.

## Если существующий connector установлен как systemd service

На том сервере, где он был запущен:

```bash
sudo systemctl status cloudflared --no-pager
sudo journalctl -u cloudflared --since '30 minutes ago' --no-pager
sudo systemctl restart cloudflared
sudo systemctl enable cloudflared
```

Проверить в Cloudflare Zero Trust → Networks → Tunnels состояние именно туннеля, обслуживающего arena.kpd100.site, и появление healthy connector. Убедиться, что сервер включён постоянно, cloudflared настроен на Restart, не зависит от интерактивного терминала и имеет исходящий доступ к сети Cloudflare (UDP/TCP 7844). При ошибке авторизации проверить token этого туннеля через защищённую настройку сервера; не публиковать его в чат, репозиторий или журналы.

## Если connector запускается в Docker

Найти существующий контейнер (`docker ps -a`), проверить его logs и restart policy. Предпочтительно восстановить имеющийся connector и его конфигурацию, сохраняя текущий tunnel ID и DNS. Если прежнее развёртывание отсутствует, подготовлен `deploy/compose.tunnel.yaml` для существующего remotely managed tunnel.

1. На сервере сохранить существующий tunnel token в `/etc/pavel-arena/tunnel.env` с правами 600 (`TUNNEL_TOKEN=...`). Token доступен владельцу туннеля в Cloudflare, а не извлекается из публичного URL. Не использовать тестовое значение из CI.
2. В Public Hostname существующего туннеля для arena.kpd100.site установить Service `http://api:8000`: cloudflared и API будут в одной Compose-сети. Если нужно сохранить старый origin, использовать прежний connector/маршрут вместо этого overlay.
3. Из checkout `/opt/pavel`:

```bash
docker compose --env-file /etc/pavel-arena/tunnel.env -f compose.yaml -f deploy/compose.tunnel.yaml config --quiet
docker compose --env-file /etc/pavel-arena/tunnel.env -f compose.yaml -f deploy/compose.tunnel.yaml up -d --build
docker compose --env-file /etc/pavel-arena/tunnel.env -f compose.yaml -f deploy/compose.tunnel.yaml logs --tail=50 cloudflared
curl -fsS http://127.0.0.1:8000/live
curl -fsS http://127.0.0.1:8000/health
curl -fsS https://arena.kpd100.site/live
curl -fsS https://arena.kpd100.site/health
```

Образ cloudflared закреплён по digest проверенного 2026.3.0, запуск с `restart: unless-stopped`. В docker logs должны появиться Registered tunnel connection; в Cloudflare — healthy connector; внешний /live должен вернуть JSON арены, а не страницу 1033. /health обязан вернуть 200 только после свежего успешного рыночного цикла. Запуск туннеля сам по себе не подтверждает работу торговли.

## Проверка устойчивости

Закрыть браузер и терминал; через внешний /health проверить новые timestamps, затем перезапустить cloudflared и worker, проверить восстановление без утраты БД. Проверить запуск после reboot сервера в эксплуатационное окно. Внешний мониторинг должен отслеживать отдельно доступность домена и /health. Для подтверждения 24/7 наблюдать состояние минимум сутки. Стопы при недоступном рынке не гарантируют исполнения; причины блокировки должны оставаться видимыми в интерфейсе.

Общий запуск, backup и HTTPS без туннеля описаны в OPERATIONS.md. Этот файл не является утверждением, что перечисленные действия были выполнены на сервере пользователя.
