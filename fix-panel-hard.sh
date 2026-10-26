#!/usr/bin/env bash
# Hard recovery: stop node, full stack restart, wait API, strip HYSTERIA2
set -euo pipefail

TOKEN_FILE="${TOKEN_FILE:-/usr/local/remnawave_reverse/token}"
API="${API:-http://127.0.0.1:3000/api}"
PROFILE_NAME="${PROFILE_NAME:-eGames-MultiProtocol}"
TAG_REMOVE="${TAG_REMOVE:-HYSTERIA2}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/remnawave}"

info(){ echo -e "\033[1;32m[+]\033[0m $*"; }
warn(){ echo -e "\033[1;33m[!]\033[0m $*"; }
err(){ echo -e "\033[1;31m[x]\033[0m $*" >&2; }

[[ ${EUID} -eq 0 ]] || { err "root required"; exit 1; }
[[ -s "$TOKEN_FILE" ]] || { err "no token $TOKEN_FILE"; exit 1; }
TOKEN=$(tr -d '\r\n ' < "$TOKEN_FILE")

cd "$COMPOSE_DIR"

info "Stop remnanode"
docker stop remnanode 2>/dev/null || true

info "Restart full stack (db/redis/panel)"
docker compose stop remnawave 2>/dev/null || true
docker compose up -d remnawave-db remnawave-redis
sleep 5
docker compose up -d remnawave
sleep 3
docker compose up -d remnawave-nginx remnawave-subscription-page 2>/dev/null || true

info "Wait API (up to ~2 min)"
ok=0
for i in $(seq 1 60); do
  code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 2 --max-time 5 \
    -H "Authorization: Bearer ${TOKEN}" "${API}/nodes" 2>/dev/null || echo 000)
  if [[ "$code" == "200" ]]; then
    info "API OK (http $code) after ${i} attempts"
    ok=1
    break
  fi
  # every 10 attempts show status
  if (( i % 10 == 0 )); then
    warn "still $code — docker compose ps"
    docker compose ps remnawave remnawave-db 2>/dev/null || true
    docker compose logs --tail=5 remnawave 2>/dev/null || true
  fi
  sleep 2
done

if [[ $ok -ne 1 ]]; then
  err "API dead. Logs:"
  docker compose logs --tail=40 remnawave
  docker compose ps
  exit 1
fi

info "Remove $TAG_REMOVE from $PROFILE_NAME"
list=$(curl -sS -H "Authorization: Bearer ${TOKEN}" "${API}/config-profiles")
profile_uuid=$(printf '%s' "$list" | python3 -c '
import sys,json
d=json.load(sys.stdin); r=d.get("response",d)
ps=r.get("configProfiles",r) if isinstance(r,dict) else r
name="'"$PROFILE_NAME"'"
for p in (ps if isinstance(ps,list) else []):
  if p.get("name")==name:
    print(p["uuid"]); break
')
if [[ -z "${profile_uuid:-}" ]]; then
  warn "profile not found — skip strip, start node only"
else
  full=$(curl -sS -H "Authorization: Bearer ${TOKEN}" "${API}/config-profiles/${profile_uuid}")
  fixed=$(printf '%s' "$full" | python3 -c '
import sys,json
raw=json.load(sys.stdin); data=raw.get("response",raw)
cfg=data.get("config") or {}; tag="'"$TAG_REMOVE"'"
old=cfg.get("inbounds") or []
cfg["inbounds"]=[ib for ib in old if ib.get("tag")!=tag]
print(json.dumps({"uuid": data.get("uuid"), "name": data.get("name") or "'"$PROFILE_NAME"'", "config": cfg}))
sys.stderr.write("left="+str([ib.get("tag") for ib in cfg["inbounds"]])+"\n")
')
  curl -sS -X PATCH "${API}/config-profiles" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$fixed" >/dev/null
  info "profile patched"
fi

info "Start remnanode"
docker start remnanode || docker compose up -d remnanode
sleep 8
if docker logs --tail=30 remnanode 2>&1 | grep -qE 'version != 2|XrayProcessDownError|failed to build inbound'; then
  warn "Xray still errors:"
  docker logs --tail=20 remnanode 2>&1 | tail -20
  exit 1
fi
info "DONE"
docker logs --tail=10 remnanode 2>&1 | tail -10 || true
curl -sS -o /dev/null -w "API %{http_code}\n" -H "Authorization: Bearer ${TOKEN}" "${API}/nodes"
