#!/usr/bin/env bash
# ============================================================
# eGames / Remnawave Injector — installer
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/install.sh)
#
# Автоматически подтягивает из eGames:
#   - API token  → /usr/local/remnawave_reverse/token
#   - PANEL_DOMAIN, SUB_PUBLIC_DOMAIN → /opt/remnawave/.env
#   - cookie gate → /opt/remnawave/nginx.conf
#   - host_address (нода) → API /nodes или selfsteal-домен
# Затем создаёт config.yaml и (по умолчанию) запускает injector.
# ============================================================

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/test-alexsun/egames-fork/main"
REPO_GIT="https://github.com/test-alexsun/egames-fork.git"
INSTALL_DIR="${INSTALL_DIR:-/opt/egames-injector}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# eGames paths (как в install_remnawave.sh)
DIR_REMNAWAVE="${DIR_REMNAWAVE:-/usr/local/remnawave_reverse}"
REMNAWAVE_DIR="${REMNAWAVE_DIR:-/opt/remnawave}"
TOKEN_FILE="${DIR_REMNAWAVE}/token"
ENV_FILE="${REMNAWAVE_DIR}/.env"
NGINX_CONF="${REMNAWAVE_DIR}/nginx.conf"
CADDYFILE="${REMNAWAVE_DIR}/Caddyfile"

# 1 = сразу после установки запустить injector
RUN_AFTER_INSTALL="${RUN_AFTER_INSTALL:-1}"

RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
CYAN='\033[1;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[x]${NC} $*" >&2; }
step()  { echo -e "${CYAN}==>${NC} $*"; }

need_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        err "Запустите от root: sudo bash $0"
        exit 1
    fi
}

# -------------------- detect eGames --------------------

read_env_var() {
    local key="$1" file="${2:-$ENV_FILE}"
    [[ -f "$file" ]] || return 0
    grep -E "^${key}=" "$file" 2>/dev/null | head -n1 \
        | sed -e "s/^${key}=//" -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//" -e 's/[[:space:]]*$//'
}

