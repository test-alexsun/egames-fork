# Отчёт о миграции inbound tag — 28 октября 2026

Миграция семи inbound на **sw126** выполнена через API Remnawave. Источник
истины — Config Profile `StealConfig`; временные файлы Node и БД не редактировались.
Debian 13, Panel 3.4.7, Node 3.4.3, серверный Xray 26.7.28.

## Инвентаризация и результат

VPS PASS означает конфигурацию, UUID-привязки и наличие listeners; клиентский
HTTPS-трафик указан отдельно. NOT VERIFIED не означает неисправность.

| Inbound | Старый tag | Новый tag | VPS | Happ | Итог |
| --- | --- | --- | --- | --- | --- |
| VLESS WS | EGADDON-WS | Vless-WS-tcp | PASS | NOT VERIFIED | Миграция PASS; клиентский трафик NOT VERIFIED |
| VLESS XHTTP TLS | EGADDON-XHTTP | Vless-XHTTP-tcp | PASS | NOT VERIFIED | Миграция и внешний HTTPS PASS |
| Trojan gRPC | EGADDON-GRPC | Trojan-gRPC-tcp | PASS | NOT VERIFIED | Миграция PASS; клиентский трафик NOT VERIFIED |
| VLESS XHTTP REALITY | EGADDON-XREALITY | Vless-XHTTP-tcp-2 | PASS | NOT VERIFIED | Миграция и внешний HTTPS PASS |
| VLESS RAW REALITY ML-KEM | EGADDON-PQ | Vless-Reality-tcp | PASS | NOT VERIFIED | Миграция и внешний HTTPS PASS |
| Shadowsocks 2022 TCP/UDP | EGADDON-SS2022 | Shadowsocks-TCP+UDP-tcp+udp | PASS | NOT VERIFIED | Миграция PASS; клиентский TCP/UDP NOT VERIFIED |
| Hysteria2 QUIC | EGADDON-HY2 | Hysteria2-QUIC-udp | PASS | NOT VERIFIED | Миграция PASS; клиентский UDP NOT VERIFIED |
| Базовый VLESS REALITY Vision | Steal | Steal, сохранён | PASS | NOT VERIFIED | Внешний HTTPS PASS |

Локальные порты семи добавлений сохранены: соответственно TCP 44739, 28355,
35143, 40190, 52218, TCP/UDP 45708, UDP 443. Первые три опубликованы через
существующий Nginx TCP 443. SNI, path, flow, ключи, UUID пользователей,
сертификаты, пароли и API-токены не менялись. Полное сравнение JSON профиля
подтвердило единственные изменения: объявления tag и ссылки inboundTag.

SSH-аудит обоих указанных серверов выявил отдельную Node-only установку de126.
Её профиль `de126-NodeOnly` и базовый `DE126-REALITY` оставлены без изменений.
Также сохранены семь его tag `EGADDON-AD05996E-{WS,XHTTP,GRPC,XREALITY,PQ,SS2022,HY2}`.
Сверка API подтвердила неизменность полного JSON этого профиля. Таким образом,
на другом сервере старые tag остаются намеренно: миграция затрагивает только
полную установку sw126, а не все профили общей Panel.

## Зависимости и механизм

Panel при переименовании удаляет inbound UUID и создаёт новые. Снимок всех
Hosts, Nodes и Internal Squads сохранён до PATCH; после PATCH UUID определены
по новым tag и восстановлены прежние связи. Количество объектов сохранено:
2 профиля, 2 подключённые Node, 16 Hosts, 1 Squad, 1 существующий пользователь.
Host remarks, отключения Hosts и ограничения сквада сохранены; выключенные
протоколы не включались ради теста. Подписка пользователя по-прежнему выдаёт
8 профилей: 4 FI и 4 DE.

Маршрутизация сохраняется структурной миграцией только `inboundTag`.
`outboundTag`, outbound selector балансировщика и остальные поля не меняются.
Шаблоны подписок и активный Node plugin проверены перед записью: ссылок на
старые tag не обнаружено; после миграции их JSON идентичен исходному. Nginx и
Compose также идентичны снимку. Служебные tags, paths, host_ids, inbounds и
tag_labels обновлены; повторный запуск использует тот же tag каждого inbound.

