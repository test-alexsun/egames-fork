#!/usr/bin/env bash
# ============================================================
# Постустановка: приводит свежую связку eGames + injector в рабочее состояние.
# Запускать ПОСЛЕ install.sh (injector уже создал профиль eGames-MultiProtocol).
#
#   bash post-install.sh            # спросит подтверждение
#   bash post-install.sh --yes      # без вопросов
#   FLAG=🇩🇪 NODE_MARK=② bash post-install.sh --yes
#
# Шаги (каждый идемпотентен; на первой ошибке скрипт останавливается):
#   1. fix-add-steal-443.py  — вернуть inbound Steal на 443 в профиль eGames
#   2. fix-tls-certs.py      — смонтировать сертификаты в remnanode и прописать их в TLS-inbounds
#   3. fix-hosts.py          — перепривязать хост 443, отключить устаревшие хосты
#   4. fix-host-names.py     — единые имена хостов (флаг страны VPS + символ ноды)
#   5. fix-firewall.py       — открыть порты inbound'ов в ufw
# Бэкапы профилей/хостов/compose: /root/remnawave-backup/
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${EUID}" -ne 0 ]]; then echo "[x] Запустите от root" >&2; exit 1; fi

if [[ "${1:-}" != "--yes" ]]; then
  echo "Будут изменены: профиль/хосты в панели, docker-compose.yml (remnanode перезапустится), правила ufw."
  echo "Бэкапы: /root/remnawave-backup/"
  read -r -p "Продолжить? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "Отменено"; exit 0; }
fi

run() { echo; echo "==> $*"; "$@"; }

run python3 fix-add-steal-443.py --apply
run python3 fix-tls-certs.py --apply
run python3 fix-hosts.py --apply
run python3 fix-host-names.py --apply
run python3 fix-firewall.py --apply

echo
echo "[+] Готово. Проверьте: ss -tlnp | grep rw-core ; обновите подписку в клиенте."
echo "[!] Файрвол хостера (панель провайдера) скрипт не меняет — откройте те же порты там."
