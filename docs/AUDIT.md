# Аудит и изменения, 27 октября 2026

Позднее в тот же день выполнено развёртывание и практические проверки на Debian 13:
[LIVE_SW126.md](LIVE_SW126.md). Ниже сохранён первоначальный аудит исходного кода;
его утверждения об отсутствии VPS-тестов относятся к первоначальному этапу.

Исходное рабочее дерево было пустым. Основной репозиторий найден по исправленной
ссылке `test-alexsun/egames-fork` и клонирован без пользовательских изменений.
Исходный commit: `e60c325a3c0f4c9b183bef7fec03898b854d70da`.
Строки в таблице относятся к этому commit, а не к изменённым файлам.

## Найденные ошибки

| Приоритет | Файл:строка | Причина и последствия | Исправление |
|---|---|---|---|
| CRITICAL | `install.sh:187`, `:191` | `${TOKEN:+...}${TOKEN:-...}` выводит также сам непустой токен; cookie печатается открыто | Удалена печать credentials, HTTP-ответы с ключами исключены из ошибок |
| CRITICAL | `remnawave_injector.py:574` и переключение ноды около `:630` | Новый профиль создавался с пустой оболочкой; текущий listener 443, routing/DNS/policy не переносились; панель и подписки теряли вход | Дополняется существующий активный профиль; исходный 443 сохраняется структурно |
| HIGH | `remnawave_injector.py:303` | TLS-inbound без certificates создаётся и активируется; «исправить потом» может положить ноду | TLS завершает существующий Nginx; для HY2 сначала проверяются сертификаты внутри Node |
| HIGH | `remnawave_injector.py:221`, `config.example.yaml` | PQ-тег получал `decryption: none`, ML-KEM вообще не генерировался | Настоящая пара из установленного `xray vlessenc`, 64-байтный ML-KEM seed; без генератора — пропуск с причиной |
| HIGH | `remnawave_injector.py:142` | При сбое keygen возвращались `REPLACE_PRIVATE_KEY`/`REPLACE_PUBLIC_KEY` | Отказ вместо фиктивных ключей; существующие REALITY-ключи сохраняются |
| HIGH | `remnawave_injector.py:416` | После отказа API создавался минимальный профиль, ошибки отдельных inbound скрывались | Удалены incremental fallback и произвольный PUT fallback; транзакция с журналом и откатом |
| HIGH | `remnawave_injector.py:535` | Ошибка привязки Node превращалась в warning, завершение с успехом | Ошибка останавливает применение, изменения откатываются с проверкой |
| HIGH | `remnawave_injector.py:626`, `fix-add-steal-443.py:112` | Выбор первой ноды; recovery переключал все ноды, включая удалённые | Явная однозначность, проверка локального адреса, отказ для общего профиля |
| HIGH | `install.sh:233`, `:308` | `git reset --hard` и перегенерация config могли уничтожить локальные правки | Установщик запускает проверенный checkout, не скачивает и не сбрасывает файлы |
| HIGH | `fix-tls-certs.py:39`, `:33` | `shell=True` с доменами и путями; mount добавлялся по случайному текстовому anchor | Subprocess только массивами argv; mounts определяются через Docker inspect; Compose не переписывается |
| HIGH | `fix-strip-hysteria.sh:31`, другие recovery | Остановка production Node до проверки API; подавление HTTP-ошибок, удаление inbound без транзакции | Legacy entrypoints направлены в общий CLI; по умолчанию только диагностика |
| MEDIUM | `fix-hosts.py:7`, `fix-host-names.py` | Изменение чужих Hosts по remark/совпадению имени | Управление только собственными Host UUID из состояния и тегом владельца |
| MEDIUM | `fix-add-steal-443.py:66`, `fix-hosts.py:66` | Dry-run создавал backup-файлы; часть backup могла быть доступна по умолчанию | Диагностика не пишет состояние/backup; секретные snapshots создаются сразу с 0600 в каталоге 0700 |
| MEDIUM | `fix-firewall.py:66` | Ошибки UFW игнорировались, отчёт выдавал успех | Проверка кода выхода и наличия правила; добавляются только отсутствующие public rules с меткой владельца |
| MEDIUM | `ensure_host` в исходном injector | Host мог считаться существующим по remark; path/security/SNI не соответствовали внешнему TLS | Host связан с конкретным inbound UUID; WS/XHTTP/gRPC публикуются через TLS:443, gRPC Host.path содержит serviceName |
| MEDIUM | исходные проверки портов и версий | Фиксированные порты без проверки TCP/UDP и без фактического Xray test | `ss` отдельно TCP/UDP, запрет дублей; проверка конфигурации реальным core до API-записи |

## Подтверждённая архитектура

eGames `93e6631aae5f7bff28eadfc45faab43150cc22c6`:

- `src/api/remnawave_api.sh:429`: Config Profile создаётся через Panel API.
- `:450–466`: VLESS REALITY TCP:443, `dest=/dev/shm/nginx.sock`, `xver=1`.
- `src/nginx/install_panel_node.sh:268`, `:333`: Nginx и Node используют host network.
- `:310–341`: общий `/dev/shm`; Nginx сам создаёт свой socket при старте.
- `:445`, `:516`, `:548`: TLS + PROXY protocol через Unix socket; отдельные server blocks панели, подписки и selfsteal.
- Привязки Node activeInbounds и Internal Squads нужны независимо от Hosts.

