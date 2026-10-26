# eGames / Remnawave — Config Profile & Hosts Injector

Полностью автоматический скрипт в стиле eGames: **всё из `config.yaml`, без вопросов**.

Создаёт/дополняет:

- **Config Profile** (inbounds Xray) через API  
- **Hosts** с привязкой к inbound  
- **Node** (`activeConfigProfileUuid` + `activeInbounds`)  
- **Internal Squad** (список inbounds)

Идемпотентно: повторный запуск не ломает Reality-ключи и не плодит дубликаты.

## Установка

```bash
git clone https://github.com/test-alexsun/egames-fork.git
cd egames-fork
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

В `config.yaml` заполните **только**:

```yaml
panel_api_token: "rwa_ВАШ_ТОКЕН"
host_address: "node.example.com"
```

Остальное уже прописано (9 протоколов, порты, squad, profile name).

## Запуск

На сервере панели (рекомендуется):

```bash
python3 remnawave_injector.py -c config.yaml
```

Проверка без записи:

```bash
python3 remnawave_injector.py -c config.yaml --dry-run
```

Секреты через env (опционально):

```bash
export PANEL_API_TOKEN="rwa_..."
export HOST_ADDRESS="node.example.com"
python3 remnawave_injector.py -c config.yaml
```

## API-форматы (как eGames)

- `POST/PATCH /api/config-profiles` — полный Xray JSON  
- `POST /api/hosts` — `{ inbound: { configProfileUuid, configProfileInboundUuid }, remark, address, port, ... }`  
- `PATCH /api/internal-squads` — `{ uuid, inbounds: [...] }`  
- `PATCH /api/nodes/{uuid}` — `{ configProfile: { activeConfigProfileUuid, activeInbounds } }`  
- `GET /api/system/tools/x25519/generate` — Reality-ключи  

## Целевые inbounds (из config)

| Tag | Port | Тип |
|-----|------|-----|
| VLESS-REALITY-VISION | 8443 | VLESS TCP REALITY Vision |
| VLESS-WS-TLS | 44205 | VLESS WS TLS |
| VLESS-XHTTP-TLS | 10443 | VLESS XHTTP TLS |
| VLESS-XHTTP-REALITY | 34544 | VLESS XHTTP REALITY |
| VLESS-XHTTP-PQ | 34514 | VLESS XHTTP REALITY PQ |
| TROJAN-GRPC-TLS | 10399 | Trojan gRPC TLS |
| VMESS-WS-TLS | 55574 | VMess WS TLS |
| SS-2022 | 15714 | Shadowsocks 2022 |
| HYSTERIA2 | 36712 | Hysteria2 |

Список и порты меняются только в `config.yaml` → `target_inbounds`.
