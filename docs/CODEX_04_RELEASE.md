# CODEX 04 — release preparation, публичная редакция

Дата: 29 октября 2026, Asia/Omsk. **Статус: NOT READY.**
Production deployment, merge и release не выполнялись.

## 1. Исходники и границы публикации

- Репозиторий: https://github.com/test-alexsun/egames-fork
- Ветка: `fix/release-04-public`; target: `main`; PR только draft.
- Публичная база: `7268cb6c63aaa6520bd8dd142f7cf87e34e847df`.
- Кандидат для стенда: `7687f051a7cc890f5a8191dad84e583d31c4bdcd`; не production-approved.
- Полные локальные отчёты и private branch history не включены. Сводки CODEX_01/02/03
  здесь обезличены. Реальные домены/IP/выделенные порты/состояния Hosts/Node отсутствуют.
- Имена в tests/fixtures относятся к синтетическим example.com и documentation IP.
- История main до точки ветвления уже публична и не переписывается этим PR.
- PR: [draft #4](https://github.com/test-alexsun/egames-fork/pull/4), без merge/release.

## 2. Исправления независимого review

Все пять дефектов R01–R05 сначала воспроизведены сохранённым независимым
`локальным независимым review probe` на исходной базе. Получены исходные FAIL из CODEX_03:
AttributeError до restore; stale state после rolled_back; disk restored/runtime new;
DELETE replacement UUID; adoption duplicate Host. Production не затрагивался.

| ID | Исправление | Текущий статус и доказательство |
|---|---|---|
| R01 HIGH | Типизированный rollback summary: UUID только API, Nginx path/hashes, UFW rule; конфиг/секреты не печатаются | FIXED CODE/TEST: публичные run install/repeat/repair/update/backup/restore/uninstall, --yes и APPLY; отдельный API+Nginx+UFW rollback; bootstrap post-check вызывает --restore |
| R02 HIGH | Durable rollback_finalizing, old_state и history до terminal rolled_back; recovery использует выбранный journal path и синхронизирует текущий журнал | FIXED CODE/TEST: сбой до/после state/history/terminal writes, два restore и повторный install/uninstall. Настоящие fsync/SIGKILL/ENOSPC всех Linux boundaries остаются gate |
| R03 HIGH | Совпадение файла с before больше не пропускает reload; завершённость операции сохраняется отдельно | FIXED CODE/TEST: независимая модель loaded config, отказ reload, повтор реально загружает before. Stopped Nginx оставляет rollback incomplete/runtime pending. Настоящий Linux Nginx signal lifecycle ещё gate |
| R04 HIGH | UUID из POST сохраняется до read-back, полный created snapshot до завершения; rollback ищет immutable UUID, проверяет snapshot и не усыновляет replacement | FIXED CODE/TEST: replacement/new fields сохраняются, DELETE не отправляется; fresh random UUID при каждом POST. Потерянный ответ POST без доказанного UUID намеренно BLOCKER ручной сверки |
| R05 MEDIUM | Cardinality проверяется по всему binding независимо от saved UUID до apply и перед изменениями; ownership state строится из подтверждённых UUID | FIXED CODE/TEST: копия с/без OWNER, оба порядка API, saved_id есть/нет; zero writes при duplicate; повтор не создаёт дублей и не захватывает общий OWNER |

`tests/test_audit02.py` больше не обещает автоматическую компенсацию любого lost
POST response: для неопределённого UUID проверяет отказ и сохранение объекта.
Это осознанный предел безопасного recovery, а не замаскированный PASS восстановления.

## 3. Статусы исходного аудита

| Замечания | Состояние после повторной проверки |
|---|---|
| A01 CRITICAL | Опасные migrate/rollback отключены; регрессии отказа до API writes проходят. Безопасная UUID-preserving миграция не реализована: Panel3.4.7 делает delete/create |
| A02 HIGH | Pre-write drift guards сохранены; остаточный GET→PATCH race без server CAS требует окна без редакторов; полноценная конкуренция на Panel не испытана |
| A03 HIGH | Node/Squad enrollment только новых inbound; отключения и exclusions сохраняются в regressions |
| A04–A06 HIGH | Partial-file recovery, stopped-container discovery и schema/identity guards сохранены, metadata/reload исправлены R01–R03; полная Linux crash qualification остаётся BLOCKER |
| A07 HIGH | Node-only только read-only; distributed mutation/recovery заблокированы. Не рекламируется как installer Node-only |
| A08 HIGH | API/cold config/PID/listener guards сохранены; реальный клиент/subscription acceptance итоговой ветки — BLOCKER |
| A09 HIGH | File certificate binds блокируются; file binds требуют remediation и renewal/served serial/HY2 испытаний — BLOCKER |
| A10 MEDIUM | Source SHA, совпадение bootstrap, hashed wheel closure и pinned validators сохранены; добавлен отказ unqualified Python; весь apt/OS image не pinned |
| A11–A12 MEDIUM | Effective flow/spaced new tags/required capabilities и HTTP2 проходят tests; старые tags не меняются |
| A13 MEDIUM | Private inputs/atomic metadata guards сохранены; POSIX-specific permission tests локально SKIP, Linux CI обязателен |
| A14–A15 MEDIUM | UFW restrictions и staged symlink includes проходят tests; provider firewall/полная IPv6 matrix не квалифицированы |
| A16 LOW | README обновлён по реальным возможностям, 21 запрошенная тема покрыта; исторические отчёты явно отделены |

## 4. Результаты проверок

Локальная среда: Windows, CPython3.13, Git Bash, сохранённые .tools binaries.
Системные/API boundaries подменены только в явно синтетических tests.

| Проверка | Результат |
|---|---|
| Python unit/synthetic integration | **Linux Debian13: 106 PASS, 0 SKIP (3.653 s); Ubuntu: 106 PASS, 0 SKIP (3.308 s)**. Предыдущий Windows прогон: 105 tests, 103 PASS / 2 POSIX-only SKIP |
| Новые регрессии R01–R05 | PASS, 8 test methods, включая многократные fault subcases и публичный цикл |
| Bash syntax всех root/test shell scripts | PASS, Git Bash `bash -n` |
| ShellCheck всех root/test shell scripts | PASS, `.tools/shellcheck/shellcheck.exe` через Bash glob |
| AST / JSON / YAML / validation manifest | PASS, 20 Python files, fixtures/config/workflow parsed |
| Xray26.10.21 Windows | PASS: 8 server configs, combined eight-inbound со spaced tags, PQ client encryption |
| Nginx1.30.0 Windows | PASS TLS+WS/XHTTP/gRPC; Windows fixture использует TCP вместо Unix socket |
| pip check / runtime imports | PASS; requests2.34.2, PyYAML6.0.3, cryptography46.0.5 |
| Linux CPython3.13 wheel closure | PASS: 9 wheels, offline pip download --no-index --require-hashes --only-binary, manylinux2014/2_34 |
| Bootstrap dry-run | PASS shell orchestration: только --check; не системная установка |
| Bootstrap install | PASS orchestration: check→backup→install→check; fake OS/packages/network/venv boundaries |
| Bootstrap post-check failure | PASS orchestration: --restore --yes вызывается, bootstrap возвращает ошибку; public restore отдельно покрыт R01 |
| dry-run/check/status/backup/install | PASS synthetic public run; реальный CLI на disposable Debian НЕ ВЫПОЛНЕН |
| repeat install / repair / update | PASS synthetic, Hosts неизменны, дублей нет, baseline/disabled/memberships сохраняются |
| restore / rollback / uninstall / reinstall | PASS synthetic public run с real temp metadata, API mock; full DB restore не поддерживается addon |
| Миграция технических tags | PASS безопасного отказа migrate/legacy rollback до writes; реальная миграция BLOCKED, не выдаётся за работающую |
| Git secret heuristic | PASS на reachable blobs и текущих nonignored файлах, high-confidence hits=0; не доказательство отсутствия любого секрета |
| git diff --check | PASS |
| GitHub Actions кандидата / PR | **PASS** для SHA7687f05: [run40895735396](https://github.com/test-alexsun/egames-fork/actions/runs/40895735396), checks + debian-unit success; Linux Xray checksum и Nginx validators PASS |
| Настоящая Debian13 Panel3.4.7/PostgreSQL/Node3.4.3 integration | **BLOCKED:** Docker CLI локально отсутствует, WSL distro недоступен, disposable сервер не предоставлен |
| Полный bootstrap на чистом Debian13 | **NOT TESTED**, сеть/apt/venv на настоящей ОС и installation SHA не испытаны |
| SIGKILL/ENOSPC/reboot каждого Linux boundary, persistent API outage/concurrency | **NOT TESTED** на настоящей инфраструктуре |
| Certificate rotation / новый served serial / HY2 reload | **NOT TESTED**, BLOCKER certificate lifecycle |
| Happ / подписки / реальный внешний трафик новой ветки | **NOT TESTED**, обязательный acceptance gate |

Первые ошибки Windows temp access и glob expansion устранены выбором workspace
TEMP/TMP и Bash glob; финальные результаты приведены выше. Системные тесты не
подменяются mock PASS. Полная эксплуатационная инвентаризация не публикуется.

Первый Ubuntu CI упал: fixture command возвращал `[]` для `ufw status`, если
на runner был установлен UFW. Fixture теперь возвращает explicit inactive state;
добавлена регрессия среды с установленным UFW. Runtime guard не ослаблялся.
Повторный Linux CI прошёл все 106 tests. Node20 deprecation warning pinned Actions
не является причиной падения; обновление Actions требует отдельной проверки.
Последний дополнительный Windows full run: 106 tests, один bootstrap subprocess
TimeoutExpired на лимите 30 s, два POSIX-only SKIP. Для Windows лимит увеличен
до 60 s; Linux limit остаётся 30 s. Это отказ переносимости тестового harness,
не успешный системный bootstrap. Отдельный повтор Windows bootstrap указан ниже.
Повтор после изменения лимита: **3 bootstrap orchestration tests PASS**, 88.244 s.

## 5. Версии и граница совместимости

| Компонент | Подтверждённая граница |
|---|---|
| ОС / Python | Debian13, CPython3.13; CI также Ubuntu24.04 |
| Panel / Node | Адаптер разрешает только 3.4.7 / 3.4.3; настоящая интеграция остаётся gate |
| Xray validator | 26.10.21, официальный Linux archive с закреплённым checksum |
| Nginx validator | Pinned nginx:1.30 OCI digest из validation-manifest.json; network-none nginx -t |
| Docker / Compose | Проверяются capabilities; диапазон production версий не квалифицирован |
| Python dependencies | requirements.lock: 9 hashes-pinned пакетов; Linux wheel closure PASS |

Таблица содержит параметры адаптера/CI, а не инвентаризацию production серверов.

## 6. Поддерживаемые и неподтверждённые сценарии

Код поддерживает single-host Panel+Node+Subscription+Nginx по существующей
eGames Unix TLS/PROXY topology, приватный dedicated Config Profile и known versions.
Это заявленная граница адаптера, не успешная production qualification этой ветки.
Required: WS/XHTTP/gRPC/XHTTP REALITY/SS2022; HY2/PQ optional по capabilities.
Исходный Vision TCP443 переиспользуется. Повтор сохраняет keys/paths/ports/UUID
и операторские access decisions в synthetic tests.

Node-only: только explicit HTTPS remote Panel inventory/check/status/dry-run;
install/repair/update/backup/restore/uninstall заблокированы. Shared profiles,
manual clients, snippets, Caddy/3x-ui и неизвестные версии не квалифицированы.
Неподтверждены все client formats, PQ/HY2 со всеми core/client versions,
external firewall IPv4/IPv6/UDP, renewal lifecycle и runtime plugins traffic effects.

## 7. Изменённые файлы этой работы

- `egames_safe.py`: typed summary, immutable Host identity, rollback metadata/reload,
  cardinality и подтверждённый ownership state.
- `bootstrap.sh`: qualification CPython3.13 до pip/apply.
- `tests/test_release04.py`, `tests/test_bootstrap.py`: новые регрессии и shell integration.
- `tests/test_audit02.py`, `tests/test_safe.py`: honest lost POST semantics и POST response UUID.
- `tests/scan_secrets.py`, `.github/workflows/check.yml`: batch Git/worktree secret heuristic в CI.
- `.gitignore`: env variants, keys/certs/private transaction artifacts.
- `README.md`: подготовка/установка/DNS/Nginx/inbounds/tags/ports/Hosts/acceptance/
  update/uninstall/backup/restore/rollback/troubleshooting и ограничения.
- `THIRD_PARTY_NOTICES.md`: отсутствие LICENSE проекта и внешние компоненты.
- `docs/PRODUCTION_DEPLOYMENT.md`: отдельный безопасный rollout/rollback runbook.
- `docs/CODEX_04_RELEASE.md`: этот отчёт.
- `docs/CODEX_01_AUDIT.md`, `docs/CODEX_02_IMPLEMENTATION.md`, `docs/CODEX_03_REVIEW.md`: обезличенные технические сводки; полные отчёты не экспортированы.

## 8. Установка, проверка, откат

Только на disposable стенде после просмотра опубликованных исходников:

```bash
git clone --no-checkout https://github.com/test-alexsun/egames-fork.git egames-fork-review
git -C egames-fork-review checkout --detach 7687f051a7cc890f5a8191dad84e583d31c4bdcd
git -C egames-fork-review rev-parse HEAD
less egames-fork-review/bootstrap.sh
```

После установленного и проверенного исходного eGames и отдельного просмотра
bootstrap/dependencies установка addon запускается **одной командой**:

```bash
sudo env EGAMES_FORK_REF=7687f051a7cc890f5a8191dad84e583d31c4bdcd bash ./egames-fork-review/bootstrap.sh
```

Сначала добавьте `--dry-run`: готовит checkout/apt/venv, проверяет capabilities,
но не меняет Panel/Nginx/firewall. Bootstrap требует собственного содержимого
из того же SHA и чистого `/opt/egames-fork` с matching origin/SHA; не делает reset.
Git clone/fixed SHA выполняется до запуска скачанного install.sh, pip использует
--require-hashes --only-binary. Установка с --yes допустима только после review
конкретного плана. Никаких `curl | bash` от root не предлагается.

Проверка source checkout:

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes --only-binary=:all: -r requirements.lock
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B tests/validate_sources.py
.venv/bin/python -B tests/scan_secrets.py
for script in *.sh tests/*.sh; do bash -n "$script"; done
shellcheck *.sh tests/*.sh
sudo bash install.sh --check
sudo bash install.sh --status
```

Linux binary job использует pinned Xray/Nginx manifest. Для настоящего стенда
дополнительно пройти полный lifecycle и faults из раздела 4 и client matrix README.
Сохранить baseline UUID/keys hashes, memberships и Host disabled; diff после
повтора должен быть пуст по этим данным.

Откат собственных новых schema2 transactions: сохранить private state/journal/
history/backups, исключить Panel edits, `sudo bash install.sh --restore`, проверить
показанный план, подтвердить APPLY. `--uninstall` идёт по своей истории.
При metadata/reload outage устранить причину и повторить; stopped Nginx требует
согласованного старта/runtime validation. При uncertain POST UUID/replacement/
drift остановиться и сверить ownership вручную. Legacy tag migration recovery
заблокирован. Полный PostgreSQL/Compose/certificates backup восстанавливается
по отдельно проверенному upstream runbook, не импортом JSON addon.

## 9. Release blockers и согласования

1. Disposable Debian13 + настоящая Panel/PostgreSQL/Node: full lifecycle,
   ENOSPC/SIGKILL/reboot, lost replies/persistent outage, cascade UUID semantics,
   Nginx reload и concurrency. Mock PASS это не закрывает.
2. Если используются certificate file mounts: отдельный reviewed remediation и renewal /
   served serial / Node HY2 lifecycle, затем разрешение recreate/reload.
3. Разрешённая тестовая подписка и Happ/client acceptance; не менять existing
   disabled/access ради тестов. External provider firewall также gate.
4. LICENSE: в проекте отсутствует файл при прежнем MIT заявлении; владелец
   должен подтвердить лицензию/правообладателей. Новая лицензия не назначалась.
5. CI кандидата завершён успешно; изменения runtime требуют повторной квалификации.
6. Утвердить maintenance/RPO/RTO/full backup restore и окончательный production SHA;
   **production apply целевого VPS требует отдельного разрешения**. Дополнительный production сервер не изменяется.

Финальный статус: **NOT READY**. Исправления доступны для independent review;
production readiness не заявляется до закрытия перечисленных gates.
