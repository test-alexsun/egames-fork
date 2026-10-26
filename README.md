# eGames / Remnawave — Config Profile & Hosts Injector

Автосоздание **Inbounds** и **Hosts** в Remnawave после установки eGames.  
Все данные (токен, домены панели / подписки / ноды, cookie) **берутся из eGames** — вручную ничего вводить не нужно.

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
4. Сразу запускает injector → создаёт inbounds + hosts  

Без автозапуска injector:

```bash
RUN_AFTER_INSTALL=0 bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/install.sh)
```

### Команды после установки

```bash
egames-injector --dry-run
egames-injector
nano /opt/egames-injector/config.yaml
```

---

## Откуда берутся данные (как в eGames)

| Параметр | Источник |
|----------|----------|
| `panel_api_token` | `/usr/local/remnawave_reverse/token` (тот же, что у eGames) |
| `panel_api_url` | `http://127.0.0.1:3000/api` (локально на панели) |
| `host_address` | адрес ноды из API `/nodes` (домен, введённый при установке eGames) |
| `egames_cookie` | cookie gate из `nginx.conf` / Caddyfile |
| `reality_server_name` | = host_address / selfsteal |
| PANEL / SUB домены | `/opt/remnawave/.env` → `PANEL_DOMAIN`, `SUB_PUBLIC_DOMAIN` |

Три домена, которые спрашивает eGames при установке (панель, подписка, нода/selfsteal), подставляются автоматически.

---

## Что создаётся

- Config Profile `eGames-MultiProtocol` с 9 inbounds  
- Hosts с remark вида `EE-ee | ⚡ VLESS REALITY + Vision`  
- Привязка inbounds к ноде и Internal Squad  

Повторный запуск безопасен (идемпотентно).

---

## Файлы

| Файл | Назначение |
|------|------------|
| `install.sh` | Установщик с автодетект eGames |
| `remnawave_injector.py` | Создание profile / hosts / squad |
| `config.example.yaml` | Шаблон (обычно не трогать) |

---

MIT
