# CODEX 03 — независимый review, публичная редакция

Исходный вердикт: **CHANGES REQUIRED**. Пять синтетически воспроизводимых дефектов:

| ID | Severity | Воспроизведение и последствие |
|---|---|---|
| R01 | HIGH | Публичный restore/uninstall вызывает .get на строковом Nginx after и падает до rollback |
| R02 | HIGH | Сбой записи old_state после terminal rolled_back оставляет stale ownership metadata |
| R03 | HIGH | Старый файл записан, reload отказал; повтор пропускает reload и ложно сообщает успех |
| R04 | HIGH | Созданный Host заменён оператором новым UUID с теми же полями; rollback удаляет replacement |
| R05 | MEDIUM | saved_id скрывает второй Host того же binding, общий OWNER tag присваивает чужой UUID |

Обязательные регрессии: публичные CLI recovery paths, metadata fault boundaries,
независимое loaded Nginx state, fresh POST UUID/replacement/lost response,
duplicate с/без OWNER в разном API order и zero writes до конфликта.

Mock API и локальный syntax PASS не заменяют disposable Debian13 + настоящую
Panel/PostgreSQL/Node, crash/reboot/concurrency, renewal и client acceptance.
Текущие статусы: CODEX_04_RELEASE. Реальные инвентаризации исключены из этой редакции.
