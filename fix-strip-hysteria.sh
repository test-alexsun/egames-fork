#!/usr/bin/env bash
# Strip HYSTERIA2 via API with eGames proxy headers (panel requires them)
set -euo pipefail

TOKEN_FILE="${TOKEN_FILE:-/usr/local/remnawave_reverse/token}"
API="${API:-http://127.0.0.1:3000/api}"
PROFILE_NAME="${PROFILE_NAME:-eGames-MultiProtocol}"
TAG_REMOVE="${TAG_REMOVE:-HYSTERIA2}"

info(){ echo -e "\033[1;32m[+]\033[0m $*"; }
err(){ echo -e "\033[1;31m[x]\033[0m $*" >&2; }

[[ ${EUID} -eq 0 ]] || { err "root"; exit 1; }
TOKEN=$(tr -d '\r\n ' < "$TOKEN_FILE")

HDR=(
  -H "Authorization: Bearer ${TOKEN}"
  -H "Content-Type: application/json"
  -H "X-Forwarded-For: 127.0.0.1"
  -H "X-Forwarded-Proto: https"
  -H "X-Remnawave-Client-Type: browser"
)

info "Check API"
code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 \
  "${HDR[@]}" "${API}/nodes" || echo 000)
[[ "$code" == "200" ]] || { err "API http $code — is remnawave up?"; exit 1; }
info "API OK"

info "Stop remnanode"
docker stop remnanode 2>/dev/null || true

info "Find profile $PROFILE_NAME"
list=$(curl -sS "${HDR[@]}" "${API}/config-profiles")
profile_uuid=$(printf '%s' "$list" | python3 -c '
import sys,json
d=json.load(sys.stdin); r=d.get("response",d)
ps=r.get("configProfiles",r) if isinstance(r,dict) else r
name="'"$PROFILE_NAME"'"
for p in (ps if isinstance(ps,list) else []):
  if p.get("name")==name:
    print(p["uuid"]); break
')
[[ -n "${profile_uuid:-}" ]] || { err "profile not found"; exit 1; }
info "uuid=$profile_uuid"

full=$(curl -sS "${HDR[@]}" "${API}/config-profiles/${profile_uuid}")
fixed=$(printf '%s' "$full" | python3 -c '
import sys,json
raw=json.load(sys.stdin); data=raw.get("response",raw)
cfg=data.get("config") or {}; tag="'"$TAG_REMOVE"'"
old=list(cfg.get("inbounds") or [])
cfg["inbounds"]=[ib for ib in old if ib.get("tag")!=tag]
print(json.dumps({
  "uuid": data.get("uuid"),
  "name": data.get("name") or "'"$PROFILE_NAME"'",
  "config": cfg,
}))
sys.stderr.write("removed %d -> %s\n" % (len(old)-len(cfg["inbounds"]), [ib.get("tag") for ib in cfg["inbounds"]]))
')

info "PATCH profile"
curl -sS -X PATCH "${API}/config-profiles" "${HDR[@]}" -d "$fixed" | python3 -c '
import sys,json
try:
  d=json.load(sys.stdin); r=d.get("response",d)
  print("ok name=", r.get("name"), "inbounds=", len((r.get("config") or {}).get("inbounds") or r.get("inbounds") or []))
except Exception as e:
  print(sys.stdin.read() if False else d if False else str(e))
' 2>/dev/null || true

info "Start remnanode"
docker start remnanode
sleep 8
if docker logs --tail=25 remnanode 2>&1 | grep -qE 'version != 2|XrayProcessDownError|failed to build inbound'; then
  err "Xray still failing"
  docker logs --tail=15 remnanode 2>&1 | tail -15
  exit 1
fi
info "DONE"
docker logs --tail=8 remnanode 2>&1 | tail -8 || true
