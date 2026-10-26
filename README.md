# eGames / Remnawave — установка панели и ноды + мультипротокольный профиль

Набор скриптов поверх [eGames remnawave-reverse-proxy](https://github.com/eGamesAPI/remnawave-reverse-proxy):
после установки панели и ноды создаёт в Remnawave профиль с **9 inbound'ами**, хосты с единообразными
именами, подключает сертификаты для TLS-протоколов и открывает порты.

Всё делается через API панели, без ручной правки в интерфейсе.

> **Безопасность.** Не публикуйте и не присылайте нигде пароль root, API-токен панели и токены GitHub.
> Если они попали в переписку или лог — смените пароль и отзовите токены.

---

## 0. Что получится

| Inbound (tag) | Порт | Имя хоста в клиенте (пример) |
|---|---|---|
| Steal-443 | 443 | `🇫🇮① \| VLESS · TCP · Reality · 443` |
| VLESS-REALITY-VISION | 8443 | `… VLESS · Vision · Reality · 8443` |
| VLESS-XHTTP-REALITY | 34544 | `… VLESS · XHTTP · Reality · 34544` |
| VLESS-XHTTP-PQ | 34514 | `… VLESS · XHTTP · Reality PQ · 34514` |
| VLESS-XHTTP-TLS | 10443 | `… VLESS · XHTTP · TLS · 10443` |
| VLESS-WS-TLS | 44205 | `… VLESS · WS · TLS · 44205` |
| VLESS-HTTPUPGRADE-TLS | 55574 | `… VLESS · HTTPUpgrade · TLS · 55574` |
| TROJAN-GRPC-TLS | 10399 | `… Trojan · gRPC · TLS · 10399` |
| SS-2022 | 15714 (TCP+UDP) | `… Shadowsocks · TCP/UDP · 2022 · 15714` |

Формат имени хоста: `<флаг страны VPS><символ ноды> | протокол · транспорт · защита · порт`.
Hysteria2 в профиль **не входит** (на ноде вызывал падение Xray: `version != 2`).

Самые устойчивые к блокировкам — Reality на 443 и 8443; TLS на нестандартных портах и
Shadowsocks без обфускации блокируют чаще. Это общая оценка, а не замер вашей сети.

---

## 1. Требования

- VPS с Ubuntu 22.04/24.04 или Debian 12, доступ **root**, 1 vCPU / 1–2 ГБ RAM и выше.
- **Три домена** (или поддомена), A-записи на IP сервера:
  1. домен панели (например `panel.example.com`);
  2. домен страницы подписок (`sub.example.com`);
  3. домен ноды / selfsteal (`node.example.com`).
- Открытые на стороне хостера порты: 22, 80, 443, 8443 и порты inbound'ов из таблицы выше
  (если у провайдера свой файрвол — открывать нужно и там).
- Установщик eGames сам выпускает сертификаты Let's Encrypt; DNS должен уже указывать на сервер.

---

## 2. Порядок установки на новый сервер (панель + нода на одном VPS)

### Шаг 1. Подготовка сервера

```bash
ssh root@<IP>
apt update && apt -y upgrade
apt -y install curl git ufw
# рекомендуется сразу перейти на SSH-ключи и сменить пароль:
passwd
```

Проверьте, что DNS уже отдаёт IP сервера:

```bash
getent hosts panel.example.com sub.example.com node.example.com
```

### Шаг 2. Установка панели и ноды (upstream eGames)

```bash
bash <(curl -Ls https://raw.githubusercontent.com/eGamesAPI/remnawave-reverse-proxy/refs/heads/main/install_remnawave.sh)
```

В меню выберите **«Установить компоненты Remnawave» → «Установить панель и ноду на один сервер»**
(названия пунктов зависят от версии upstream; сверяйтесь с его README) и введите три домена.
Скрипт поставит Docker, Nginx + Xray (reverse proxy через unix-сокет `/dev/shm/nginx.sock`),
выпустит сертификаты, создаст панель, ноду и профиль `StealConfig`, **покажет данные входа** —
сохраните их. Panel открывается по ссылке с cookie-ключом, которую выводит установщик.

Что должно появиться на сервере: `/opt/remnawave/` (compose, nginx.conf, .env),
`/usr/local/remnawave_reverse/token` (API-токен), контейнеры `remnawave`, `remnawave-db`,
`remnawave-redis`, `remnawave-nginx`, `remnawave-subscription-page`, `remnanode`.

### Шаг 3. Injector: профиль, inbound'ы и хосты

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/install.sh)
```

Скрипт ставит Python-зависимости в `/opt/egames-injector`, читает token, домены и адрес ноды
из eGames, пишет `config.yaml` и запускает injector: создаёт профиль `eGames-MultiProtocol`,
inbound'ы, хосты, привязывает их к ноде и Internal Squad. Повторный запуск безопасен.

Без автозапуска injector: `RUN_AFTER_INSTALL=0 bash <(curl -fsSL …/install.sh)`;
проверка без изменений: `egames-injector --dry-run`.

> После этого шага **нода переключена на профиль `eGames-MultiProtocol`**. В нём пока нет
> порта 443 (он остался в `StealConfig`), у TLS-inbound'ов нет сертификатов, порты закрыты
> файрволом. Это исправляет шаг 4.

### Шаг 4. Постустановка (одной командой)

```bash
git clone https://github.com/test-alexsun/egames-fork.git ~/egames-fork
cd ~/egames-fork
bash post-install.sh            # спросит подтверждение; --yes — без вопросов
```

Скрипт выполняет по порядку (каждый шаг идемпотентен, на первой ошибке остановка):

| # | Скрипт | Что делает |
|---|---|---|
| 1 | `fix-add-steal-443.py` | Копирует inbound `Steal` (443) в профиль eGames под тегом `Steal-443` (теги уникальны во всех профилях), включает его на ноде и в squad'ах |
| 2 | `fix-tls-certs.py` | Монтирует `/etc/letsencrypt` (read-only) в `remnanode`, **проверяет**, что файлы видны внутри контейнера, и только затем прописывает `certificates` в TLS-inbound'ы |
| 3 | `fix-hosts.py` | Привязывает хост 443 к `Steal-443`, отключает устаревшие хосты (старый `XHTTP`, `Hysteria2`) |
| 4 | `fix-host-names.py` | Единые имена хостов; флаг определяется по публичному IP VPS |
| 5 | `fix-firewall.py` | Открывает в `ufw` порты всех inbound'ов (для SS ещё и UDP). Если ufw не активен — ничего не меняет |

Флаг и символ ноды можно задать вручную: `FLAG=🇩🇪 NODE_MARK=② bash post-install.sh --yes`.
Автоопределение по IP может ошибаться (базы показывают страну регистрации диапазона) —
сверьтесь со страной площадки в карточке VPS.

Каждый скрипт можно запускать отдельно: без `--apply` он работает в режиме **dry-run**
(печатает план и делает бэкап).

Порядок важен: сертификаты нельзя прописывать в профиль, пока они не смонтированы в
`remnanode` — иначе Xray не стартует и **вся нода** перестаёт работать.

### Шаг 5. Проверка

```bash
ss -tlnp | grep rw-core | awk '{print $4}'      # слушаются 443, 8443, 34544, 34514, 10443, 44205, 55574, 10399, 15714
docker logs --tail 20 remnanode 2>&1 | grep -aiE 'xray|error'   # "XRay Core ... is up and running"
curl -sI https://panel.example.com | head -1                     # HTTP/2 200 (с cookie-ключом из установщика)

