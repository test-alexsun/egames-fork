# eGames / Remnawave: дополнение существующей установки

**Статус ветки: NOT READY для production.** Исправления review подготовлены
для проверки; системные acceptance gates ещё открыты.
Итог: [CODEX_04_RELEASE](docs/CODEX_04_RELEASE.md),
[общий план внедрения](docs/PRODUCTION_DEPLOYMENT.md).

Проект расширяет активный Config Profile через API Remnawave. Не переустанавливает
Panel/Node, не редактирует БД и runtime Node, не создаёт пользователей, не меняет
существующие ключи и сертификаты. Текущая реализация и ограничения:
[CODEX_02_IMPLEMENTATION.md](docs/CODEX_02_IMPLEMENTATION.md).

## Совместимость

| Компонент | Граница адаптера |
|---|---|
| Основной режим | Panel + Node + Subscription + Nginx на одном VPS; Node/Nginx host networking, общий `/dev/shm` |
| ОС / Python | Bootstrap: Debian 13. Lockfile и CI: CPython 3.13; другие Python не квалифицированы |
| Panel / Node | Только 3.4.7 / 3.4.3; неизвестные версии блокируются |
| Xray | Проверяется реальный бинарник Node; синтаксические тесты 26.10.21, сетевой acceptance новых версий обязателен |
| Nginx | eGames Unix TLS + PROXY protocol, явный `http2 on` для gRPC |
| Node-only | Только read-only inventory/check/status/dry-run через явный HTTPS API удалённой Panel |

Shared profile, manual clients, snippets, неоднозначные контейнеры/Node и
неподдерживаемая топология блокируют изменения. Поддержка старых OS guards
в Python не означает проведённых системных испытаний на этих ОС.

Сертификаты должны быть видимы через directory mounts с корректным live/archive
lineage. Отдельные certificate/key file bind mounts блокируют применение: при
ACME rotation они удерживают старый inode. Сравниваются текущий публичный сертификат
на хосте и в Nginx, файлы TLS в Node. Установщик не исправляет Compose/mounts или
renewal hooks автоматически. Нужен отдельный стендовый renewal acceptance.

## Установка после eGames

### Сервер и Debian 13

Нужен Debian 13 VPS с root/sudo, доступом к apt/GitHub/PyPI,
синхронизированным временем и местом для полного backup. Дополнение требует
минимум 20 MiB для своей транзакции; это не sizing Panel/БД. CPU/RAM выбираются
по требованиям upstream и нагрузке; нагрузочные испытания ветки не проведены.

```bash
cat /etc/os-release
timedatectl status
df -h /
sudo apt-get update
sudo apt-get install -y ca-certificates git curl python3 python3-venv iproute2 util-linux
```

Сохраните SSH-доступ и консоль провайдера. Firewall/SSH настраиваются по политике
владельца. Не открывайте Panel/PostgreSQL/Node management всему Интернету.

### Исходный eGames и Panel + Node

Изученный upstream eGames: `93e6631aae5f7bff28eadfc45faab43150cc22c6`
(reference 3.8.3). Это идентификатор исходников, не квалификация всех загрузок
его установщика. Не выполняйте непроверенный `curl | bash` от root.

```bash
git clone --no-checkout https://github.com/eGamesAPI/remnawave-reverse-proxy.git egames-upstream
git -C egames-upstream checkout --detach 93e6631aae5f7bff28eadfc45faab43150cc22c6
git -C egames-upstream rev-parse HEAD
less egames-upstream/install_remnawave.sh
# После проверки скрипта, модулей и загрузок владельцем стенда:
sudo bash egames-upstream/install_remnawave.sh
```

В меню upstream выберите совместные **Panel + Node**, subscription page и
**Nginx**. Подготовьте три доменных имени: Panel, подписки, selfsteal Node.
Проверьте установленные Panel 3.4.7 / Node 3.4.3: moving images upstream могут
дать другие версии, которые addon отклонит. Сначала проверьте вход в Panel,
gateway/cookie protection, connected Node, исходный TCP443 REALITY и подписку.
Addon не переводит Caddy/3x-ui в поддерживаемую топологию.

### DNS и Nginx

Создайте A трёх имён на VPS; AAAA — только при рабочем IPv6. Node endpoint
должен указывать прямо на VPS, без HTTP CDN proxy. Проверьте DNS снаружи,
SAN и сроки сертификатов. Доступность HTTP-01 зависит от выбранного ACME challenge.

