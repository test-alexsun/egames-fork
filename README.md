# eGames / Remnawave — Config Profile & Hosts Injector

Автоматическое создание **Inbounds** и **Hosts** в панели Remnawave (установка eGames).  
Всё из `config.yaml`, без интерактивных вопросов. API-форматы — как в официальном eGames `remnawave_api.sh`.

---

## Установка на другой сервер (одна команда)

На **любом** Linux-сервере (панель или отдельный management-хост):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/install.sh)
```

Скрипт:

1. Поставит python3 / pip / git  
2. Скачает injector в `/opt/egames-injector`  
3. Создаст venv и зависимости  
4. Положит `config.yaml` из примера  
5. Добавит команду `egames-injector`  

### После установки

```bash
nano /opt/egames-injector/config.yaml
```

Заполните **два обязательных поля**:

```yaml
panel_api_token: "rwa_ВАШ_ТОКЕН"      # Panel → Settings → API Tokens
host_address: "node.example.com"      # домен или IP ноды
```

Если скрипт стоит **не на сервере панели** (удалённый доступ):

```yaml
panel_api_url: "https://panel.example.com/api"
egames_cookie: "name=value"           # cookie gate из nginx eGames
```

Проверка и запуск:

```bash
egames-injector --dry-run   # только лог
egames-injector             # создать inbounds + hosts
```

### Опционально: systemd timer (раз в сутки)

```bash
cp /opt/egames-injector/egames-injector.service /etc/systemd/system/
cp /opt/egames-injector/egames-injector.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now egames-injector.timer
```

---

## Ручная установка

```bash
git clone https://github.com/test-alexsun/egames-fork.git
cd egames-fork
pip install -r requirements.txt
cp config.example.yaml config.yaml
# отредактировать config.yaml
python3 remnawave_injector.py -c config.yaml
```

---

## Что делает injector

| Шаг | Действие |
|-----|----------|
| 1 | Pre-flight API |
| 2 | Найти/создать Config Profile |
| 3 | Добавить недостающие inbounds (9 протоколов) |
| 4 | Сохранить профиль через API |
| 5 | Создать Hosts (формат eGames) |
| 6 | Привязать inbounds к Node + Internal Squad |
| 7 | Verify |

Повторный запуск безопасен: существующие Reality-ключи и hosts не сбрасываются.

---

## Целевые inbounds (по умолчанию в config)

| Tag | Port | Тип |
|-----|------|-----|
| VLESS-REALITY-VISION | 8443 | VLESS TCP REALITY Vision |
| VLESS-WS-TLS | 44205 | VLESS WS TLS |
| VLESS-XHTTP-TLS | 10443 | VLESS XHTTP TLS |
| VLESS-XHTTP-REALITY | 34544 | VLESS XHTTP REALITY |
| VLESS-XHTTP-PQ | 34514 | VLESS XHTTP REALITY |
| TROJAN-GRPC-TLS | 10399 | Trojan gRPC TLS |
| VMESS-WS-TLS | 55574 | VMess WS TLS |
| SS-2022 | 15714 | Shadowsocks 2022 |
| HYSTERIA2 | 36712 | Hysteria2 |

Список меняется только в `config.yaml` → `target_inbounds`.

---

## Файлы

| Файл | Назначение |
|------|------------|
| `install.sh` | Установщик на сервер |
| `remnawave_injector.py` | Основной скрипт |
| `config.example.yaml` | Пример конфига |
| `requirements.txt` | Python-зависимости |

---

## Лицензия

MIT
