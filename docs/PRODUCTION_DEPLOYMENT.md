# Безопасное внедрение на целевом VPS — только после отдельного разрешения

Статус: **план, не выполненный deployment**. Ветка NOT READY. Сначала закрыть
gates CODEX_04, включая Debian13/настоящую Panel, лицензирование, renewal и клиенты.
Все изменения целевого VPS, включая mounts/recreate/reload, требуют отдельного разрешения.

1. Назначить maintenance window; запретить параллельные правки Panel/API и другие
   installers. Проверить консоль провайдера, SSH, свободное место, время и off-host
   защищённое хранилище. Определить RPO/RTO и ответственного за откат.
2. Сохранить исходную конфигурацию: полный Git SHA/чистоту checkout, private addon
   state/journal/transactions/backups, Compose/env, image IDs/digests, Docker mounts,
   network/firewall и сертификатный lineage с правами. Каталог 0700, файлы 0600;
   не копировать секреты в Git/PR. Составить checksums и проверить читаемость копии.
3. Backup Panel: согласованный upstream/database runbook, `pg_dump` в consistent
   snapshot плюс Compose/env/secrets, версии PostgreSQL/Panel. Испытать restore
   на отдельной БД; JSON addon не заменяет этот backup. Не угадывать имя БД/сервиса.
4. Backup Node: Compose/env, mounts/TLS/plugin config, image digest и runtime
   version; приватно сохранить API Config Profile и cold config штатного CLI.
   Не редактировать generated config/БД напрямую.
5. Backup Nginx: effective `nginx -T` приватно, include tree, symlinks/permissions,
   Compose mounts, certificates live+archive, renewal hooks. Сохранить served serial.
6. Зафиксировать inbound: profile UUID, tag→UUID, config hash, keys hashes без
   вывода ключей, Node activeInbounds, Squad memberships. Зафиксировать Hosts:
   UUID/binding/address/port/path/TLS/nodes/tags/disabled. Отдельно baseline TCP443.
7. Проверить `ss -Hlnpt`, `ss -Hlnpu`, `ufw status`, provider firewall IPv4/IPv6.
   Сопоставить PID Node core и listeners. Не отбирать занятый UDP443 и не открывать
   management/loopback наружу. Зафиксировать disabled Hosts без изменения доступа.
8. До addon отдельно устранить certificate file bind blocker: подготовить directory
   mounts с live/archive на стенде; испытать atomic renewal, новый served serial,
   Nginx reload и HY2 TLS lifecycle. Согласовать и выполнить remediation целевого VPS
   отдельным изменением с backup и откатом Compose; до этого apply запрещён.
9. Проверить совместимость: Debian13, Python3.13, Panel3.4.7, Node3.4.3, реальный
   Xray validator/version, Nginx Unix TLS+PROXY+HTTP2, локальная Panel+Node, отдельный
   профиль, отсутствие manual clients/snippets/неоднозначности. Старые tags сохраняются.
10. Получить reviewed SHA из CODEX_04, проверить источник/bootstrap/lockfile/CI.
    Выполнить `sudo bash install.sh --dry-run`, затем `--check` и `--backup`.
    Сохранить redacted CHANGE PLAN: только новые inbound/Host/routes/rules,
    прежние UUID/keys/доступы совпадают. При blocker остановиться, не обходить guard.
11. **После явного разрешения владельца** применить `sudo bash install.sh --install`
    и подтвердить конкретный план APPLY. Не обновлять одновременно images/core/ОС.
    Контролировать journal; при ошибке сохранить материалы, проверить auto rollback.
12. Проверить `--check`, `--status`, connected Node, `nginx -t`, services/logs,
    cold config, PID/listeners и API bindings; сравнить исходный inbound/Hosts/keys
    и disabled flags. Повторный install сначала проверен на стенде: дубли отсутствуют.
13. Проверить подписку тестового пользователя: HTTP200, разрешённые Hosts/форматы,
    правильные параметры и отсутствие дублей. Не публиковать private URL/credentials.
14. В Happ снаружи проверить каждый разрешённый endpoint: handshake/HTTPS/outbound
    IP/DNS/upload/reconnect, SS TCP+UDP, HY2 UDP, XHTTP длительный upload. Записать
    версии Happ/core и время; сопоставить Node/Nginx logs и outbound traffic.
    Проверить Panel gateway и недоступность запрещённых backend ports.
15. Откат при отказе baseline, потере UUID/доступов, нерабочих подписках/клиентах:
    сохранить private journal/state, прекратить редакторов; выполнить
    `sudo bash install.sh --restore`, сверив rollback plan. Повторять при временном
    API/disk/reload отказе после устранения причины. Uncertain POST/foreign drift
    требуют ручной сверки UUID, не удаления похожего Host. Stopped Nginx оставляет
    runtime pending до согласованного старта и повторного restore.
16. При невозможности компенсации использовать проверенный полный backup по
    upstream runbook; согласованно восстановить Panel DB + Compose + Node + Nginx
    и старые image digests. DB restore затрагивает и другую Node/новые пользовательские
    изменения: отдельно подтвердить RPO и окно. Не выполнять слепой импорт JSON addon.
17. Подтвердить старый TCP443, Hosts/subscriptions/Happ и согласованность metadata,
    сохранить итоговый diff и разрешение на завершение maintenance window.

Открытые согласования: disposable стенд/ресурсы; LICENSE; remediation mounts/renewal;
тестовая подписка/Happ и допустимые endpoint; maintenance/RPO/RTO; финальный SHA;
production apply и возможные reload/recreate/full DB restore. Дополнительный production сервер не используется
как disposable стенд и не меняется этим планом.
