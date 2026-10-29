# Draft PR: fix recovery completion, Nginx reload retry and Host ownership

Target: `main`. Head: `fix/release-04-public`. Draft: **yes**.
Статус: **NOT READY; не сливать и не выпускать release**.
Публикуется обезличенный пакет без эксплуатационных сведений и private commit history.

## Проблема и изменение поведения

Независимый review воспроизвёл пять ошибок: restore/uninstall падал на строковом
Nginx after, rollback завершал журнал до state, повтор пропускал неуспешный reload,
удалял replacement Host с новым UUID и присваивал ownership duplicate Host.

Typed summary скрывает конфиги; rollback_finalizing сохраняет metadata перед
terminal status; retry повторяет reload; Host UUID из POST фиксируется durable,
полный read-back snapshot проверяется перед DELETE. Cardinality всего binding
проверяется до writes; state получает только подтверждённые собственные UUID.
Lost POST response без UUID блокирует автоматическую компенсацию вместо удаления
похожего Host. Bootstrap дополнительно отклоняет неиспытанный Python.

## Проверки

- 105 tests: 103 PASS, 2 POSIX-only SKIP на Windows.
- Новые regressions R01–R05; public install/repeat/repair/update/backup/restore/
  uninstall/reinstall с synthetic API; UFW/Nginx/API typed recovery.
- Bootstrap shell orchestration: dry-run, success, post-check failure→restore.
- Bash syntax, ShellCheck, AST/JSON/YAML, git diff --check PASS.
- Xray26.10.21: восемь configs + combined + PQ client PASS.
- Nginx1.30.0 Windows TLS/WS/XHTTP/gRPC PASS; Unix socket не испытан этим тестом.
- Девять Linux wheels проверены offline с hashes; pip check PASS.
- Heuristic secret scan reachable blobs/current files: совпадений нет.
- Новая ветка не применялась к production; эксплуатационная инвентаризация не публикуется.
- GitHub CI должен пройти на PR; результат до запуска не заявляется.

## Совместимость и риски

Граница адаптера: Debian13/CPython3.13, Panel3.4.7, Node3.4.3, single-host Nginx
Unix TLS+PROXY, dedicated profile. Node-only только read-only. UUID-changing
tag migration и legacy rollback запрещены; старые tags/ключи/доступы сохраняются.

Не закрыты disposable Debian13+настоящая Panel/PostgreSQL integration,
crash/ENOSPC/reboot всех boundaries, certificate renewal/HY2 reload, Happ и
subscription acceptance. Panel API не имеет CAS: нужно окно без редакторов.
File certificate mounts требуют отдельного remediation. LICENSE проекта отсутствует;
прежнее MIT заявление должен подтвердить владелец. Production deployment требует
отдельного разрешения, merge/release не выполняются автоматически.

Подробности: `docs/CODEX_04_RELEASE.md`, `docs/PRODUCTION_DEPLOYMENT.md`, README.