3x-ui `7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661` использует другую архитектуру:
Nginx Stream на TCP:443, SQLite и собственные модели клиентов/Hosts. Эти изменения
не перенесены в Remnawave. Его PQ-скрипт также печатает часть decryption и использует
Vision с XHTTP без проверки: такой код не является подтверждением совместимости.

Официальные исходники для адаптера:

- Remnawave backend `52321390ac4efe04a610811446d87335f1d10a93`, package 3.4.7:
  `src/common/helpers/xray-config/xray-config.validator.ts`, `ss-cipher.ts`,
  `src/common/utils/flow/get-vless-flow.ts`, Host contracts,
  `resolve-proxy-config.service.ts`, Xray JSON и Mihomo generators.
- Node `2ad154f8f1016c94c1872f337268af878af61b18`, package 3.4.3:
  handler передаёт пользователям UUID/пароли/flow, присланные Panel.
- Xray 26.10.21 `1b1647c`: реальные серверные проверки, `infra/conf/hysteria.go`,
  `vless.go`, `transport_internet.go`, генератор `main/commands/all/vlessenc.go`.

Старое утверждение «Hysteria2 не поддерживается Xray» неверно для проверенной версии.
Правильная схема — protocol `hysteria`, settings.version=2 и
streamSettings.hysteriaSettings.version=2. VMess отсутствует в управляемых
пользователях и генераторах подписок backend; AES-128 SS2022 также не входит в
поддерживаемый серверный адаптер. Выбран AES-256 с 32-байтным ключом.

## Выполненные проверки

Локально Windows, без доступа к production:

- 37 unittest: 36 passed, 1 skipped (POSIX file permissions).
- Bash syntax всех shell entrypoints и ShellCheck 0.11.0: passed.
- Python compile и JSON fixtures: passed.
- Официальный Xray 26.10.21 Windows amd64: 8 server configs и один PQ client config passed.
  SHA256 архива совпал с опубликованным `.dgst`:
  `fc58c39ee2f2717b4c54d28d374362389e5319b20ae44aea76ea45a5243ec827`.
- Официальный Nginx 1.30.0 Windows: TLS + WS/XHTTP/gRPC routes passed.
  Для этой проверки Unix listener заменён локальным TCP:18443; это не Linux UDS test.
- Linux CI добавлен, но в этой сессии не запускался: там проверяются POSIX права
  и конфигурация с Unix listener настоящим `nginx:1.30` в одноразовом контейнере.

Fixtures проверяют идемпотентность inbound/Hosts/routes, сохранение DNS/routing/policy,
backup/restore/uninstall, неясный результат HTTP-записи, ошибку Node API, конфликт TCP/UDP,
несовместимые версии, missing mount/certificate и отказ от перезаписи внешних правок.

## Изменённые и добавленные файлы

Основная реализация: `remnawave_injector.py`, новый `egames_safe.py`, `install.sh`,
`config.example.yaml`, `requirements.txt`. Документация: `README.md`, `docs/AUDIT.md`.
Безопасные compatibility entrypoints: `post-install.sh`, `fix-add-steal-443.py`,
`fix-tls-certs.py`, `fix-hosts.py`, `fix-host-names.py`, `fix-firewall.py`,
`fix-panel-hard.sh`, `fix-node-hysteria.sh`, `fix-strip-hysteria.sh`.
Тесты: `tests/test_safe.py`, `tests/validate_binaries.py`, `tests/nginx-docker.sh`,
`tests/fixtures/egames.json`, `tests/fixtures/nginx.conf`.
CI/служебное: `.github/workflows/check.yml`, `.gitattributes`, `.gitignore`.

## Оставшиеся ограничения

Это проверенная на уровне кода и валидаторов реализация, а не подтверждение
полного развёртывания. На Debian 12/13 и Ubuntu 24.04 установка, рестарт VPS,
реальные экспорты подписки и подключения клиентом здесь не выполнялись.
Релизная готовность по всем критериям исходного задания пока не подтверждена.

Адаптер ограничен Panel 3.4.7, Node 3.4.3 и исходной single-VPS Nginx selfsteal
схемой. Caddy, node plugins, общие профили, port ranges, runtime snippets и
неоднозначная топология отклоняются. Ранее созданные legacy inbound не присваиваются
новому установщику автоматически. Восстановление уже сломанной старой установки
требует отдельного плана по её фактическому состоянию.

Новые HTTP-транспорты используют loopback TCP. Общий Unix socket eGames сохраняется;
новые UDS с небезопасным 0666 не создаются. Адаптер владения/пересоздания дополнительных
сокетов после reboot не реализован. HY2 включается только с уже доступными Node TLS
mounts; установщик не пересоздаёт контейнеры ради добавления mounts.

Автоматический firewall adapter — только активный UFW. Для nftables/firewalld и
файрвола хостера выводится ограничение; автоматического открытия там нет.
Ручные backups предназначены для диагностики/ручного восстановления; `--restore`
автоматически откатывает последний journal, а не произвольный JSON snapshot.

Rollback отказывается перезаписывать внешние изменения и сообщает INCOMPLETE.
Read-back подтверждает восстановленные API-объекты/файлы, но не клиентскую связность.
Panel не предоставляет CAS для всех этих API: полностью исключить одновременную
администраторскую правку между последним GET и PATCH невозможно.