## Изменённые файлы

- `inbound_tags.py`: имена из реальной конфигурации, глобальная уникальность,
  структурное обновление ссылок и проверка dangling inboundTag.
- `tag_migration.py`: приватный журнал, API-миграция, восстановление UUID-связей,
  защита от drift/параллельных правок, read-back, автоматический и ручной откат.
- `egames_safe.py`: новые установки, автоматическая миграция legacy state,
  стабильные label→tag и сохранение Host remarks при одинаковом транспорте.
- `remnawave_injector.py`: проверка PQ определяется также по явному label,
  поэтому её нельзя обойти новым названием tag.
- `tests/test_tag_migration.py`, `tests/test_safe.py`: генерация, коллизии,
  UUID cascade, routing, потерянные HTTP-ответы, health failures, drift,
  сохранение выключенных Hosts и повторная установка.
- `.github/workflows/check.yml`: компиляция новых модулей в CI.
- `bootstrap.sh`: исправлены два замечания ShellCheck в ранее существовавшем
  bootstrap (trap и неоднозначная конструкция проверки Docker).
- `README.md`, `docs/INBOUND_TAG_MIGRATION.md`, этот отчёт.

Исторические документы `docs/LIVE_SW126.md` сохранены как снимок прежнего
развёртывания; старые строки в них и тестах совместимости не являются рабочими
ссылками конфигурации. Старый `inbound_tag_plan.py` остаётся автономным
планировщиком имён Hosts и не применяется для новой миграции.

## Резервные копии и откат

На sw126, с правами root-only:

- `/root/remnawave-audit/private/snapshot-tag-before.json` — API и конфигурации.
- `/root/remnawave-audit/private/tag-migration-20261028/files-before.tar.gz` —
  checkout, состояние установщика, Nginx и Compose.
- `/root/remnawave-audit/private/tag-migration-20261028/database-before.sql` —
  успешный pg_dump, 333935 байт на момент создания.
- `/var/lib/egames-injector/backups/tags-*.json`, `tag-migration.json` —
  снимок миграции и write-ahead журнал, статус committed.

Секретные снимки не включены в Git. Ручной API-откат:
`cd /opt/egames-fork && .venv/bin/python tag_migration.py --restore`.
Он восстанавливает конфиг и связи по заново выданным UUID, а не предполагает
сохранение удалённых UUID. Порядок и ограничения описаны в документации.
Исторические установочные транзакции содержат устаревшие UUID: они архивированы,
автоматический uninstall после миграции блокируется. Полный возврат старой
установки требует проверенного восстановления БД/файлов. На production откат
не запускался, поскольку миграция прошла; отказные сценарии проверены mock-тестами.

## Тесты

| Проверка | Статус | Доказательство / ограничение |
| --- | --- | --- |
| Генерация по реальному протоколу/транспорту | PASS | Автоматические тесты и реальные JSON |
| Уникальность, глобальные коллизии и суффиксы | PASS | Автоматические тесты; все 7 tag уникальны |
| Миграция с каскадным удалением UUID | PASS | Mock с cascade и production API read-back |
| Ошибка API / потеря ответа / health failure / параллельные правки | PASS | Автоматические отказные тесты |
| Routing и сохранение outboundTag | PASS | Структурное сравнение; автоматические тесты dangling/duplicate |
| Повторная установка на тестовом стенде | PASS | Идемпотентные mock-тесты установщика |
| Повторная установка sw126 | PASS | journal committed, 0 операций |
| Windows unit tests | PASS | 67 запусков, 66 PASS, 1 Linux-only SKIP |
| Debian unit tests | PASS | Все 67 PASS |
| Компиляция Python и проверка diff | PASS | compileall, git diff --check |
| Реальный Xray 26.7.28 / Nginx | PASS | validate_xray и nginx -t на sw126 |
| Hosts / Nodes / Squads / отключения | PASS | tag_verify.py, точная сверка memberships |
| Секреты и сетевые настройки | PASS | Профиль идентичен исходному после обратного отображения tag |
| Подписка существующего пользователя | PASS | HTTP JSON; 8 профилей, прежние разрешения |
| Внешний HTTPS: базовый Vision и 3 включённых VLESS | PASS | Windows Xray 26.10.21; HTTP 200, выход через IP VPS |
| Трафик WS / Trojan gRPC / SS2022 / Hysteria2 | NOT VERIFIED | Отключены либо исключены из пользовательской подписки |
| Реальный клиент Happ | NOT VERIFIED | Happ 4.2.1 обнаружен; Computer Use app approval timed out |
| Перезапуск Node / Xray | PASS | docker restart remnanode; последующий API/read-back/listeners PASS |
| Перезапуск Docker | NOT VERIFIED | Автоматическая проверка разрешений отклонила общий restart; запрос пользователю отправлен |
| Перезагрузка VPS | NOT VERIFIED | Отдельное подтверждение общего перерыва обслуживания ожидается |
| GitHub Actions после публикации | FAIL, исправление отправлено | 67 unit-тестов PASS; исходный запуск остановился на двух замечаниях ShellCheck в bootstrap; итоговый статус см. PR |