# TLS-протоколы отдают ваш сертификат (подставьте домен сертификата):
for p in 44205 10443 10399 55574; do
  echo | timeout 8 openssl s_client -connect 127.0.0.1:$p -servername sub.example.com 2>/dev/null \
   | grep -aE 'subject=|Verification' | tr '\n' ' '; echo
done
```

Подписка должна отдавать 9 ссылок (7 `vless`, 1 `trojan`, 1 `ss`); в панели нода в статусе **Connected**.
Страница подписок отвечает `502`/обрыв на корневой `/` и без `shortUuid` — это нормально,
проверять нужно реальную ссылку подписки пользователя.

С **другого устройства** (не с VPS!) проверьте доступность портов:
`nc -zv <IP> 443; nc -zv <IP> 34544; nc -zv <IP> 15714`. Проверка с самого сервера по его
публичному IP ничего не доказывает.

### Шаг 6. Клиент

Создайте пользователя в панели (он попадёт в `Default-Squad`), откройте его ссылку подписки в
клиенте (Happ, v2rayN, Hiddify и т.п.), обновите подписку, проверьте несколько протоколов.

---

## 3. Нода на отдельном сервере

1. На сервере панели: пункт установки «только панель» (или «панель и страница подписок»).
2. На втором сервере: установщик eGames → «Установить только ноду», вставьте сертификат/ключ,
   который запрашивает установщик; в панели нода появится после успешного подключения.
3. Для второй ноды используйте другой символ: `NODE_MARK=② python3 fix-host-names.py --apply`.

Ограничение: `fix-tls-certs.py` и `fix-firewall.py` рассчитаны на панель и ноду **на одном
сервере** (монтируют каталог `/etc/letsencrypt` локального `remnanode`). Для удалённой ноды
сертификат нужно выпустить/скопировать на неё и смонтировать в её `remnanode` самостоятельно,
после чего прописать `certificates` в профиле; порты откройте в ufw ноды вручную.
Этот сценарий в репозитории не проверялся.

---

## 4. Ручная установка injector (без install.sh)

```bash
git clone https://github.com/test-alexsun/egames-fork.git && cd egames-fork
pip install -r requirements.txt
cp config.example.yaml config.yaml     # поправить panel_api_token, host_address
python3 remnawave_injector.py -c config.yaml            # --dry-run для проверки
```

`tls_cert_file` / `tls_key_file` в `config.yaml` при первой установке **оставляйте пустыми**
(см. шаг 4); пути — это пути внутри контейнера `remnanode`.

Откуда `install.sh` берёт данные: token — `/usr/local/remnawave_reverse/token`; домены —
`/opt/remnawave/.env` (`PANEL_DOMAIN`, `SUB_PUBLIC_DOMAIN`); cookie — `nginx.conf`;
адрес ноды — `GET /api/nodes` или selfsteal-домен.

---

## 5. Скрипты репозитория

| Файл | Назначение |
|---|---|
| `install.sh` | Установщик injector с автодетектом eGames |
| `remnawave_injector.py` | Создание профиля, inbound'ов, хостов, привязка к ноде и squad |
| `config.example.yaml` | Шаблон конфигурации (9 inbound'ов, без Hysteria2) |
| `post-install.sh` | Оркестратор шагов 1–5 из раздела 2 |
| `fix-add-steal-443.py` | Перенос `Steal` (443) в профиль eGames |
| `fix-tls-certs.py` | Сертификаты для TLS-inbound'ов (монтирование + `certificates`) |
| `fix-hosts.py` | Перепривязка хоста 443, отключение устаревших хостов |
| `fix-host-names.py` | Единые имена хостов, флаг по IP |
| `fix-firewall.py` | Порты inbound'ов в ufw |
| `fix-panel-hard.sh` | Восстановление при недоступном API / упавшей ноде |
| `fix-node-hysteria.sh`, `fix-strip-hysteria.sh` | Удаление `HYSTERIA2` из профиля (crash loop Xray) |

Все `fix-*.py` по умолчанию в **dry-run**, перед изменениями пишут бэкап в
`/root/remnawave-backup/` (профили, хосты, `docker-compose.yml`).

---

## 6. Диагностика

| Симптом | Причина | Решение |
|---|---|---|
| Скрипт видит API как `000`, в логе панели `ProxyCheckMiddleware: Reverse proxy and HTTPS are required` | запрос на `127.0.0.1:3000` без заголовков reverse proxy | передавайте `X-Forwarded-For: 127.0.0.1` и `X-Forwarded-Proto: https` (во всех скриптах репозитория уже так) |
| `ECONNREFUSED …:2222`, нода Disconnected | `remnanode` остановлен (скрипт упал до запуска) | `docker start remnanode` или `bash fix-panel-hard.sh` |
| Xray падает: `version != 2` / `HYSTERIA2` | inbound hysteria в профиле | `bash fix-node-hysteria.sh` |
| Панель и подписка недоступны по HTTPS, порта 443 нет в `ss` | нода переключена на профиль без `Steal` на 443 | `python3 fix-add-steal-443.py --apply` |
| `HTTP 409 … A113 Inbound tags must be unique` | теги inbound'ов уникальны во всех профилях | скрипт уже копирует `Steal` как `Steal-443` |
| Работает только 443/8443, остальные порты недоступны | `ufw` (политика DROP) или файрвол хостера | `python3 fix-firewall.py --apply` + открыть порты у хостера |
| WS / XHTTP+TLS / gRPC / HTTPUpgrade не подключаются, `certs=[]` | у TLS-inbound'ов нет сертификата | `python3 fix-tls-certs.py --apply` |
| Клиент отклоняет сертификат | SNI хоста ≠ домену сертификата | в Hosts у TLS-хостов SNI = домен сертификата |
| `502` при открытии `https://<sub-домен>/` | страница подписок не отдаёт корень без `shortUuid` | это норма, проверяйте `https://<sub-домен>/<shortUuid>` |
| В подписке лишние/мёртвые серверы | хосты привязаны к неактивному inbound'у | `python3 fix-hosts.py --apply` |

Откат: профиль и хосты восстанавливаются из JSON в `/root/remnawave-backup/`
(через интерфейс/API), `docker-compose.yml` — из `docker-compose.yml.<время>`.
Профиль `StealConfig` не удаляется и остаётся резервным: в панели Nodes → нода → выбрать
профиль `StealConfig` вернёт исходное состояние.

После продления сертификата Let's Encrypt Xray может не подхватить новые файлы без перезапуска:
добавьте `docker restart remnanode` в deploy-hook certbot (`/etc/letsencrypt/renewal-hooks/deploy/`).

---

## 7. Ограничения панели (учтены в скриптах)

- Протоколы: `vless`, `trojan`, `shadowsocks`; `vmess` и метод SS `2022-blake3-aes-128-gcm` панель не принимает.
- Сети: `raw`, `tcp`, `ws`, `xhttp`, `grpc`, `httpupgrade`.
- `PATCH /api/nodes`, `/api/config-profiles`, `/api/hosts`, `/api/internal-squads` — `uuid` в теле запроса.
- У ноды один активный профиль: порты в разных профилях не объединить, поэтому `Steal` переносится в профиль eGames.

---

## Лицензия

MIT