detect_panel_token() {
    if [[ -s "$TOKEN_FILE" ]]; then
        cat "$TOKEN_FILE" | tr -d '\r\n '
        return 0
    fi
    # fallback: docker-compose / .env REMNAWAVE_API_TOKEN
    local t
    t=$(read_env_var "REMNAWAVE_API_TOKEN" "$ENV_FILE")
    if [[ -z "$t" && -f "${REMNAWAVE_DIR}/docker-compose.yml" ]]; then
        t=$(grep -E 'REMNAWAVE_API_TOKEN:' "${REMNAWAVE_DIR}/docker-compose.yml" 2>/dev/null \
            | head -n1 | sed -E 's/.*REMNAWAVE_API_TOKEN:[[:space:]]*//' | tr -d '"'\''[:space:]')
    fi
    printf '%s' "$t"
}

detect_cookie() {
    local line c1 c2
    if [[ -f "$NGINX_CONF" ]] && grep -q 'map $http_cookie $auth_cookie' "$NGINX_CONF" 2>/dev/null; then
        line=$(grep -A 3 'map $http_cookie $auth_cookie' "$NGINX_CONF" | grep -E '~\*' | head -n1 || true)
        # ~*NAME=VALUE
        c1=$(printf '%s' "$line" | sed -n 's/.*~\*\([A-Za-z0-9_-]*\)=.*/\1/p')
        c2=$(printf '%s' "$line" | sed -n 's/.*~\*[A-Za-z0-9_-]*=\([A-Za-z0-9_-]*\).*/\1/p')
        if [[ -n "$c1" && -n "$c2" ]]; then
            echo "${c1}=${c2}"
            return 0
        fi
    fi
    if [[ -f "$CADDYFILE" ]]; then
        line=$(grep 'header +Set-Cookie' "$CADDYFILE" 2>/dev/null | head -n1 || true)
        c1=$(printf '%s' "$line" | sed -n 's/.*Set-Cookie "\([^=]*\)=.*/\1/p')
        c2=$(printf '%s' "$line" | sed -n 's/.*Set-Cookie "[^=]*=\([^;"]*\).*/\1/p')
        if [[ -n "$c1" && -n "$c2" ]]; then
            echo "${c1}=${c2}"
            return 0
        fi
    fi
    return 0
}

detect_panel_domain() {
    local d
    d=$(read_env_var "PANEL_DOMAIN")
    [[ -n "$d" ]] && { echo "$d"; return; }
    d=$(read_env_var "FRONT_END_DOMAIN")
    [[ -n "$d" && "$d" != "*" ]] && { echo "$d"; return; }
    # nginx server_name
    if [[ -f "$NGINX_CONF" ]]; then
        d=$(grep -E '^\s*server_name\s+' "$NGINX_CONF" 2>/dev/null \
            | head -n1 | sed -E 's/.*server_name\s+([^;]+);.*/\1/' | awk '{print $1}')
        [[ -n "$d" && "$d" != "_" ]] && { echo "$d"; return; }
    fi
}

detect_sub_domain() {
    local d
    d=$(read_env_var "SUB_PUBLIC_DOMAIN")
    # often "sub.example.com/api/sub" → take host part
    d="${d%%/*}"
    echo "$d"
}

# Node domain: prefer live API; fallback nginx / selfsteal hints
detect_node_address() {
    local token="$1"
    local addr=""

    if [[ -n "$token" ]] && command -v curl >/dev/null 2>&1; then
        local resp
        resp=$(curl -fsS --connect-timeout 5 --max-time 15 \
            -H "Authorization: Bearer ${token}" \
            -H "Content-Type: application/json" \
            -H "X-Remnawave-Client-Type: browser" \
            "http://127.0.0.1:3000/api/nodes" 2>/dev/null || true)
        if [[ -n "$resp" ]]; then
            addr=$(printf '%s' "$resp" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    nodes = d.get("response", d)
    if isinstance(nodes, dict):
        nodes = nodes.get("nodes") or nodes.get("items") or []
    if not isinstance(nodes, list):
        nodes = []
    for n in nodes:
        if n.get("isDisabled"):
            continue
        a = n.get("address") or ""
        if a and a not in ("127.0.0.1", "localhost", "172.30.0.1"):
            print(a)
            break
    else:
        if nodes:
            print(nodes[0].get("address") or "")
except Exception:
    pass
' 2>/dev/null || true)
        fi
    fi

    if [[ -n "$addr" ]]; then
        echo "$addr"
        return
    fi

    # fallback: second/third server_name in nginx (selfsteal / node)
    if [[ -f "$NGINX_CONF" ]]; then
        addr=$(grep -E '^\s*server_name\s+' "$NGINX_CONF" 2>/dev/null \
            | sed -E 's/.*server_name\s+([^;]+);.*/\1/' | awk '{print $1}' \
            | grep -vE '^(_|localhost)$' | sed -n '2p')
        [[ -n "$addr" ]] && { echo "$addr"; return; }
    fi

    # last resort: panel domain
    detect_panel_domain
}

detect_all() {
    step "Чтение настроек eGames / Remnawave"

    DETECTED_TOKEN="$(detect_panel_token || true)"
    DETECTED_COOKIE="$(detect_cookie || true)"
    DETECTED_PANEL_DOMAIN="$(detect_panel_domain || true)"
    DETECTED_SUB_DOMAIN="$(detect_sub_domain || true)"
    DETECTED_NODE="$(detect_node_address "${DETECTED_TOKEN}" || true)"

    info "token:        ${DETECTED_TOKEN:+yes (${#DETECTED_TOKEN} chars)}${DETECTED_TOKEN:-НЕ НАЙДЕН}"
    info "panel domain: ${DETECTED_PANEL_DOMAIN:-—}"
    info "sub domain:   ${DETECTED_SUB_DOMAIN:-—}"
    info "node/host:    ${DETECTED_NODE:-—}"
    info "cookie:       ${DETECTED_COOKIE:-— (localhost API)}"

    if [[ -z "$DETECTED_TOKEN" ]]; then
        warn "Файл ${TOKEN_FILE} не найден. Убедитесь, что eGames-панель установлена."
        warn "Можно прописать panel_api_token вручную в config.yaml после установки."
    fi
}

# -------------------- system / project --------------------

install_system_deps() {
    step "Системные пакеты"
    if [[ -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        case "${ID:-}" in
            ubuntu|debian)
                apt-get update -qq
                DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
                    python3 python3-pip python3-venv curl git ca-certificates
                ;;
            centos|rhel|rocky|almalinux|fedora)
                if command -v dnf >/dev/null 2>&1; then
                    dnf install -y -q python3 python3-pip curl git ca-certificates
                else
                    yum install -y -q python3 python3-pip curl git ca-certificates
                fi
                ;;
        esac
    fi
    info "Python: $(${PYTHON_BIN} --version 2>&1)"
}

fetch_project() {
    step "Файлы → ${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}"
    local keep_cfg=""
    [[ -f "${INSTALL_DIR}/config.yaml" ]] && keep_cfg=$(cat "${INSTALL_DIR}/config.yaml")

    if command -v git >/dev/null 2>&1; then
        if [[ -d "${INSTALL_DIR}/.git" ]]; then
            git -C "${INSTALL_DIR}" fetch --depth 1 origin main 2>/dev/null || true
            git -C "${INSTALL_DIR}" reset --hard origin/main 2>/dev/null || true
        else
            rm -rf "${INSTALL_DIR}.tmp"
            if git clone --depth 1 "${REPO_GIT}" "${INSTALL_DIR}.tmp" 2>/dev/null; then
                rm -rf "${INSTALL_DIR}"
                mv "${INSTALL_DIR}.tmp" "${INSTALL_DIR}"
            else
                download_files
            fi
        fi
    else
        download_files
    fi

    if [[ -n "$keep_cfg" && ! -f "${INSTALL_DIR}/config.yaml" ]]; then
        printf '%s\n' "$keep_cfg" > "${INSTALL_DIR}/config.yaml"
    fi
    chmod +x "${INSTALL_DIR}/remnawave_injector.py" 2>/dev/null || true
}

download_files() {
    mkdir -p "${INSTALL_DIR}"
    for f in remnawave_injector.py config.example.yaml requirements.txt README.md; do
        curl -fsSL "${REPO_RAW}/${f}" -o "${INSTALL_DIR}/${f}"
    done
}

setup_venv() {
    step "venv + pip"
    local venv="${INSTALL_DIR}/.venv"
    if ${PYTHON_BIN} -m venv "${venv}" 2>/dev/null; then
        # shellcheck source=/dev/null
        source "${venv}/bin/activate"
        pip install -q --upgrade pip
        pip install -q -r "${INSTALL_DIR}/requirements.txt"
        deactivate 2>/dev/null || true
        info "venv OK"
    else
        ${PYTHON_BIN} -m pip install --user -q -r "${INSTALL_DIR}/requirements.txt"
    fi
}

# -------------------- write config from eGames --------------------

write_config_from_egames() {
    step "Генерация config.yaml из eGames"

    local token="${DETECTED_TOKEN:-}"
    local host="${DETECTED_NODE:-}"
    local cookie="${DETECTED_COOKIE:-}"
    local panel_domain="${DETECTED_PANEL_DOMAIN:-}"
    local api_url="http://127.0.0.1:3000/api"
    local reality_sni="${host}"

    # если панель слушает только снаружи — можно переключить, но eGames API
    # всегда доступен на localhost:3000 с сервера панели
    if [[ ! -S /var/run/docker.sock ]] && [[ -n "$panel_domain" ]] && [[ -z "$token" ]]; then
        api_url="https://${panel_domain}/api"
    fi

    # не затирать уже заполненный ручной config, если токен не найден
    if [[ -f "${INSTALL_DIR}/config.yaml" ]] && grep -q 'panel_api_token: "rwa_' "${INSTALL_DIR}/config.yaml" 2>/dev/null; then
        if ! grep -q 'rwa_REPLACE\|ВАШ_ТОКЕН\|REPLACE_ME' "${INSTALL_DIR}/config.yaml" 2>/dev/null; then
            if [[ -z "$token" ]]; then
                info "config.yaml уже настроен — оставляю"
                return 0
            fi
        fi
    fi

    # базовый шаблон
    if [[ ! -f "${INSTALL_DIR}/config.example.yaml" ]]; then
        err "нет config.example.yaml"
        exit 1
    fi
    cp "${INSTALL_DIR}/config.example.yaml" "${INSTALL_DIR}/config.yaml"

    # подстановка через python (надёжнее sed для yaml)
    TOKEN="$token" HOST="$host" COOKIE="$cookie" API_URL="$api_url" SNI="$reality_sni" \
    PANEL_DOMAIN="$panel_domain" SUB_DOMAIN="${DETECTED_SUB_DOMAIN:-}" \
    ${PYTHON_BIN} - << 'PY'
import os, re
from pathlib import Path
p = Path("/opt/egames-injector/config.yaml")
# INSTALL_DIR may differ — use env
install = os.environ.get("INSTALL_DIR", "/opt/egames-injector")
p = Path(install) / "config.yaml"
text = p.read_text(encoding="utf-8")

def repl(key, val):
    global text
    if val is None or val == "":
        return
    # panel_api_token: "..."
    text = re.sub(
        rf'^({re.escape(key)}:\s*)".*?"',
        rf'\1"{val}"',
        text,
        count=1,
        flags=re.M,
    )

repl("panel_api_token", os.environ.get("TOKEN", ""))
repl("host_address", os.environ.get("HOST", ""))
repl("egames_cookie", os.environ.get("COOKIE", ""))
repl("panel_api_url", os.environ.get("API_URL", "http://127.0.0.1:3000/api"))
repl("reality_server_name", os.environ.get("SNI", "") or os.environ.get("HOST", ""))

# комментарий с доменами eGames
banner = (
    f"# Auto-filled from eGames on install\n"
    f"# panel: {os.environ.get('PANEL_DOMAIN', '')}\n"
    f"# sub:   {os.environ.get('SUB_DOMAIN', '')}\n"
    f"# node:  {os.environ.get('HOST', '')}\n"
)
if not text.startswith("# Auto-filled"):
    text = banner + text
p.write_text(text, encoding="utf-8")
print("config.yaml written")
PY

    chmod 600 "${INSTALL_DIR}/config.yaml"
    info "config.yaml готов"
}

write_wrapper() {
    step "CLI /usr/local/bin/egames-injector"
    cat > /usr/local/bin/egames-injector << WRAP
#!/usr/bin/env bash
set -euo pipefail
INSTALL_DIR="${INSTALL_DIR}"
VENV="\${INSTALL_DIR}/.venv"
CFG="\${INSTALL_DIR}/config.yaml"
if [[ -x "\${VENV}/bin/python" ]]; then
    PY="\${VENV}/bin/python"
else
    PY="python3"
fi
exec "\${PY}" "\${INSTALL_DIR}/remnawave_injector.py" -c "\${CFG}" "\$@"
WRAP
    chmod +x /usr/local/bin/egames-injector
}

write_systemd() {
    cat > "${INSTALL_DIR}/egames-injector.service" << UNIT
[Unit]
Description=Remnawave eGames Config/Hosts Injector
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/local/bin/egames-injector
User=root

[Install]
WantedBy=multi-user.target
UNIT
    cat > "${INSTALL_DIR}/egames-injector.timer" << 'TIMER'
[Unit]
Description=Daily eGames Injector

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
TIMER
}

run_injector() {
    step "Запуск injector (создание inbounds + hosts)"
    if [[ ! -s "${INSTALL_DIR}/config.yaml" ]]; then
        warn "нет config.yaml — пропуск"
        return 0
    fi
    if grep -qE 'rwa_REPLACE|ВАШ_ТОКЕН|REPLACE_ME' "${INSTALL_DIR}/config.yaml" 2>/dev/null; then
        warn "token не подставлен — пропуск автозапуска"
        warn "Пропишите panel_api_token и выполните: egames-injector"
        return 0
    fi
    if ! grep -qE 'host_address: "[^"]+"' "${INSTALL_DIR}/config.yaml" 2>/dev/null; then
        warn "host_address пуст — пропуск"
        return 0
    fi
    # host still placeholder?
    if grep -q 'host_address: "node.example.com"' "${INSTALL_DIR}/config.yaml" 2>/dev/null; then
        warn "host_address = node.example.com — укажите домен ноды и запустите egames-injector"
        return 0
    fi

    set +e
    /usr/local/bin/egames-injector
    local rc=$?
    set -e
    if [[ $rc -eq 0 ]]; then
        info "Inbounds и Hosts созданы"
    else
        warn "Injector завершился с кодом $rc — смотрите лог выше"
        warn "Повтор: egames-injector"
    fi
}

print_summary() {
    echo
    echo -e "${GREEN}============================================================${NC}"
    echo -e "${GREEN}  eGames Injector установлен: ${INSTALL_DIR}${NC}"
    echo -e "${GREEN}============================================================${NC}"
    echo
    echo "  panel domain : ${DETECTED_PANEL_DOMAIN:-—}"
    echo "  sub domain   : ${DETECTED_SUB_DOMAIN:-—}"
    echo "  node / host  : ${DETECTED_NODE:-—}"
    echo "  token        : ${DETECTED_TOKEN:+OK}${DETECTED_TOKEN:-не найден}"
    echo "  cookie       : ${DETECTED_COOKIE:-localhost}"
    echo
    echo "Команды:"
    echo -e "  ${CYAN}egames-injector --dry-run${NC}"
    echo -e "  ${CYAN}egames-injector${NC}"
    echo -e "  ${CYAN}nano ${INSTALL_DIR}/config.yaml${NC}"
    echo
}

# -------------------- main --------------------
main() {
    need_root
    export INSTALL_DIR
    echo
    echo -e "${CYAN}eGames / Remnawave Injector — автоустановка${NC}"
    echo

    install_system_deps
    detect_all
    fetch_project
    setup_venv
    write_config_from_egames
    write_wrapper
    write_systemd
    print_summary

    if [[ "${RUN_AFTER_INSTALL}" == "1" ]]; then
        run_injector
    else
        info "Автозапуск отключён (RUN_AFTER_INSTALL=0)"
    fi
}

main "$@"