Результаты внешнего клиента сохранены локально в
`audit/client-results-tag-migration-20261028-external.json`; серверные статусы —
`/root/remnawave-audit/private/tag-verified-summary.json`. Серверный аудит:
`audit/tag_preflight.py`, `audit/tag_verify.py`. Эти служебные файлы расположены
рядом с checkout и не нужны установщику.

## Найденные ошибки и повторная проверка

1. В sandbox отсутствовал доступ к Windows SSH-конфигурации; SSH-аудит выполнен
   через разрешённый запуск с настроенными ключами. Другие серверы не менялись.
2. Первая команда pg_dump получила роль root из-за кавычек удалённого shell;
   повтор через subprocess argv успешно использовал POSTGRES_USER/POSTGRES_DB.
3. Сразу после restart Node ещё не успела подключиться к Panel. После ожидания
   все проверки прошли. Во время рестарта зафиксированы Failed to stop Xray и
   временные ECONNREFUSED stats API; последующая синхронизация и HTTPS PASS.
4. Первый Windows-клиентский запуск прервался на emoji в cp1251, следующие
   попытки — на получении bundle через SSH. Исправлена кодировка вывода,
   проведена отдельная SSH-диагностика, итоговый запуск всех 4 профилей PASS.
5. Общий restart Docker отклонён автоматической проверкой разрешений из-за
   прерывания всего стека. Ограничение не обходилось; запрос подтверждения
   пользователю отправлен. Docker/reboot не выдаются за успешные проверки.

## GitHub

Изменения подготовлены как отдельный коммит
`fix: rename EGADDON inbound tags to descriptive protocol names` поверх
существующей ветки `fix/preserve-operator-settings`, для публикации в отдельной
ветке `fix/descriptive-inbound-tags`, включая три уже существующих коммита
(сохранение operator settings, выбор Node в CLI, ранняя обработка --help).
Публикация в `main` отклонена автоматической проверкой разрешений как изменение
основной ветки с более широким влиянием; отдельный запрос пользователю отправлен.
До подтверждения default main сохраняет прежний установщик. Для установки новой
версии используйте опубликованную ветку либо её SHA. История не переписывается,
force-push не используется. Состояние публикации и SHA коммита приводятся в
итоговом сообщении; этот отчёт не заявляет успешный push до ответа GitHub.

Публикация feature-ветки подтверждена GitHub: кодовый коммит
`d8ea489ccfa6dfb7bb1b9b19fd9a940040e4d8f1`,
[draft PR #3](https://github.com/test-alexsun/egames-fork/pull/3).
VPS checkout переключён на опубликованную feature-ветку; `egames-fork check`
повторно прошёл. Предварительно развёрнутые изменения сохранены в Git stash
`tag-migration-deployed-source`, без reset и удаления коммитов. `main` не изменён.

Миграция на sw126 и подтверждённые проверки завершены. Полная проверка Happ,
четырёх отключённых клиентских протоколов, Docker restart и reboot остаётся
NOT VERIFIED; считать всю исходную задачу полностью проверенной нельзя.
