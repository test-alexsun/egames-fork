#!/usr/bin/env bash
# ============================================================
# eGames / Remnawave Injector — installer
# Установка на любой сервер (панель или удалённый management-хост)
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/test-alexsun/egames-fork/main/install.sh)
#
# Или:
#   curl -fsSL ... -o install.sh && bash install.sh
# ============================================================

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/test-alexsun/egames-fork/main"
REPO_GIT="https://github.com/test-alexsun/egames-fork.git"
INSTALL_DIR="${INSTALL_DIR:-/opt/egames-injector}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

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

detect_os() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        OS_ID="${ID:-unknown}"
    else
        OS_ID="unknown"
    fi
}

install_system_deps() {
    step "Системные пакеты (python3, pip, venv, curl, git)"
    detect_os
    case "${OS_ID}" in
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
            # venv module
            ${PYTHON_BIN} -m pip install --upgrade pip -q 2>/dev/null || true
            ;;
        *)
            warn "Неизвестная ОС (${OS_ID}). Нужны: python3, pip, curl, git"
            if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
                err "python3 не найден"
                exit 1
            fi
            ;;
    esac
    info "Python: $(${PYTHON_BIN} --version 2>&1)"
}

fetch_project() {
    step "Установка в ${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}"
    if command -v git >/dev/null 2>&1; then
        if [[ -d "${INSTALL_DIR}/.git" ]]; then
            info "Обновление репозитория"
            git -C "${INSTALL_DIR}" fetch --depth 1 origin main 2>/dev/null || true
            git -C "${INSTALL_DIR}" reset --hard origin/main 2>/dev/null \
                || git -C "${INSTALL_DIR}" pull --ff-only 2>/dev/null || true
        else
            rm -rf "${INSTALL_DIR}.tmp"
            if git clone --depth 1 "${REPO_GIT}" "${INSTALL_DIR}.tmp" 2>/dev/null; then
                # сохранить config.yaml если уже был
                if [[ -f "${INSTALL_DIR}/config.yaml" ]]; then
                    cp -a "${INSTALL_DIR}/config.yaml" "${INSTALL_DIR}.tmp/config.yaml"
                fi
                rm -rf "${INSTALL_DIR}"
                mv "${INSTALL_DIR}.tmp" "${INSTALL_DIR}"
            else
                warn "git clone не удался — качаю файлы напрямую"
                download_files
            fi
        fi
    else
        download_files
    fi
}

download_files() {
    mkdir -p "${INSTALL_DIR}"
    for f in remnawave_injector.py config.example.yaml requirements.txt README.md; do
        info "download ${f}"
        curl -fsSL "${REPO_RAW}/${f}" -o "${INSTALL_DIR}/${f}"
    done
    chmod +x "${INSTALL_DIR}/remnawave_injector.py"
}

setup_venv() {
    step "Python venv + зависимости"
    local venv="${INSTALL_DIR}/.venv"
    if [[ ! -d "${venv}" ]]; then
        ${PYTHON_BIN} -m venv "${venv}" 2>/dev/null || {
            warn "venv недоступен — ставим пакеты в --user"
            ${PYTHON_BIN} -m pip install --user -q -r "${INSTALL_DIR}/requirements.txt"
            return
        }
    fi
    # shellcheck source=/dev/null
    source "${venv}/bin/activate"
    pip install -q --upgrade pip
    pip install -q -r "${INSTALL_DIR}/requirements.txt"
    deactivate 2>/dev/null || true
    info "venv: ${venv}"
}

ensure_config() {
    step "Конфигурация"
    if [[ ! -f "${INSTALL_DIR}/config.yaml" ]]; then
        cp "${INSTALL_DIR}/config.example.yaml" "${INSTALL_DIR}/config.yaml"
        info "Создан ${INSTALL_DIR}/config.yaml"
    else
        info "config.yaml уже есть — не перезаписываю"
    fi
    chmod 600 "${INSTALL_DIR}/config.yaml" 2>/dev/null || true
}

write_wrapper() {
    step "CLI-обёртка /usr/local/bin/egames-injector"
    cat > /usr/local/bin/egames-injector << 'WRAP'
#!/usr/bin/env bash
set -euo pipefail
INSTALL_DIR="/opt/egames-injector"
VENV="${INSTALL_DIR}/.venv"
CFG="${INSTALL_DIR}/config.yaml"

if [[ -x "${VENV}/bin/python" ]]; then
    PY="${VENV}/bin/python"
else
    PY="python3"
fi

exec "${PY}" "${INSTALL_DIR}/remnawave_injector.py" -c "${CFG}" "$@"
WRAP
    chmod +x /usr/local/bin/egames-injector
    info "Команда: egames-injector"
}

write_systemd_optional() {
    # Не включаем по умолчанию — только шаблон
    cat > "${INSTALL_DIR}/egames-injector.service" << 'UNIT'
[Unit]
Description=Remnawave eGames Config/Hosts Injector (one-shot)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/egames-injector
ExecStart=/usr/local/bin/egames-injector
User=root
Nice=10

[Install]
WantedBy=multi-user.target
UNIT

    cat > "${INSTALL_DIR}/egames-injector.timer" << 'TIMER'
[Unit]
Description=Run eGames Injector daily

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
TIMER
    info "Шаблон systemd: ${INSTALL_DIR}/egames-injector.service (+ .timer)"
}

print_next_steps() {
    echo
    echo -e "${GREEN}============================================================${NC}"
    echo -e "${GREEN}  Установка завершена: ${INSTALL_DIR}${NC}"
    echo -e "${GREEN}============================================================${NC}"
    echo
    echo "1. Отредактируйте конфиг (токен панели + адрес ноды):"
    echo -e "   ${CYAN}nano ${INSTALL_DIR}/config.yaml${NC}"
    echo
    echo "   Обязательно:"
    echo "     panel_api_token: \"rwa_...\"   # Settings → API Tokens"
    echo "     host_address: \"node.example.com\""
    echo
    echo "   Если скрипт НЕ на сервере панели — укажите URL и cookie:"
    echo "     panel_api_url: \"https://panel.example.com/api\""
    echo "     egames_cookie: \"name=value\"   # из nginx map eGames"
    echo
    echo "2. Проверка (без изменений):"
    echo -e "   ${CYAN}egames-injector --dry-run${NC}"
    echo
    echo "3. Применить (создать inbounds + hosts):"
    echo -e "   ${CYAN}egames-injector${NC}"
    echo
    echo "Опционально — ежедневный запуск:"
    echo "   cp ${INSTALL_DIR}/egames-injector.service /etc/systemd/system/"
    echo "   cp ${INSTALL_DIR}/egames-injector.timer   /etc/systemd/system/"
    echo "   systemctl daemon-reload"
    echo "   systemctl enable --now egames-injector.timer"
    echo
}

# -------------------- main --------------------
main() {
    need_root
    echo
    echo -e "${CYAN}eGames / Remnawave Injector installer${NC}"
    echo
    install_system_deps
    fetch_project
    setup_venv
    ensure_config
    write_wrapper
    write_systemd_optional
    print_next_steps
}

main "$@"
