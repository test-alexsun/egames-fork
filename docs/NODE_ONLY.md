# Node + Subscription с удалённой панелью

`install-node.sh` добавляет inbound и Hosts к **существующей** установке оригинального
[eGames](https://github.com/eGamesAPI/remnawave-reverse-proxy). Локальная панель,
PostgreSQL и Redis этому режиму не нужны. Старый `install.sh` сохраняет сценарий
Panel + Node. Поддержаны Debian 12/13 и Ubuntu 24.04; API-адаптер проверен для
Panel 3.4.7 / Node 3.4.3. Неизвестные версии отклоняются до изменения профиля.

```text
Удалённая Panel --защищённый Node API--> Node
Internet TCP 443 --> Xray REALITY --> /dev/shm/nginx.sock (TLS, PROXY v1)
                                     --> Nginx: node domain / SelfSteal
                                     --> Nginx: subscription domain --> 127.0.0.1:3010
                                     --> WS / XHTTP / gRPC --> loopback Xray
Internet UDP 443 --> native Xray Hysteria2 (при поддержке установленного core)
Subscription --> HTTPS Panel API + Bearer token + существующая gate cookie
```

## Подготовка и DNS

Сохраните SSH, Compose, Nginx, TLS, firewall и полные API-объекты панели в каталоге
root 0700, файлы 0600. Запишите версии и image digests. Проверьте A/AAAA обоих
доменов против реальных адресов VPS. Для REALITY используйте DNS only без CDN.
Не добавляйте AAAA, если IPv6 слушатель и firewall не проверены.

Изучите исходники актуального eGames, затем установите его Node-only вариант с
Nginx, настоящим `secretKey` из `/api/keygen` существующей панели и её IP. Не
генерируйте фиктивный SECRET_KEY. Через поддерживаемый API создайте отдельный
Config Profile и Node, исходный REALITY Host и добавьте inbound в нужные Internal
Squads. Используйте уникальный основной tag, например `DE126-REALITY`.
Профиль должен принадлежать только целевой ноде. Сохраняйте все существующие ключи.

Node API 2222/TCP открывается **только** IP панели; SSH, TCP 443 и временный
HTTP-01 TCP 80 разрешаются отдельно. Не сбрасывайте firewall. На этом VPS не
должно быть контейнера `remnawave/backend`; адаптер остановится, если найдёт его.

## Одна Nginx для Node и Subscription

Последовательный запуск стандартных Node-only и Subscription-only установок
конфликтует: последний создаёт вторую Nginx на TCP 443. Вместо этого сохраните
Node-only Compose и используйте проверенные render-функции eGames
`src/nginx/install_sub.sh` для сервиса Subscription и его vhost. Добавьте **только**
subscription service в существующий Compose; Nginx и её контейнер остаются одни.

Subscription bind: `127.0.0.1:3010:3010`. В её vhost замените `listen 443 ssl` на
`listen unix:/dev/shm/nginx.sock ssl proxy_protocol`. Включите HTTP/2; направьте
PROXY protocol real IP только от loopback. Не добавляйте второй default server
или повторные глобальные map/upstream. Исходный REALITY `serverNames` должен
включать оба SNI, если установленный core иначе отклоняет subscription SNI.
Изменение `serverNames` существующего рабочего REALITY требует отдельного анализа;
у новой ноды задавайте оба имени сразу.

Сертификаты должны покрывать оба домена (один SAN-сертификат или отдельные
lineages). Монтируйте **каталоги** `live/<lineage>` и `archive/<lineage>` read-only,
чтобы обновление symlink было видно контейнерам. Hysteria2 требует доступных
сертификата и ключа также внутри Node. Никогда не используйте chmod 777.
Проверяйте кандидат установленной `nginx -t` перед записью и reload. Для HTTP-01
предпочтителен постоянный webroot на TCP 80 и deploy-hook, перечитывающий
сертификаты Nginx и Node. Подтвердите `certbot renew --dry-run`.

## Авторизация и несколько страниц подписок

Укажите `REMNAWAVE_PANEL_URL=https://panel.example.com`, `REMNAWAVE_API_TOKEN` и
`EGAMES_COOKIE=NAME=VALUE` в root-only окружении Subscription. Cookie должна
совпадать с текущей защитой панели. Публичные подписки не требуют этой cookie:
она применяется только между Subscription backend и панелью. Новый
административный интерфейс не создаётся; защита панели не отключается.

Можно обслуживать несколько subscription frontend с разными доменами, используя
одну панель и один shortUuid. Не меняйте её глобальный `SUB_PUBLIC_DOMAIN` для
переноса старых страниц. Проверяйте содержимое `/SHORT_UUID/json` на каждом
домене; корневая `/` без пользовательского идентификатора не доказывает работу.

## Дополнительные inbound

| Вариант | Публичный порт | Условия |
|---|---|---|
| VLESS TCP REALITY Vision | TCP 443 | Сохраняется существующий inbound |
| VLESS WS TLS | TCP 443 | Nginx → loopback, случайный path |
| VLESS XHTTP TLS | TCP 443 | Nginx → loopback, случайный path |
| Trojan gRPC TLS | TCP 443 | HTTP/2, Nginx → loopback, serviceName |
| VLESS XHTTP REALITY | отдельный TCP | Без несовместимого Vision flow |
| VLESS REALITY ML-KEM768 | отдельный TCP | Реальный `vlessenc` установленного core |
| Shadowsocks 2022 AES-256-GCM | отдельный TCP/UDP | Безопасный 32-байтовый server key |
| Hysteria2 | UDP 443 | Native `hysteria/version=2`, доступные TLS-файлы |

Все кандидаты проверяются **бинарником установленной Node**. Неподдерживаемые
варианты пропускаются с причиной. 3x-ui служит функциональным ориентиром; её
VMess/TUIC/WireGuard и параметры PQ не переносятся в Remnawave без API-адаптера.

## Запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.node.example.yaml /root/node.yaml
chmod 600 /root/node.yaml
# Укажите node_uuid и реальные домены. Секреты обнаружатся в Subscription.
sudo bash install-node.sh -c /root/node.yaml --check
sudo bash install-node.sh -c /root/node.yaml --dry-run
sudo bash install-node.sh -c /root/node.yaml --backup
sudo bash install-node.sh -c /root/node.yaml --install
sudo bash install-node.sh -c /root/node.yaml --status
```

API URL/token/cookie обнаруживаются из единственного Subscription контейнера.
Явные `panel_api_url`, `token_file`, `cookie_file` имеют приоритет; приватные файлы
проверяются на владельца, права и symlink. Передача API credentials на целевой VPS
должна быть разрешена владельцем. Нужен именно административный API token с
правами управления профилями/Node/Hosts/Squads, а не фиктивный browser session.

`node_uuid` обязателен даже при одной ноде. Адрес Node из панели должен совпадать
с локальным адресом VPS; сверяются версии Xray, активный профиль и Squad.
Теги имеют стабильный префикс `EGADDON-<первые 8 символов node_uuid>`, поэтому
добавление второй ноды не конфликтует с прежней. Для имен Hosts используется
проверенная GeoIP-страна или явно заданный подтверждённый `host_country_code`.

## Повторный запуск, обновление и восстановление

`--install` создаёт только отсутствующее; `--repair` и `--update` сверяют состояние,
сохраняют ключи, UUID и paths. Внешние изменения управляемых inbound или Nginx
вызывают отказ: автоматического затирания пользовательской правки нет.
`--update` не обновляет Docker images; обновление eGames/Node выполняется отдельно
с проверкой совместимости. `--dry-run`, `--check`, `--status` не пишут профиль,
Hosts, Nginx, firewall или state; валидатор Nginx использует временный файл 0600,
удаляемый после проверки.

Перед каждой мутацией создаётся snapshot и журнал в
`/var/lib/egames-node-injector` (0700/0600). При ошибке выполняется обратная
транзакция с read-back и проверкой drift. `--restore` обращает последнюю
транзакцию; `--uninstall` обращает собственную историю, удаляя только созданные
дополнением объекты. Базовая Node, Subscription, сертификаты и исходный REALITY
этими командами не удаляются. `--backup` создаёт ручной snapshot; произвольный
старый snapshot не импортируется слепо. Не удаляйте state для обхода защиты.
Если контейнер пересоздан и его ID изменился, recovery guard требует ручной
проверки соответствия backup этой установке.

## Проверки и ошибки

Проверяйте Docker/Compose, `nginx -t`, фактический Xray, TCP/UDP listeners,
Node connected и реальные пользовательские подписки. Для встроенной проверки
укажите `subscription_test_url_file` с приватным HTTPS URL `/SHORT_UUID/json`.
Без этого выводится `NOT TESTED`; HTTP 200 и TCP-connect не считаются VPN-тестом.
После установки проверьте каждым профилем HTTPS через внешний VPN-клиент,
SS2022 UDP, повторную установку без дубликатов и рестарт.

- 404 панели: проверьте cookie; 401: token; redirect не выполняется автоматически.
- 502 подписки: её URL/API token/cookie, доступность панели и backend 3010.
- Неактивная Node: настоящий secretKey, firewall 2222 только с панели, адрес Node.
- Конфликт tag: неверный префикс или чужой managed state; не присваивайте объект.
- Shared Config Profile: создайте отдельный профиль через Panel до запуска.
- Hysteria2 skipped: проверьте UDP 443 и TLS mounts в Node.
- Partial rollback: сохраните journal и диагностируйте внешний drift; не запускайте
  повторную установку поверх незавершённой транзакции.

Не публикуйте private backup, подписки, токены, cookies и полные JSON пользователей.
Отчёты должны явно разделять реальные клиентские проверки и статическую валидацию.
