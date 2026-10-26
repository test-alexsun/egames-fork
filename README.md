# eGames / Remnawave — Config Profile & Hosts Injector

Отказоустойчивый скрипт-расширение для панели **Remnawave**, развёрнутой через установщик **eGames** (v3.8.x+).

Скрипт **идемпотентно**:

1. Читает текущий Config Profile (Xray JSON) через REST API.
2. Добавляет недостающие inbounds (9 протоколов) **без перезаписи** существующих Reality-ключей и клиентов.
3. Создаёт / обновляет соответствующие **Hosts**.
4. Привязывает профиль и inbounds к **Node** и **Internal Squad**.

Все операции выполняются **только через API** (`http://127.0.0.1:3000/api` или внешний URL + cookie).

---

## Требования

- Python 3.10+
- Панель Remnawave с API Token (Settings → API Tokens)
- На сервере панели (рекомендуется) или с доступом к API

```bash
pip install -r requirements.txt
```

---

## Быстрый старт

```bash
cp config.example.yaml config.yaml
# Отредактируйте:
#   panel_api_token
#   host_address
#   node_uuid (опционально)
#   egames_cookie (если API снаружи через reverse-proxy)

python3 remnawave_injector.py -c config.yaml
```

Dry-run (только лог, без изменений):

```bash
python3 remnawave_injector.py -c config.yaml --dry-run
```

Секреты можно передать через окружение:

```bash
export PANEL_API_TOKEN="rwa_..."
export PANEL_API_URL="http://127.0.0.1:3000/api"
export EGAMES_COOKIE="name=value"
export HOST_ADDRESS="node.example.com"
python3 remnawave_injector.py -c config.yaml
```

---

## Целевые inbounds (по умолчанию)

| # | Tag                      | Порт  | Протокол / транспорт          |
|---|--------------------------|-------|-------------------------------|
| 1 | VLESS-REALITY-VISION     | 8443  | VLESS + TCP + REALITY + Vision |
| 2 | VLESS-WS-TLS             | 44205 | VLESS + WebSocket + TLS       |
| 3 | VLESS-XHTTP-TLS          | 0*    | VLESS + XHTTP + TLS (nginx)   |
| 4 | VLESS-XHTTP-REALITY      | 34544 | VLESS + XHTTP + REALITY       |
| 5 | VLESS-XHTTP-PQ           | 34514 | VLESS + XHTTP + REALITY (PQ)  |
| 6 | TROJAN-GRPC-TLS          | 10399 | Trojan + gRPC + TLS           |
| 7 | VMESS-WS-TLS             | 55574 | VMess + WebSocket + TLS       |
| 8 | SS-2022                  | 15714 | Shadowsocks 2022              |
| 9 | HYSTERIA2-UDP443         | 443   | Hysteria2 (UDP)               |

\* порт `0` — inbound за reverse-proxy / unix-socket (типично для eGames).

Список полностью настраивается в `config.yaml` → `target_inbounds`.

---

## Безопасность

- **Не** перезаписывает `privateKey` / `shortIds` у уже существующих REALITY-inbounds.
- **Не** трогает файлы БД и конфиги Xray напрямую — только REST API.
- Токен и cookie лучше хранить в env / secrets, а не в git.

---

## Pipeline

1. Pre-flight (`/system/health` или `/nodes`)
2. Fetch profile (`GET /api/config-profiles`)
3. Schema merge (по `tag`)
4. Push profile (`PATCH/POST /api/config-profiles`)
5. Sync Hosts (`GET/POST/PATCH /api/hosts`)
6. Attach Node & Internal Squad
7. Verification

---

## Совместимость

Разрабатывалось с учётом:

- Remnawave Panel 2.x / 3.x (Config Profiles + Internal Squads)
- eGames reverse-proxy installer 3.8.x+
- Локальный доступ `http://127.0.0.1:3000` и внешний через `EGAMES_COOKIE` + Bearer

Если конкретный endpoint отличается в вашей версии панели — смотрите логи `DEBUG` и при необходимости скорректируйте пути в `RemnawaveClient`.

---

## Лицензия

MIT
