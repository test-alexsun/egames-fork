# ПРАВИЛЬНЫЙ ПОРЯДОК УСТАНОВКИ

1. Подготовьте VPS с Debian 13, root или sudo, публичным IPv4, доступом в интернет,
   достаточными RAM и свободным местом. Рекомендуется свежая система. Направьте DNS
   доменов панели, подписки и ноды на VPS и откройте необходимые порты.
2. Установите [официальный eGames](https://github.com/eGamesAPI/remnawave-reverse-proxy),
   выбрав Panel + Node на одном VPS, Nginx, HTTPS и домены. Для защиты панели
   можно выбрать cookie authentication. Torrent Blocker и защита от сканеров —
   отдельные функции официального eGames, этот проект их не устанавливает.

   ```bash
   bash <(curl -Ls https://raw.githubusercontent.com/eGamesAPI/remnawave-reverse-proxy/refs/heads/main/install_remnawave.sh)
   ```

3. Убедитесь, что доступны панель и подписка, Node подключена, исходный REALITY
   работает, сертификаты действительны, контейнеры запущены и Nginx проходит `nginx -t`
   внутри своего контейнера. Устанавливайте egames-fork только после этих проверок.
4. После публикации bootstrap в main его можно скачать, просмотреть и запустить:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/bootstrap.sh -o /tmp/egames-fork-bootstrap.sh && sudo bash /tmp/egames-fork-bootstrap.sh
   ```

   Bootstrap создан, но полноценное интеграционное тестирование на чистом Debian 13
   пока не завершено. Для воспроизводимости используйте `EGAMES_FORK_REF` с полным
   SHA проверенного коммита; для проверки самого bootstrap скачайте его по тому же SHA.
   Существующий checkout с другим коммитом или локальными изменениями не перезаписывается.

После установки доступны `sudo egames-fork check`, `status`, `repair`, `update`,
`backup`, `restore` и `uninstall`. Проверки реального клиентского подключения и
формирования подписки автоматически не выполняются и выводятся как NOT TESTED.

# eGames / Remnawave: безопасное дополнение протоколов

Установщик расширяет **существующий активный Config Profile** Remnawave поверх
eGames Panel + Node + Nginx на одном VPS. Сохраняет TCP 443, исходные inbound,
outbounds, DNS, routing, policy, Hosts, сертификаты и защиту панели.

История исправлений: [docs/AUDIT.md](docs/AUDIT.md). Реальная установка на Debian 13,
подписка, внешние подключения и рестарт проверены 27 октября 2026:
[docs/LIVE_SW126.md](docs/LIVE_SW126.md). Результаты относятся к указанным версиям
и одному VPS; синтаксическая проверка сама по себе не подтверждает клиентский трафик.

Для предварительного анализа переименования технических inbound-тегов внутри
сквадов доступен [автономный планировщик](docs/INBOUND_TAG_MIGRATION.md).
Он не изменяет панель; автоматическое применение миграции ещё не реализовано.

## Требования и границы совместимости

| Компонент | Условия |
|---|---|
| ОС | Debian 13 (приоритет), Debian 12, Ubuntu 24.04; системные интеграционные тесты ещё нужны |
| Panel | Адаптер проверен по исходникам **3.4.7**; другие версии останавливают применение |
| Node | Адаптер проверен по исходникам **3.4.3**; версия должна сообщаться Panel |
| Xray | На VPS **26.7.28**, внешний клиент **26.10.21**; проверяется тот core, который запускает Node |
| Nginx | Схема eGames с `unix:/dev/shm/nginx.sock ssl proxy_protocol`, HTTP/2; на VPS проверен **1.30.6** |
| Docker | На VPS Engine **29.9.2**, Compose **5.6.1**; Node/Nginx в host network, API Panel доступен локально |
| Python | Python 3.10+; `requests`, `PyYAML`, `cryptography` из requirements.txt |
| Прочее | `ip`, `ss`, root для применения; действующий администраторский API-токен |

Engine/Compose проверяются реальными `docker inspect`, `docker compose version` и
доступностью контейнеров, без заявления о тестировании всех их версий. jq и OpenSSL CLI
не нужны: JSON/YAML разбираются структурно, сертификаты проверяются cryptography.

Caddy, удалённая Node, общий профиль нескольких нод, неоднозначный
выбор контейнеров/ноды и нестандартная структура Nginx требуют отдельного адаптера.
При таких условиях установщик прекращает применение с диагностикой.

В рабочей ветке `audit/sw126-live-20261027` добавлен адаптер сохранения встроенных
Node Plugins (Torrent Blocker, Ingress/Egress Filter) для Panel 3.4.7 / Node 3.4.3.
Он читает `pluginConfig` по UUID, требует NET_ADMIN и проверяет, что привязка и
конфигурация плагина не изменились перед применением и после синхронизации.
Объекты плагинов не записываются. Lifecycle hooks, shared lists, неизвестные поля
и включённый Connection Drop блокируют применение. На VPS проверено сохранение
плагина при установке и рестарте, Ingress Filter с 271 записью, реальная блокировка
BitTorrent из изолированного namespace и появление отчёта в панели.

## DNS и сеть

```text
panel.example.com -> VPS_IP
sub.example.com   -> VPS_IP
node.example.com  -> VPS_IP
```

Допустим корневой домен selfsteal вместо `node.example.com`. DNS не изменяется.
Домен Node берётся из существующего REALITY serverNames; адрес управления Node
вроде `172.30.0.1` не используется как публичный адрес Host.

```text
Internet TCP:443 -> существующий Xray REALITY
                    |-- VLESS REALITY / Vision (существующие пользователи Panel)
                    `-- /dev/shm/nginx.sock, TLS + PROXY protocol
                          |-- panel domain -> Panel (защита сохранена)
                          |-- sub domain   -> Subscription Page
                          `-- node/selfsteal domain
                                |-- сайт-прикрытие
                                |-- случайный WS path    -> loopback Xray VLESS WS
                                |-- случайный XHTTP path -> loopback Xray VLESS XHTTP
                                `-- gRPC serviceName     -> loopback Xray Trojan gRPC

Internet отдельные TCP       -> XHTTP REALITY / VLESS PQ
Internet отдельный TCP+UDP   -> Shadowsocks 2022
Internet UDP:443             -> Hysteria2, только при выполнении условий
```

Дополнительный публичный HTTPS listener не создаётся. Новые HTTP-транспорты используют
локальный TCP, общий Unix socket исходного eGames сохраняется. Дополнительные UDS и
их lifecycle/ownership adapter пока не реализованы; широкие chmod/chown не применяются.

## Протоколы и итоговые Hosts

| Inbound/tag | Публичный Host | Реализация / проверка |
|---|---|---|
| Существующий Steal / VLESS REALITY Vision | исходный домен:443 | Сохраняется без смены ключей и listener; UUID/flow назначает Panel |
| `EGADDON-WS` | node domain:443, TLS, случайный path | VLESS WS через существующий Nginx, Upgrade/Connection, timeouts |
| `EGADDON-XHTTP` | node domain:443, TLS, случайный path | XHTTP auto, buffering off, loopback upstream |
| `EGADDON-GRPC` | node domain:443, TLS, случайный serviceName | Trojan gRPC, HTTP/2, `grpc_pass`, Host.path = serviceName |
| `EGADDON-XREALITY` | node domain:выбранный TCP | XHTTP REALITY без Vision; конфиг должен принять установленный Xray |
| `EGADDON-PQ` | node domain:выбранный TCP | VLESS Encryption ML-KEM-768 + RAW + REALITY, flow пустой; без генератора пропускается |
| `EGADDON-SS2022` | node domain:выбранный TCP+UDP | `2022-blake3-aes-256-gcm`, криптографический 32-байтный server key |
| `EGADDON-HY2` | node domain:443 **UDP** | Native `hysteria`, version=2 в protocol и transport; только при доступных Node TLS mounts и свободном UDP443 |
| VMess WS TLS | Не создаётся | В проверенном backend нет управляемых VMess пользователей и генератора подписки; альтернатива VLESS WS |

Предпочтительный SS2022 AES-128 отсутствует в проверенном адаптере Panel; применяется
поддерживаемый AES-256. Внешний Hysteria-сервис не устанавливается: проверенный
Xray/Panel уже имеют native support, а при отсутствии prerequisites выводится причина пропуска.

Все новые inbound сначала проверяются **установленным** Xray. Непринятый optional
inbound пропускается с явной причиной; записи-заглушки не создаются. Таблица CLI
показывает фактический выбранный набор и реальные порты конкретного запуска.

UUID, Trojan passwords и пользовательские SS/Hysteria credentials принадлежат
пользователям Remnawave и назначаются самой Panel. Установщик не создаёт отдельного
скрытого пользователя и не внедряет UUID из модели 3x-ui. Hosts связываются с UUID
inbound профиля; новые inbound добавляются в activeInbounds выбранной ноды и в те
Internal Squads, где уже разрешён исходный 443.

| Порт | Владелец / правило |
|---|---|
| TCP 443 | Исходный Xray, без переноса на Nginx Stream |
| UDP 443 | Только HY2 и только если свободен; HTTP3/QUIC может конфликтовать |
| Случайные loopback TCP 20000–59999 | WS/XHTTP/gRPC; наружу не открываются |
| Отдельные TCP 20000–59999 | XHTTP REALITY и PQ; проверка занятости перед применением |
| Отдельный TCP+UDP 20000–59999 | SS2022 |

Активный UFW получает только отсутствующие public rules с комментарием `EGAMES_ADDON`.
Неактивный UFW не включается; nftables, firewalld и firewall провайдера автоматически
не меняются. Их доступность нужно проверить отдельно. Firewall не сбрасывается.

## Установка и проверка

Сначала установите исходный eGames, выбрав Panel + Node на одном VPS и Nginx,
и убедитесь, что панель, подписки и исходный REALITY уже работают. Здесь не выполняется
переустановка eGames или базы данных.

Подготовка зависимостей в checkout (PEP 668 совместимо с Debian 13):

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv iproute2
git clone https://github.com/test-alexsun/egames-fork.git
cd egames-fork
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Для воспроизводимости зафиксируйте проверенный commit после clone и сначала
испытайте checkout на тестовом VPS. Используйте install.sh из этого checkout:
сохранённая ранее копия установщика может не содержать исправлений аудита.

Одна команда диагностики после подготовки checkout:

```bash
sudo bash install.sh --dry-run
```

Токен автоматически читается из `/usr/local/remnawave_reverse/token`; путь можно
переопределить через config. Если поддерживаемого токена нет, используется скрытый
интерактивный ввод; в non-interactive режиме — отказ с инструкцией. Токен страницы
подписки не принимается автоматически за администраторский. Пути Nginx и cert/key,
network/mounts, контейнеры и API port обнаруживаются из Docker inspect и профиля.

Запуск без флагов также означает **dry-run**. Диагностика не устанавливает пакеты,
не создаёт backup/state, не меняет API-объекты/конфиги и не перезапускает сервисы.
Выполняются read-only Docker/API вызовы и штатные тесты конфигураций.

Для `nginx -t` временный конфиг создаётся внутри обнаруженного контейнера через
`mktemp` с правами 0600 и удаляется в `finally`. Использование `/dev/stdin` для
основного конфига Nginx на реальном Debian-контейнере оказалось несовместимым:
проверка возвращала `no "events" section`, хотя исходный конфиг содержал `events`.
Рабочий bind-mounted конфиг предварительная проверка не изменяет.

```bash
sudo bash install.sh --check
sudo bash install.sh --status
sudo bash install.sh --install
sudo bash install.sh --repair
sudo bash install.sh --update
```

`--install`, `--repair` и `--update` сверяют один и тот же желаемый набор. Повторный
запуск сохраняет ключи, пути, порты, UUID Hosts. Внешние изменения собственного inbound
или managed Nginx-блока приводят к отказу вместо перезаписи. Испорченные поля собственных
Hosts восстанавливаются с сохранением UUID. Заимствование чужих объектов по remark запрещено.

Отображаемые названия Hosts в панели и подписках имеют единый формат:
`флаг страны | протокол | транспорт и защита`. Пример для VPS в Финляндии:

| Inbound | Название Host |
| --- | --- |
| Steal | 🇫🇮 \| VLESS \| TCP REALITY Vision |
| EGADDON-WS | 🇫🇮 \| VLESS \| WS TLS |
| EGADDON-XHTTP | 🇫🇮 \| VLESS \| XHTTP TLS |
| EGADDON-GRPC | 🇫🇮 \| Trojan \| gRPC TLS |
| EGADDON-XREALITY | 🇫🇮 \| VLESS \| XHTTP REALITY |
| EGADDON-PQ | 🇫🇮 \| VLESS \| TCP REALITY ML-KEM768 |
| EGADDON-SS2022 | 🇫🇮 \| Shadowsocks \| 2022 AES-256-GCM |
| EGADDON-HY2 | 🇫🇮 \| Hysteria2 \| QUIC TLS |

Страна определяется по публичному IPv4 домена ноды через HTTPS GeoIP (`ipwho.is`,
резервный сервис `ipinfo.io`), отдельной сессией без токена панели. При ошибке GeoIP,
нескольких IPv4 или непубличном адресе укажите проверенный ISO-код страны в
`config.yaml`, например `host_country_code: "FI"`. Этот override отключает GeoIP-запросы.
Диагностика показывает будущие названия; изменения применяются через `--install`,
`--repair` или `--update` и сохраняются при повторном запуске.

Для исходного Host на REALITY TCP 443 изменяется только `remark`, если он привязан
к исходному inbound активного профиля и его адрес совпадает с доменом ноды.
Его UUID, теги и остальные поля сохраняются; эта правка включена в журнал отката.
Технические inbound tags и конфигурация соединений для переименования не меняются.

`--install` применяет изменения профиля через Panel (она синхронизирует Xray) и
перезагружает только конфигурацию Nginx. Это команда применения на VPS; автоматический
запуск этих действий на production в ходе аудита не выполнялся.

Если однозначное обнаружение невозможно, используйте только необходимые overrides:

```bash
cp config.example.yaml config.yaml
chmod 600 config.yaml
sudo bash install.sh -c config.yaml --dry-run
```

Старый `target_inbounds` config отклоняется: он описывал небезопасный standalone TLS
и фиктивный PQ. Старые `fix-*.py` теперь используют единый транзакционный сценарий:
без `--apply` диагностика, с `--apply` repair. Bash recovery entrypoints также по
умолчанию диагностические, без принудительных остановок/удалений.

## Backup, rollback и удаление

Состояние `/var/lib/egames-injector/`: `state.json`, `journal.json`, `backups/`,
`transactions/`. Файлы сразу создаются с 0600, каталоги с 0700; они содержат секреты
профиля и не предназначены для публикации.

```bash
sudo bash install.sh --backup
sudo bash install.sh --restore
sudo bash install.sh --uninstall
```

Перед записью сохраняются snapshot и журнал намерений. После API-операций выполняется
GET для проверки фактического результата. Неясный HTTP timeout сверяется с API,
а не считается автоматически ни успехом, ни отказом. При ошибке дальнейшее применение
прекращается и выполненные операции откатываются в обратном порядке.

`--restore` откатывает последнюю транзакцию. `--uninstall` проходит историю своих
транзакций в обратном порядке; существующие до установки объекты сохраняются.
Произвольный файл из `--backup` автоматически не импортируется — это ручной snapshot.

Если внешний администратор изменил объект после установки, rollback не затирает его:
появится **Rollback INCOMPLETE**, журнал сохранится, дальнейшая установка блокируется.
Не удаляйте журнал или состояние для обхода ошибки; сопоставьте изменения и backup.
Read-back подтверждает объекты/файлы, но не реальный клиентский трафик.

Nginx конфиг, смонтированный отдельным файлом, записывается с сохранением inode:
`os.replace` на хосте оставил бы контейнер на старом bind-mounted inode. Перед записью
проверяется staged-конфиг, сохраняется backup; после записи выполняются `nginx -t` и reload.
Сам журнал/состояние записываются через атомарную замену. После reboot профиль остаётся
в Panel, routes — в исходном Nginx source, правила UFW — persistent; reboot-тест ещё нужен.

## Обновление

Сначала `--check` и `--backup`. Обновляйте исходники обычным Git workflow после проверки
локальных изменений; установщик не выполняет `git reset --hard`, не скачивает скрипт
поверх checkout и не включает ежедневный таймер. Затем обновите venv и выполните
`--dry-run`, после проверки — `--update`. При обновлении Panel/Node до неизвестной
версии сначала требуется ревизия адаптера и генераторов подписок.

## Типичные ошибки

| Сообщение | Действие |
|---|---|
| `no reviewed adapter` | Установленная версия ещё не проверена; не обходить guard сменой номера версии |
| `Ambiguous/missing ...` | Указать UUID/контейнер в config; первая попавшаяся нода не выбирается |
| `Selected ... does not refer to this VPS` | Нода удалённая или неверно выбрана; проверить топологию |
| `No Docker mount exposes ...` | Требуемый путь не виден контейнеру; сначала спроектировать корректный mount |
| `Hysteria2 skipped` | Посмотреть причину: UDP443, certificates или Xray validation; TCP443 сохраняется |
| `Unowned inbound tag conflict` | Старый/чужой объект не присваивается дополнению; нужна отдельная миграция |
| `Nginx routes ... modified` | Сопоставить внешние правки с managed block; установщик их не затирает |
| `API HTTP 401/403` | Проверить срок/права admin API-token; response body с секретами не печатается |
| `unfinished transaction` | Выполнить `--restore`, сохранить журнал при неполном откате |

После применения проверьте доступность панели по её обычной защищённой ссылке,
реальную пользовательскую ссылку подписки и соединение **с внешнего клиента** по каждому
созданному Host. Корень subscription-сайта сам по себе не является тестом подписки.
Дополнение проверяет конфиги, API read-back, connected Node и локальные listeners;
автоматического end-to-end теста подписки и клиента внутри CLI пока нет.
Отдельный аудит подтвердил все восемь профилей до и после рестарта;
первые отказы и успешные повторы сохранены, поскольку сеть VPS давала тайм-ауты.

## Автоматические тесты

```bash
python3 -m unittest discover -s tests -v
for script in *.sh tests/*.sh; do bash -n "$script"; done
shellcheck *.sh tests/nginx-docker.sh
XRAY_BINARY=/path/to/verified/xray NGINX_BINARY=/path/to/nginx python3 tests/validate_binaries.py
```

Fixtures не требуют production VPS. Проверяются сохранение профиля, отсутствие дублей,
dry-run, повторная установка, Host repair, backup/restore/uninstall, API failures/timeouts,
несовместимые версии, конфликты TCP/UDP, missing mounts/certificates и внешний drift.

GitHub Actions использует Linux mock-tests, POSIX permissions, официальный Xray и
одноразовый `nginx:1.30` без сети. CI добавлен, но в этой сессии не запускался.
Текущая ветка: **45 passed на Debian 13**, **44 passed, 1 skipped на Windows**.
Реальные Xray/Nginx configuration checks и клиентские тесты выполнены на VPS;
отдельный Windows-тест Nginx заменяет Unix listener на TCP.

## Лицензия

MIT, в соответствии с исходным проектом. Официальные компоненты сохраняют свои лицензии.
