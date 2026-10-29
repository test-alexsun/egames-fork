# CODEX 01 — технические выводы, публичная редакция

Это обезличенное изложение, не исходный полный эксплуатационный отчёт.
CRITICAL/HIGH findings: небезопасный snapshot rollback миграции; перезапись
операторских access decisions; повторное включение выключенных inbound;
частичная Nginx запись при crash; recovery с остановленными/recreated контейнерами;
несогласованные journal/state/history; неквалифицированный Node-only mutation;
недостаточная runtime verification; certificate file bind lifecycle.

MEDIUM/LOW: pinning source/dependencies, effective flow/technical tags,
required capabilities, private secret inputs, UFW source/family restrictions,
symlink include semantics и актуальность документации.

Критерии исправления: доказуемое ownership, отказ при drift, сохранение исходного
TCP443/ключей/UUID и операторских исключений, write-ahead recovery, regression
tests и настоящая disposable Debian/Panel/client qualification. Статусы A01–A16
в CODEX_04_RELEASE; полный локальный отчёт сохранён владельцем и не публикуется.
