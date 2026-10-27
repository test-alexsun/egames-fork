# Практическая проверка sw126, 27 октября 2026

Debian 13.7, eGames 3.8.4 (`93e6631aae5f7bff28eadfc45faab43150cc22c6`),
Panel 3.4.7, Node 3.4.3, штатный Xray 26.7.28, Nginx 1.30.6,
Docker 29.9.2 и Compose 5.6.1. Внешний клиент: официальный Xray 26.10.21 Windows.
Исходный egames-fork: `1bca4778f31fda0d057835a84ddc53f56ee7f73f`.
Изменения сохранены в ветке `audit/sw126-live-20261027`; push/PR не выполнялись.

## Подтверждённые результаты

- Установка официальным eGames выполнена с Nginx и secret cookie.
- Все три домена получили действительные сертификаты Let's Encrypt.
- Исходный Steal/REALITY/Vision проверен внешним клиентом до применения дополнения.
- `--dry-run`, `--check`, `--backup`, `--install` выполнены на VPS.
- Исходный активный StealConfig дополнен: inbound 1 → 8, Hosts 1 → 8.
- Сохранились UUID исходного inbound, Node и профиля, исходный Host, DNS, routing,
  outbounds и все посторонние блоки Nginx. TCP 443 остался у Xray.
- Тестовый пользователь получил восемь профилей через публичную подписку `/json`.
- Все восемь профилей проверены реальным внешним HTTPS-трафиком с выходным IP VPS.
- После рестарта Node, Nginx и Subscription Page повторены клиентские проверки;
  конфигурация, плагин и подписка сохранились. База/Panel и Docker daemon не перезапускались.
- Повторный `--install`: 0 API-мутаций, 0 записей конфигурации Nginx, 0 reload.
- Cookie-защита проверена на `/`, `/api`, `/api/`, `/admin`, `/login`, случайном URL;
  без cookie — сайт-прикрытие/404, с cookie API дополнительно требует Bearer.
- Проверены Secure/HttpOnly/SameSite=Strict, отсутствие query-секрета в access log,
  отказ неизвестному SNI/Host и прямому обращению по IP.
- Внешний доступ к 2222, 3000, 3001, 3010, 6767 и трём loopback inbound отсутствует.

| Профиль | Публичный порт | Реальный клиент |
|---|---|---|
| Steal: VLESS REALITY + Vision | TCP 443 | HTTPS PASS |
| EGADDON-WS: VLESS WS TLS | TCP 443 | HTTPS PASS |
| EGADDON-XHTTP: VLESS XHTTP TLS | TCP 443 | HTTPS PASS |
| EGADDON-GRPC: Trojan gRPC TLS | TCP 443 | HTTPS PASS |
| EGADDON-XREALITY: XHTTP REALITY | TCP 40190 | HTTPS PASS |
| EGADDON-PQ: RAW REALITY + ML-KEM-768 | TCP 52218 | HTTPS PASS |
| EGADDON-SS2022: AES-256-GCM | TCP/UDP 45708 | HTTPS и UDP DNS PASS |
| EGADDON-HY2: native Hysteria2 | UDP 443 | HTTPS PASS |

Проверки не были безошибочными: первые попытки PQ/SS2022 до рестарта и gRPC/XHTTP
REALITY после рестарта давали тайм-ауты; повторные подключения прошли без изменений
конфигурации. Для XHTTP REALITY журнал клиента подтвердил TCP connect timeout.
Отказы сохранены в отчёте вместе с успешными повторами.

## Torrent Blocker и Ingress Filter

Использован официальный eGames `Reverse Node Plugins`, привязан к единственной Node.
Torrent Blocker настроен на 3600 секунд; Ingress Filter использует classic preset,
271 исходную IPv4/CIDR-запись. Перед применением проверено отсутствие IP SSH/VPS
в списке; native nftables sets/chains и счётчики подтверждены на сервере.

Практический тест Torrent Blocker использовал отдельный network namespace и IP
172.29.250.2: обычный HTTPS проходил, синтетический BitTorrent-handshake вызывал
бан официальным плагином, разрыв соединения и отчёт в панели. Проверка повторена
после рестарта, число отчётов выросло 0 → 1 → 2. Namespace удалён, только тестовый
IP разблокирован штатным executor API. Существующие правила/настройки не сбрасывались.
Для повторного контрольного HTTPS выбран собственный VPS: первый запрос к внешнему
сайту завершился тайм-аутом ещё до отправки BitTorrent и не был засчитан как PASS.

