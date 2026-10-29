# Технические tags: политика сохранения UUID

В адаптере Panel 3.4.7 автоматическое переименование отключено. `syncInbounds`
удаляет старую запись и создаёт новую при смене tag; Host FK получает SetNull,
Node/Squad связи удаляются. Сохранить прежний inbound UUID через поддерживаемый
API нельзя. Восстановление memberships не сохраняет сам объект и не соответствует
требованию UUID preservation.

Новые inbound используют формат `Vless-XHTTP -tcp`; коллизии получают `-2`, `-3`.
Пробел проверен Xray validator, API schema принимает string. Формат вычисляется
из протокола/транспорта и effective flow Panel; RAW REALITY с явным пустым flow
не называется Vision. Существующие descriptive и `EGADDON-*` tags остаются прежними.
Управление видимыми названиями выполняется через Host.remark.

Read-only предложение доступно в проверенном checkout с приватным owner-state:

```bash
sudo .venv/bin/python tag_migration.py --plan --state-dir /var/lib/egames-injector
```

JSON выводит `canApply: false`. `tag_migration.py --restore` и программный
`migrate/rollback` завершаются до API writes. Снимки старой миграции и журналы
с удалёнными UUID сохраняются для независимого восстановления. Не меняйте schema,
не копируйте старый state поверх текущего и не используйте старый исполнитель:
он может затереть поздние правки DNS, inbound и ограничения доступа.

`inbound_tag_plan.py` — исторический offline-планировщик по Host.remark. Он не
применяет изменения и не определяет формат новых technical tags.

Для новых обычных транзакций поддерживаются schema 2 `install.sh --restore` и
`--uninstall` с identity/epoch/drift checks. Это не средство отката старой tag
migration. Подробности: [CODEX_02_IMPLEMENTATION](CODEX_02_IMPLEMENTATION.md).
