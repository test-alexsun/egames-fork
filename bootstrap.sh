#!/usr/bin/env bash
# Bootstrap a reviewed egames-fork checkout; never reset an existing checkout.
set -Eeuo pipefail
umask 077
mode='install'
approve=()
options=()
while (($#)); do
    case "$1" in
        --help|-h)
            printf '%s\n' 'Usage: EGAMES_FORK_REF=<reviewed full SHA> sudo -E bash bootstrap.sh [--dry-run] [--yes] [--config FILE]'
            exit 0 ;;
        --dry-run) mode='dry-run'; shift ;;
        --yes) approve=(--yes); shift ;;
        --config) [[ $# -ge 2 ]] || { echo 'Missing config path' >&2; exit 2; }; options+=(--config "$2"); shift 2 ;;
        *) printf 'Unexpected argument; run bootstrap.sh --help.\n' >&2; exit 2 ;;
    esac
done
readonly REPO='https://github.com/test-alexsun/egames-fork.git'
readonly DEST='/opt/egames-fork'
readonly LOGDIR='/var/log/egames-fork'
readonly CLI='/usr/local/bin/egames-fork'
stage='initialization'
fail() { printf '[ERROR] %s: %s\n' "$stage" "$1" >&2; exit 1; }
trap 'printf "[ERROR] %s failed (exit %s)\n" "$stage" "$?" >&2' ERR
[[ $EUID -eq 0 ]] || fail 'Run with sudo or as root.'
[[ -r /etc/os-release ]] || fail 'Cannot identify operating system.'
# shellcheck disable=SC1091
. /etc/os-release
[[ ${ID:-} == debian && ${VERSION_ID:-} == 13 ]] || fail 'Bootstrap supports Debian 13 only.'
if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
    fail 'Docker is unavailable. Install and verify official eGames first: https://github.com/eGamesAPI/remnawave-reverse-proxy'
fi
docker compose version >/dev/null || fail 'Docker Compose is unavailable.'
[[ ! -e "$CLI" ]] || { [[ -f "$CLI" ]] && head -n 2 "$CLI" | grep -q '# egames-fork managed wrapper'; } || fail "Existing $CLI is not owned by egames-fork."
[[ ! -L "$LOGDIR" ]] || fail 'Symlink log directory is unsupported.'
command -v flock >/dev/null || fail 'flock from util-linux is required.'
exec 9>/run/lock/egames-fork-bootstrap.lock
flock -n 9 || fail 'Another bootstrap is running.'
mkdir -p "$LOGDIR"
chmod 700 "$LOGDIR"
log() { printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "$stage" "$*" | tee -a "$LOGDIR/bootstrap.log"; }
# Check ownership/cleanliness before apt, venv or checkout mutations.
[[ ! -L "$DEST" && ! -L "$CLI" ]] || fail 'Symlink installation paths are unsupported.'
if [[ -e "$DEST" ]]; then
    command -v git >/dev/null || fail 'git is needed to inspect the existing checkout before dependencies.'
    [[ -d "$DEST/.git" ]] || fail 'Existing destination is not a Git checkout.'
    [[ $(git -C "$DEST" remote get-url origin) == "$REPO" ]] || fail 'Existing checkout has a different origin.'
    [[ -z $(git -C "$DEST" status --porcelain --untracked-files=normal) ]] || fail 'Existing checkout has local changes; preserve them before continuing.'
fi
ref=${EGAMES_FORK_REF:-}
[[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]] || fail 'Set EGAMES_FORK_REF to the reviewed full commit SHA; moving main is not accepted.'
sha=${ref,,}
if [[ -d "$DEST/.git" ]]; then
    [[ $(git -C "$DEST" rev-parse HEAD) == "$sha" ]] || fail 'Existing commit differs; update the checkout deliberately.'
fi
stage='dependencies'
log 'Installing required Debian packages if missing.'
packages=()
for package in ca-certificates curl git python3 python3-venv iproute2; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q '^install ok installed$' || packages+=("$package")
done
if ((${#packages[@]})); then
    apt-get update >"$LOGDIR/dependencies.log" 2>&1 || fail "apt update failed; see $LOGDIR/dependencies.log"
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}" >>"$LOGDIR/dependencies.log" 2>&1 || fail "apt install failed; see $LOGDIR/dependencies.log"
fi
stage='source'
if [[ -e "$DEST" ]]; then
    [[ -d "$DEST/.git" ]] || fail "$DEST already exists and is not a Git checkout."
    [[ $(git -C "$DEST" remote get-url origin) == "$REPO" ]] || fail 'Existing checkout has a different origin.'
    [[ -z $(git -C "$DEST" status --porcelain --untracked-files=normal) ]] || fail 'Existing checkout has local changes; preserve and review them before continuing.'
    [[ $(git -C "$DEST" rev-parse HEAD) == "$sha" ]] || fail "Existing checkout differs from requested $sha; update it deliberately before rerunning."
else
    git clone --no-checkout "$REPO" "$DEST" >>"$LOGDIR/dependencies.log" 2>&1 || fail 'Git clone failed.'
    git -C "$DEST" checkout --detach "$sha" >>"$LOGDIR/dependencies.log" 2>&1 || fail 'Requested commit unavailable in checkout.'
fi
# Require the reviewed bootstrap and source to come from exactly the same commit.
cmp -s "${BASH_SOURCE[0]}" <(git -C "$DEST" show "$sha:bootstrap.sh") || fail 'Bootstrap differs from the pinned source commit.'
log "Using commit $sha."
stage='python environment'
if [[ ! -e "$DEST/.venv" ]]; then
    python3 -m venv "$DEST/.venv" >>"$LOGDIR/dependencies.log" 2>&1 || fail 'Cannot create Python virtual environment.'
fi
[[ -x "$DEST/.venv/bin/python" ]] || fail 'Existing .venv is invalid; inspect it before retrying.'
"$DEST/.venv/bin/python" -c 'import sys; supported = sys.version_info[:2] == (3, 13); print("Python compatibility: " + ("3.13 qualified" if supported else "WARNING: unqualified version; use CPython 3.13")); sys.exit(0 if supported else 1)' || fail 'Unsupported Python version; no infrastructure changes applied.'
"$DEST/.venv/bin/python" -m pip install --require-hashes --only-binary=:all: -r "$DEST/requirements.lock" >>"$LOGDIR/dependencies.log" 2>&1 || fail "Python dependencies failed; see $LOGDIR/dependencies.log"
"$DEST/.venv/bin/python" -c 'import requests, yaml, cryptography' || fail 'Python dependencies are unavailable.'
stage='preflight'
log 'Checking existing eGames and validators.'
bash "$DEST/install.sh" --check "${options[@]}" 2>&1 | tee "$LOGDIR/preflight.log" || fail 'Preflight failed; existing infrastructure was not modified.'
if [[ "$mode" == dry-run ]]; then
    log 'Read-only infrastructure plan complete. No API, Nginx or firewall changes applied.'
    exit 0
fi
stage='backup'
bash "$DEST/install.sh" --backup "${options[@]}" 2>&1 | tee -a "$LOGDIR/installation.log" || fail 'Backup failed; installation stopped.'
stage='installation'
bash "$DEST/install.sh" --install "${approve[@]}" "${options[@]}" 2>&1 | tee -a "$LOGDIR/installation.log" || fail 'Installation failed; inspect the transaction journal and logs.'
stage='post-install'
if ! bash "$DEST/install.sh" --check "${options[@]}" 2>&1 | tee "$LOGDIR/post-install.log"; then
    bash "$DEST/install.sh" --restore --yes "${options[@]}" 2>&1 | tee -a "$LOGDIR/installation.log" || fail 'Post-install failure; rollback incomplete. Preserve state and journal.'
    fail 'Post-install check failed; guarded transaction rollback completed.'
fi
wrapper=$(mktemp /usr/local/bin/.egames-fork-XXXXXX)
cat >"$wrapper" <<'WRAPPER'
#!/usr/bin/env bash
# egames-fork managed wrapper
set -Eeuo pipefail
mode=${1:-status}
case "$mode" in
    check|status|repair|update|backup|restore|uninstall|install|dry-run) ;;
    *) echo 'Usage: egames-fork {check|status|repair|update|backup|restore|uninstall|install|dry-run} [options]' >&2; exit 2 ;;
esac
if (($#)); then shift; fi
if [[ -z ${NODE_UUID:-} && -f /var/lib/egames-injector/state.json ]]; then
    NODE_UUID=$(/opt/egames-fork/.venv/bin/python -c 'import re,sys; sys.path.insert(0,"/opt/egames-fork"); from egames_safe import read_state; v=read_state("/var/lib/egames-injector").get("node_uuid", ""); assert re.fullmatch(r"[0-9a-fA-F-]{36}", v), "invalid saved Node UUID"; print(v)')
    export NODE_UUID
fi
exec bash /opt/egames-fork/install.sh "--$mode" "$@"
WRAPPER
chmod 755 "$wrapper"
mv -- "$wrapper" "$CLI"
log 'Installation completed. Client connections and subscription generation: NOT TESTED.'
