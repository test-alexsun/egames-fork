# eGames / Remnawave — Config Profile & Hosts Injector

Автоматическое создание **Inbounds** и **Hosts** в панели Remnawave после установки [eGames](https://github.com/eGamesAPI/remnawave-reverse-proxy).

Всё из `config.yaml`, без интерактивных вопросов. API-форматы — как в официальном eGames `remnawave_api.sh`.

Проверено на живой панели: 9 inbounds + hosts + привязка к Node и Internal Squad.

---

## Установка (на сервере с eGames-панелью)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/install.sh)
```

Скрипт:

1. Ставит Python / зависимости в `/opt/egames-injector`
2. Читает из eGames:
   - **token** → `/usr/local/remnawave_reverse/token`
   - **PANEL_DOMAIN**, **SUB_PUBLIC_DOMAIN** → `/opt/remnawave/.env`
   - **cookie** → `/opt/remnawave/nginx.conf` (map auth_cookie)
   - **host_address (нода)** → `GET /api/nodes` или selfsteal-домен
3. Пишет готовый `config.yaml`
4. Запускает injector → создаёт inbounds + hosts

Без автозапуска injector:

```bash
RUN_AFTER_INSTALL=0 bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/install.sh)
```

### Команды после установки

```bash
egames-injector --dry-run   # только лог, без изменений
egames-injector             # применить
nano /opt/egames-injector/config.yaml
```

---

## Откуда берутся данные (как в eGames)

| Параметр | Источник |
|----------|----------|
| `panel_api_token` | `/usr/local/remnawave_reverse/token` |
| `panel_api_url` | `http://127.0.0.1:3000/api` (локально на панели) |
| `host_address` | адрес ноды из API `/nodes` |
| `egames_cookie` | cookie gate из `nginx.conf` / Caddyfile |
| `reality_server_name` | = host_address / selfsteal |
| PANEL / SUB домены | `/opt/remnawave/.env` → `PANEL_DOMAIN`, `SUB_PUBLIC_DOMAIN` |

Три домена, которые спрашивает eGames при установке (панель, подписка, нода/selfsteal), подставляются автоматически.

---

## Что создаётся

| Шаг | Действие |
|-----|----------|
| 1 | Pre-flight API |
| 2 | Найти/создать Config Profile `eGames-MultiProtocol` |
| 3 | Добавить недостающие inbounds (идемпотентно) |
| 4 | Сохранить профиль через API |
| 5 | Создать Hosts (формат eGames) |
| 6 | Привязать inbounds к Node (`PATCH /nodes`) и Internal Squad |
| 7 | Verify |

Повторный запуск безопасен: существующие Reality-ключи и hosts не сбрасываются.

### Целевые inbounds (по умолчанию)

| Tag | Port | Протокол |
|-----|------|----------|
| VLESS-REALITY-VISION | 8443 | VLESS TCP/RAW REALITY Vision |
| VLESS-WS-TLS | 44205 | VLESS WebSocket TLS |
| VLESS-XHTTP-TLS | 10443 | VLESS XHTTP TLS |
| VLESS-XHTTP-REALITY | 34544 | VLESS XHTTP REALITY |
| VLESS-XHTTP-PQ | 34514 | VLESS XHTTP REALITY |
| TROJAN-GRPC-TLS | 10399 | Trojan gRPC TLS |
| VLESS-HTTPUPGRADE-TLS | 55574 | VLESS HTTPUpgrade TLS |
| SS-2022 | 15714 | Shadowsocks 2022 (`2022-blake3-aes-256-gcm`) |
| HYSTERIA2 | 36712 | Hysteria (`protocol: hysteria`) |

Список меняется только в `config.yaml` → `target_inbounds`.

> **Важно:** панель Remnawave **не принимает** `vmess` и метод SS `2022-blake3-aes-128-gcm`.  
> Используются только разрешённые протоколы/методы.

---

## Ручная установка

```bash
git clone https://github.com/test-alexsun/egames-fork.git
cd egames-fork
pip install -r requirements.txt
cp config.example.yaml config.yaml
# при необходимости поправить token / host_address
python3 remnawave_injector.py -c config.yaml
```

---

## Обновление на сервере

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/install.sh)
# или только скрипт:
curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/remnawave_injector.py \
  -o /opt/egames-injector/remnawave_injector.py
egames-injector
```

`config.yaml` при обновлении **не затирается**.

---

## Опционально: systemd timer (раз в сутки)

```bash
cp /opt/egames-injector/egames-injector.service /etc/systemd/system/
cp /opt/egames-injector/egames-injector.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now egames-injector.timer
```

---

## Файлы

| Файл | Назначение |
|------|------------|
| `install.sh` | Установщик с автодетект eGames |
| `remnawave_injector.py` | Создание profile / hosts / squad / node |
| `config.example.yaml` | Шаблон (9 inbounds) |
| `requirements.txt` | `requests`, `PyYAML` |

---

## Ограничения панели (учтены в скрипте)

- Протоколы: `vless`, `trojan`, `shadowsocks`, `hysteria`, …
- Сети: `raw`, `tcp`, `ws`, `xhttp`, `grpc`, `httpupgrade`, `hysteria`, …
- SS methods: `aes-128-gcm`, `aes-256-gcm`, `chacha20-ietf-poly1305`, `2022-blake3-aes-256-gcm`
- Node update: `PATCH /api/nodes` с `uuid` **в теле** запроса
- Profile update: `PATCH /api/config-profiles` с `uuid` в теле
- При полном отказе создания профиля — fallback: минимальный inbound, затем по одному

---

## Лицензия

MIT

---

## Восстановление ноды (crash loop из‑за Hysteria)

Если Xray на ноде падает с `version != 2` / `HYSTERIA2`:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/fix-node-hysteria.sh)
```

Скрипт: останавливает `remnanode` → ждёт API → удаляет inbound `HYSTERIA2` из профиля → запускает ноду.
