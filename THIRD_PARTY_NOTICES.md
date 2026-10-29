# Лицензии и внешние компоненты

Отдельного LICENSE для egames-fork в исходном дереве нет. Ранее README заявлял
MIT; правообладателю необходимо подтвердить это и утвердить LICENSE перед релизом.
Эта доработка не назначает новую лицензию чужому коду.

Внешние компоненты не включаются в Git. Их собственные LICENSE/NOTICE сохраняются
в дистрибутивах; загрузка и эксплуатация проверяются отдельно:

- eGames: MIT, Copyright (c) 2025 eGames, изученный LICENSE в upstream
  `93e6631aae5f7bff28eadfc45faab43150cc22c6`.
- Xray: собственный LICENSE upstream XTLS/Xray-core; binary validator скачивается
  отдельно, версия и checksum заданы validation-manifest.json.
- Nginx, Docker, Remnawave Panel/Node: лицензии соответствующих upstream images
  и включённых зависимостей, не лицензия этого addon.
- Python runtime packages: версии/hashes в requirements.lock; lockfile не заменяет
  лицензионные уведомления исходных пакетов.

Проверка наличия лицензий выполнена; полная юридическая квалификация зависимостей
не заявляется. Утверждение LICENSE проекта остаётся release blocker.
