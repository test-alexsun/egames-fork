# CODEX 02 — реализация, публичная редакция

Реализованы pre-write drift guards, сохранение Node/Squad/Host access decisions,
partial-write recovery, stable installation identity, private state/secret inputs,
schema2 journals, capability checks, pinned wheels/validators и Node-only inventory.

UUID-changing tag migration и legacy snapshot rollback отключены: поддерживаемый
Panel API заменяет inbound UUID при rename. Node-only mutation заблокирован.
Это безопасное ограничение, не подтверждение полной реализации этих сценариев.

Независимый review обнаружил R01–R05, поэтому прежние положительные выводы не
являются production approval. Итоговые исправления/проверки/ограничения:
CODEX_04_RELEASE. Настоящая Panel/PostgreSQL integration, Linux crash boundaries,
renewal/HY2 lifecycle, Happ/subscriptions и provider firewall остаются gates.