## Исправления этой ветки

1. Native plugin preservation adapter: чтение конфигурации по UUID, NET_ADMIN,
   отказ неизвестным hooks/sections/shared lists, проверка binding/config drift
   перед записью и после синхронизации. Сам pluginConfig не изменяется.
2. Nginx `-c /dev/stdin` на реальном контейнере возвращал `no "events" section`.
   Проверка переведена на приватный seekable temporary file внутри обнаруженного
   контейнера. Файл удаляется в `finally`, рабочий bind mount не трогается.
3. CLI сообщает подтверждённое желаемое состояние, не заявляя reload при пустом diff.

Добавлены регрессионные тесты: сохранение/дрейф/отказ плагинов, обычная и неуспешная
staged-проверка Nginx с обязательной очисткой. Debian: 45 PASS; Windows: 44 PASS,
1 SKIP (POSIX permissions). CI workflow в этой сессии не запускался.

## Серверные изменения вне дополнения

- Для native HY2 Node получил read-only mounts только своего ACME live/archive
  lineage; корректность Compose и доступность cert/key проверены до активации.
- В generated Nginx config добавлен access-log format без args/Referer, чтобы
  секретная ссылка входа не сохранялась в журнале. Все оригинальные server blocks
  и Unix TLS + PROXY protocol сохранены.
- Публичным файлам сайта-прикрытия возвращены 0644, каталогам 0755: приватный umask
  записи установщика первоначально создал index.html с 0600 и вызвал 403.
- Из-за вложенного `rawInbound` первый диагностический вывод содержал session
  REALITY privateKey. Маскирование исправлено, журнал очищен; по отдельному согласию
  владельца заменён только созданный в этой сессии неиспользуемый ключ при нуле
  пользователей, с закрытой резервной копией и сохранением UUID/прочих полей.

## Названия Hosts

После установки все восемь отображаемых имён приведены к формату
`🇫🇮 | протокол | транспорт и защита`. GeoIP-сервисы ipwho.is и ipinfo.io
определили IPv4 VPS как Финляндию (FI, Хельсинки). Например:
`🇫🇮 | VLESS | WS TLS`, `🇫🇮 | Trojan | gRPC TLS`, `🇫🇮 | Hysteria2 | QUIC TLS`.
API read-back подтвердил изменение только `remark`: UUID, привязки, остальные
поля Hosts и полный Config Profile сохранены. Закрытые снимки до/после находятся
в `/root/remnawave-audit/private/`, журнал — `logs/11-host-country-names.log`.
Тот же формат теперь используется установщиком и описан в README.

## Ограничения

Сеть VPS нестабильна: наблюдались SSH/TCP/ACME/HTTP-01 timeout. Первичный выпуск
сертификатов потребовал временного loopback SOCKS-туннеля через существующий SSH.
Проверка прямого `certbot renew --dry-run` прошла для панели, но не прошла для
Node (доступ к ACME staging) и подписки (secondary HTTP-01 validation timeout).
Действующие production-сертификаты не изменялись; надёжность автопродления требует
устранения сетевой проблемы и повторной проверки.
Повтор двух неуспешных dry-run через временный SSH-прокси также завершился
HTTP-01 timeout, включая secondary validation подписки. Поэтому доступ к API CA
через прокси не устраняет проблему входящей проверки; успешное автопродление
Node/подписки не заявляется.

VMess и SS2022 AES-128 не создавались: соответствующих адаптеров управляемых
пользователей/подписки в проверенном backend нет. Общие профили, Caddy, shared lists
и произвольные lifecycle hooks остаются вне адаптера. Полный reboot VPS и испытание
Linux-клиентов иных приложений не выполнялись.

Полный отчёт и журналы: `/root/remnawave-audit/INSTALLATION_REPORT.md`,
`/root/remnawave-audit/logs/`. Пароли, private keys, API tokens и ссылки авторизации
в эту документацию не включены.