Nginx принимает TLS + PROXY protocol через `/dev/shm/nginx.sock`, Xray владеет
TCP443. В selfsteal server нужен `http2 on;`, host networking и общий `/dev/shm`.
Сохраните защищённые Panel/API/subscription locations; fixture из tests не
заменяет production config. Проверка: `docker exec <NGINX_CONTAINER> nginx -t`.
TLS lineage монтируется каталогами с live symlink и archive target; cert/key
должны читаться в Nginx и Node. Отдельные certificate file binds блокируются.
Renewal hook, обслуживаемый serial и HY2 reload проверяются на стенде отдельно.

### Дополнение одной командой

Сначала установите и проверьте [официальный eGames](https://github.com/eGamesAPI/remnawave-reverse-proxy):
исходный REALITY, защищённые Panel/Subscription, сертификаты и подключение Node.
Bootstrap не устанавливает eGames, Docker или плагины.

Скачайте `bootstrap.sh` из проверенного полного commit SHA и изучите его. После
публикации этого коммита установка выполняется одной командой:

```bash
sudo env EGAMES_FORK_REF=<FULL_REVIEWED_SHA> bash ./bootstrap.sh
```

Bootstrap требует тот же SHA для исходников и собственного содержимого; moving
`main` не принимается. Существующий checkout `/opt/egames-fork` с другим SHA,
чужим origin или локальными изменениями не перезаписывается. Создаются venv,
зависимости по `requirements.lock`, приватный backup и CLI wrapper. Перед записью
показывается точный план и требуется `APPLY`. Для заранее согласованного запуска
есть `--yes`; `--dry-run` готовит зависимости и показывает план без изменения
Remnawave/Nginx/firewall. Ошибки применения вызывают guarded rollback.

Рекомендуемый SHA для проверки указан в CODEX_04; production SHA пока не одобрен.
Полный SHA публичного кандидата указан в CODEX_04_RELEASE.
Для проверки перенесённого checkout на отдельном стенде:

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes --only-binary=:all: -r requirements.lock
sudo bash install.sh --dry-run
sudo bash install.sh --install
```

Admin token читается из `/usr/local/remnawave_reverse/token`, явного `token_file`
или `PANEL_API_TOKEN`. Token/config/cookie файлы должны принадлежать запускающему
пользователю, иметь 0600 и не содержать symlink в пути. Не передавайте секреты
в аргументах команд. Для YAML: `sudo chmod 600 config.yaml` и соответствующий owner.
`config.example.yaml` содержит поддерживаемые переопределения. При нескольких Node
нужен `NODE_UUID` либо `node_uuid` в config. Домен берётся из существующего REALITY;
country code можно задать явно, иначе используется отдельный HTTPS GeoIP-запрос.

## Протоколы и имена

| Возможность | Реализация | По умолчанию |
|---|---|---|
| VLESS REALITY Vision | Существующий TCP443, сохранение ключей и UUID; flow проверяется по правилам Panel | Обязательный baseline |
| VLESS WS TLS | Loopback Xray + TLS в существующем Nginx | WS: required |
| VLESS XHTTP TLS | Loopback, XHTTP auto, buffering off | XHTTP: required |
| VLESS XHTTP REALITY | Прямой отдельный TCP, без Vision | XREALITY: required |
| Trojan gRPC TLS | Loopback, Nginx HTTP/2, Host.path=serviceName | GRPC: required |
| Shadowsocks 2022 | AES-256-GCM, 32-byte server key, TCP+UDP | SS2022: required |
| Hysteria2 | Native Xray/Panel `hysteria` version 2, UDP443, проверенные TLS mounts | HY2: optional |
| VLESS Encryption | Реальный ML-KEM-768 generator, RAW+REALITY, пустой flow | PQ: optional |

`required_protocols` позволяет потребовать HY2/PQ или изменить набор. Отсутствие
required capability завершает preflight до записи. Строка `CAPABILITIES` содержит
JSON status/required/reason для каждого варианта. VMess и фиктивные PQ не создаются.

Новые technical tags: `Vless-WS -tcp`, `Vless-XHTTP -tcp`, `Trojan-gRPC -tcp`,
`Vless-XHTTP -tcp-2`, `Vless-Reality -tcp`, `Shadowsocks-TCP+UDP -tcp+udp`,
`Hysteria2-QUIC -udp`. Пробел поддерживается контрактом Panel и реальным Xray
validator. Коллизии проверяются во всех профилях; label→tag сохраняется в state.

Существующие technical tags, включая `EGADDON-*`, сохраняются. В Panel 3.4.7
rename удаляет inbound и создаёт новый UUID; этот путь отключён по требованию
сохранить объект. [Планирование имён и ограничения](docs/INBOUND_TAG_MIGRATION.md).
Существующие descriptive tags не переименовываются ради добавления пробела.

Новые inbound включаются только в выбранную Node и сквады исходного TCP443.
Повторный запуск сохраняет выключенные Hosts, исключения Squad/Node, UUID,
credentials, лимиты и неизвестные поля API. UFW получает правила только для новых
публичных inbound. Source-restricted, DENY и IPv4-only конфликты не расширяются
молча; внешний firewall/provider имеет статус `not-tested`.

## Команды и восстановление

### Порты и порядок Hosts

| Назначение | Порт / доступ |
|---|---|
| Vision и frontend WS/XHTTP/gRPC | TCP443, публичный |
| HY2 при доступной capability | UDP443, публичный |
| XHTTP REALITY и PQ | Отдельный TCP для каждого из 20000–59999 |
| SS2022 | Один номер из 20000–59999, TCP + UDP |
| WS/XHTTP/gRPC backends | По одному loopback TCP из 20000–59999 |
| Panel / Subscription upstream | Обычно loopback TCP3000 / 3010; сверить Compose |
| Node management | TCP2222, только от Panel/доверенной сети |
| SSH / ACME | По политике сервера и выбранному challenge |

Точные порты выдаёт CHANGE PLAN, номера из старых live-отчётов не являются
defaults. Provider firewall и IPv6 проверяйте отдельно.

Порядок: baseline Host → Config Profile → получить inbound UUID через API →
по одному Host на новый endpoint → новые UUID в исходные Squads и выбранную
Node → runtime verification → state. Исходному Host меняется только remark.
TLS frontend Host использует публичный 443, TLS securityLayer и path/serviceName;
прямые transports — свой public port. Hosts создаёт installer, вручную
дублировать их не нужно. Country remark можно задать `host_country_code`.
Дубликаты binding и смена сохранённого UUID блокируют повтор до writes.

### Проверка подписок и клиентских подключений

Сохраните до/после Host UUID, inbound UUID, disabled flags и memberships.
Получите подписку тестового пользователя через приватный URL: HTTP200,
выбранный формат, разрешённые Hosts, SNI/path/ALPN, отсутствие дублей и
запрещённых endpoint. Не публикуйте subscription URL/UUID/passwords/выдачу
клиента. Enabled Host без разрешающего Squad не даёт пользователю доступа.
Сверьте Xray JSON и URI; sing-box/Clash поддерживают не все варианты.

В Happ импортируйте тестовую подписку, запишите версии Happ/core, проверьте
каждый разрешённый endpoint: handshake, внешний IP, HTTPS download/upload,
DNS и reconnect. Для SS отдельно TCP/UDP, HY2 — UDP, XHTTP — длительный upload.
Сопоставьте время запроса с Node/Nginx logs и реальным outbound traffic.
Отключённые Hosts/доступы ради теста не включайте. Acceptance итоговой ветки
ещё не выполнен и обязателен перед production approval.

### Обновление, удаление, Backup/Restore и Rollback

```bash
sudo bash install.sh --check
sudo bash install.sh --status
sudo bash install.sh --backup
sudo bash install.sh --install
sudo bash install.sh --repair
sudo bash install.sh --update
sudo bash install.sh --restore
sudo bash install.sh --uninstall
```

Без флагов выполняется dry-run. `--repair` и `--update` согласуют конфигурацию и
Hosts; не обновляют Git, Docker images, пользователей или разрешения существующих
inbound. Для автоматизации есть явный `--yes`. После bootstrap те же режимы
доступны как `egames-fork check`, `egames-fork repair` и т. д.

Backup — приватный JSON snapshot профиля/Hosts/Node/Squads/Nginx/plugin, не backup
PostgreSQL, Compose или сертификатов. Произвольный snapshot автоматически не
импортируется. `--restore` компенсирует последнюю транзакцию; `--uninstall` проходит
свою историю в обратном порядке. Восстановление не затирает внешний drift и не
удаляет новые чужие привязки. При `Rollback INCOMPLETE` сохраните journal/state,
восстановите API/диск и повторите recovery после сверки состояния.

Журналы schema 2 связаны с установкой и epoch. Старые журналы до этой версии,
результаты UUID-changing tag migration и чужие установки автоматически не
восстанавливаются. Сохраняйте старые backups для отдельного аудита. Не удаляйте
journal и не подменяйте schema/epoch для обхода guard.

Nginx file bind mount записывается с сохранением inode, с durable intent и
распознаванием только возможного частичного overwrite. Recovery не требует
работающих Node/Nginx или прежнего Docker Id. При остановленном Nginx восстанавливает
файл без запуска сервиса; validate/start выполняются отдельно. При недоступной Panel
локальный Nginx можно восстановить, но API rollback останется incomplete.

Panel API не имеет CAS/revision precondition: остаётся узкое окно между GET и PATCH.
Применение требует окна без параллельного редактирования Panel. Installer locks
защищают другие экземпляры installer, включая разные state-dir, но не Panel UI.

## Node-only

Поддержано только диагностическое чтение уже подготовленной Node. Установка
Node-only самим upstream и отдельно подготовленная Node не подтверждают addon Node-only apply.
Node-only backup/restore/repair/update/uninstall и миграция scoped tags запрещены.

```yaml
topology: node-only
panel_api_url: https://panel.example.com/api
token_file: /root/panel-api-token
node_uuid: <REMOTE_NODE_UUID>
# cookie_file: /root/existing-panel-gateway-cookie
```

`--check --config config.yaml` читает удалённую Panel и локальные Node/Nginx,
сверяет UUID с адресами VPS, версии и действующий профиль. Локальная Panel не
ищется, обход её защиты не создаётся. Install/repair/update/backup/restore/uninstall
заблокированы в этой топологии до двухсерверного стендового acceptance.

## Проверки

### Troubleshooting

| Симптом | Действие |
|---|---|
| Unsupported version / required capability | Сверить фактические версии/бинарник/HTTP2/TLS mounts; не обходить guards |
| Certificate lifecycle preflight | Подготовить directory mounts и испытать renewal на стенде; отдельное согласование recreate |
| Duplicate Hosts / identity changed | Сверить UUID и bindings со state/backup; не удалять чужой Host автоматически |
| Uncertain Host POST / rollback incomplete at host | POST мог завершиться без ответа UUID; сохранить journal и сверить с Panel audit trail; повтор не присваивает похожие Hosts |
| Rollback incomplete at nginx | Проверить файл, место, `nginx -t`, статус контейнера; после согласованного старта повторить restore |
| Rollback finalizing | Освободить место/восстановить права и повторить restore: state/history завершаются до terminal marker |
| HTTP401 / Panel unavailable | Восстановить доступ/token/gateway; не публиковать token; повторить recovery после сверки |
| Foreign/shared profile / manual clients | Остановиться; привести топологию к поддерживаемой в отдельном плане |
| Host есть, подписки/трафика нет | Проверить Squad/Node memberships, disabled, формат клиента, DNS/SNI, firewall TCP/UDP |
| ENOSPC / unfinished transaction | Сохранить private state/journal/backups, восстановить диск/API; сначала restore, затем новый plan |
| Legacy migration journal | Автоматический rollback/uninstall заблокирован; требуется отдельный audited recovery |

Для обновления исходников заранее сохраните state/history и Git SHA; получите
проверенный commit в чистый checkout, изучите diff/lockfile и обновите venv по
hashes. Bootstrap не делает reset существующего checkout. До `--update` выполните
`--check` и `--backup`; один `--update` не скачивает новую версию проекта.
Удаление выполняйте `--uninstall` по своей истории, сохранив backup до и после.
Произвольное восстановление PostgreSQL snapshot выполняется отдельно по upstream
runbook с согласованной точкой восстановления всех связанных компонентов.

```bash
python3 -B -m unittest discover -s tests -v
python3 -B tests/validate_sources.py
for script in *.sh tests/*.sh; do bash -n "$script"; done
shellcheck *.sh tests/*.sh
XRAY_BINARY=/path/to/xray NGINX_BINARY=/path/to/nginx python3 tests/validate_binaries.py
```

GitHub Actions содержит Ubuntu и Debian13 unit checks, Bash/ShellCheck, pinned
Xray checksum и Nginx OCI digest из `validation-manifest.json`; контейнер Nginx
запускается с `--network none` только для `nginx -t`. Debian/Ubuntu CI кандидата
прошёл: по 106 tests без SKIP, Linux Xray/Nginx validators PASS.
Проверенный SHA и результаты: [CODEX_04_RELEASE](docs/CODEX_04_RELEASE.md).

Runtime verification сопоставляет API config, cold config штатного Node CLI,
перезапуск Xray при изменении базовой конфигурации и владельца TCP/UDP listeners.
Это не клиентский acceptance. После отдельного согласования rollout проверьте
защищённую Panel, реальную пользовательскую подписку и каждый разрешённый Host
снаружи; форматы sing-box/Clash не поддерживают все варианты Xray.


Полные эксплуатационные отчёты не входят в публичный пакет.
Ранее README заявлял MIT, но отдельного LICENSE проекта нет;
владелец должен подтвердить лицензию до релиза. См.
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md).
