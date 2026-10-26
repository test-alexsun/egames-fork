#!/usr/bin/env bash
# ============================================================
# Fix: Xray crash loop caused by HYSTERIA2 (version != 2)
# Removes HYSTERIA2 from eGames-MultiProtocol and restarts node.
#
#   bash fix-node-hysteria.sh
# ============================================================
set -euo pipefail

TOKEN_FILE="${TOKEN_FILE:-/usr/local/remnawave_reverse/token}"
API="${API:-http://127.0.0.1:3000/api}"
PROFILE_NAME="${PROFILE_NAME:-eGames-MultiProtocol}"
TAG_REMOVE="${TAG_REMOVE:-HYSTERIA2}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/remnawave}"

RED='\033[1;31m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info(){ echo -e "${GREEN}[+]${NC} $*"; }
warn(){ echo -e "${YELLOW}[!]${NC} $*"; }
err(){ echo -e "${RED}[x]${NC} $*" >&2; }

need_root() {
  [[ ${EUID} -eq 0 ]] || { err "run as root"; exit 1; }
}

api_ok() {
  local code
  code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 8 \
    -H "X-Forwarded-For: 127.0.0.1" -H "X-Forwarded-Proto: https" -H "X-Remnawave-Client-Type: browser" \
    -H "Authorization: Bearer ${TOKEN}" "${API}/nodes" 2>/dev/null || echo 000)
  [[ "$code" == "200" || "$code" == "201" ]]
}

wait_api() {
  for _ in $(seq 1 30); do
    if api_ok; then
      info "API OK"
      return 0
    fi
    echo -n "."
    sleep 2
  done
  echo
  err "API still down after wait"
  return 1
}

main() {
  need_root
  [[ -s "$TOKEN_FILE" ]] || { err "no token: $TOKEN_FILE"; exit 1; }
  TOKEN=$(tr -d '\r\n ' < "$TOKEN_FILE")

  info "1/4 Stop remnanode (break crash loop)"
  docker stop remnanode 2>/dev/null || true
  sleep 3

  if ! api_ok; then
    warn "API down — restart remnawave"
    (cd "$COMPOSE_DIR" && docker compose restart remnawave) || true
    sleep 8
  fi
  wait_api || exit 1

  info "2/4 Find profile: $PROFILE_NAME"
  local list profile_uuid
  list=$(curl -sS -H "Authorization: Bearer ${TOKEN}" "${API}/config-profiles")
  profile_uuid=$(printf '%s' "$list" | python3 -c '
import sys,json
d=json.load(sys.stdin)
r=d.get("response",d)
ps=r.get("configProfiles",r) if isinstance(r,dict) else r
name="'"$PROFILE_NAME"'"
for p in (ps if isinstance(ps,list) else []):
    if p.get("name")==name:
        print(p["uuid"]); break
')
  if [[ -z "$profile_uuid" ]]; then
    err "profile '$PROFILE_NAME' not found"
    exit 1
  fi
  info "profile uuid=$profile_uuid"

  info "3/4 Remove inbound tag=$TAG_REMOVE"
  local full fixed
  full=$(curl -sS -H "Authorization: Bearer ${TOKEN}" \
    "${API}/config-profiles/${profile_uuid}")
  fixed=$(printf '%s' "$full" | python3 -c '
import sys,json
raw=json.load(sys.stdin)
data=raw.get("response",raw)
cfg=data.get("config") or {}
tag="'"$TAG_REMOVE"'"
old=cfg.get("inbounds") or []
new=[ib for ib in old if ib.get("tag")!=tag]
removed=len(old)-len(new)
cfg["inbounds"]=new
out={
  "uuid": data.get("uuid"),
  "name": data.get("name") or "'"$PROFILE_NAME"'",
  "config": cfg,
}
print(json.dumps(out))
sys.stderr.write(f"removed={removed} left={[ib.get(\"tag\") for ib in new]}\n")
')
  curl -sS -X PATCH "${API}/config-profiles" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$fixed" >/tmp/profile_patch_resp.json
  info "profile patched"

  info "4/4 Start remnanode"
  docker start remnanode
  sleep 6
  if docker logs --tail=25 remnanode 2>&1 | grep -qE 'version != 2|XrayProcessDownError|failed to start'; then
    warn "Xray still failing — check: docker logs --tail=40 remnanode"
    docker logs --tail=15 remnanode 2>&1 | tail -15
    exit 1
  fi
  info "OK — HYSTERIA2 removed, node should stay up"
  docker logs --tail=8 remnanode 2>&1 | tail -8 || true
}

main "$@"
