#!/usr/bin/env python3
"""Make TLS inbounds of eGames-MultiProtocol work (WS/XHTTP/gRPC/HTTPUpgrade).

Order matters (a bad order takes the WHOLE node down, because Xray refuses to start
when a certificateFile is missing):
  1. mount /etc/letsencrypt (read-only) into the remnanode container   [docker-compose.yml]
  2. recreate remnanode and verify the cert files are readable INSIDE it
  3. only then add 'certificates' to the TLS inbounds in the panel profile
  4. open the TLS ports in ufw

Usage (on the VPS, as root):
    python3 fix-tls-certs.py            # dry-run: shows what would be changed
    python3 fix-tls-certs.py --apply
Env: COMPOSE_DIR, CERT_DOMAIN (default: SNI of the TLS inbounds), PROFILE, TOKEN_FILE, API
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

COMPOSE_DIR = os.environ.get("COMPOSE_DIR", "/opt/remnawave")
DOMAIN = os.environ.get("CERT_DOMAIN", "")  # empty = serverName of the first TLS inbound
PROFILE = os.environ.get("PROFILE", "eGames-MultiProtocol")
TOKEN_FILE = os.environ.get("TOKEN_FILE", "/usr/local/remnawave_reverse/token")
API = os.environ.get("API", "http://127.0.0.1:3000/api").rstrip("/")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "/root/remnawave-backup")
MOUNT_LINE = "/etc/letsencrypt:/etc/letsencrypt:ro"
ANCHOR = "./xray-custom:/usr/local/bin/xray"
CERT = KEY = ""  # set in main() once the domain is known
TOKEN = open(TOKEN_FILE).read().strip()


def sh(cmd, check=True):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=COMPOSE_DIR)
    if check and r.returncode != 0:
        sys.exit(f"command failed: {cmd}\n{r.stdout}{r.stderr}")
    return r


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    for k, v in {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
                 "X-Forwarded-For": "127.0.0.1", "X-Forwarded-Proto": "https",
                 "X-Remnawave-Client-Type": "browser"}.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode() or "{}"
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {method} {path}: {e.read().decode()[:400]}")
    d = json.loads(raw)
    return d.get("response", d) if isinstance(d, dict) else d


def get_profile():
    r = call("GET", "/config-profiles")
    r = r.get("configProfiles", r) if isinstance(r, dict) else r
    return next((p for p in r if p["name"] == PROFILE), None)


def tls_inbounds(cfg):
    return [ib for ib in cfg.get("inbounds", [])
            if (ib.get("streamSettings") or {}).get("security") == "tls"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    global DOMAIN, CERT, KEY

    prof = get_profile()
    if not prof:
        sys.exit(f"profile {PROFILE} not found")
    cfg = prof["config"]
    if not DOMAIN:
        DOMAIN = next(((ib["streamSettings"].get("tlsSettings") or {}).get("serverName")
                       for ib in tls_inbounds(cfg)
                       if (ib["streamSettings"].get("tlsSettings") or {}).get("serverName")), "")
        if not DOMAIN:
            sys.exit("cannot detect certificate domain; set CERT_DOMAIN=<domain>")
    CERT = f"/etc/letsencrypt/live/{DOMAIN}/fullchain.pem"
    KEY = f"/etc/letsencrypt/live/{DOMAIN}/privkey.pem"
    print(f"[i] certificate domain: {DOMAIN}")

    if not os.path.exists(f"/etc/letsencrypt/live/{DOMAIN}/fullchain.pem"):
        sys.exit(f"no certificate on host for {DOMAIN}")
    todo = [ib for ib in tls_inbounds(cfg)
            if not ((ib["streamSettings"].get("tlsSettings") or {}).get("certificates"))]
    ports = sorted({ib["port"] for ib in tls_inbounds(cfg)})
    compose = os.path.join(COMPOSE_DIR, "docker-compose.yml")
    text = open(compose).read()
    need_mount = MOUNT_LINE not in text and "/etc/letsencrypt:/etc/letsencrypt" not in text

    print(f"[i] TLS inbounds without certificates: {[i['tag'] for i in todo]}")
    print(f"[i] compose mount needed: {need_mount}; ufw ports: {ports}")
    if need_mount and ANCHOR not in text:
        sys.exit(f"anchor line '{ANCHOR}' not found in compose; add the mount manually: "
                 f"- {MOUNT_LINE} under remnanode volumes")
    if not a.apply:
        print("[!] dry-run. Re-run with --apply (remnanode will restart for a few seconds)")
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(compose, os.path.join(BACKUP_DIR, f"docker-compose.yml.{stamp}"))
    with open(os.path.join(BACKUP_DIR, f"profile_tls_{stamp}.json"), "w") as f:
        json.dump(prof, f, indent=2)

    if need_mount:
        lines = text.split("\n")
        i = next(n for n, l in enumerate(lines) if ANCHOR in l)
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        lines.insert(i + 1, f"{indent}- {MOUNT_LINE}")
        open(compose, "w").write("\n".join(lines))
        if sh("docker compose config -q", check=False).returncode != 0:
            shutil.copy2(os.path.join(BACKUP_DIR, f"docker-compose.yml.{stamp}"), compose)
            sys.exit("compose invalid after edit; restored the backup")
        print("[+] mount added to docker-compose.yml")
        sh("docker compose up -d remnanode")
        time.sleep(5)

    # verify files are visible INSIDE the container BEFORE touching the profile
    for path in (CERT, KEY):
        if sh(f"docker exec remnanode test -r {path}", check=False).returncode != 0:
            sys.exit(f"{path} is not readable inside remnanode; profile NOT changed")
    print("[+] certificate files readable inside remnanode")

    if todo:
        new_cfg = json.loads(json.dumps(cfg))
        for ib in tls_inbounds(new_cfg):
            tls = ib["streamSettings"].setdefault("tlsSettings", {})
            if not tls.get("certificates"):
                tls["certificates"] = [{"certificateFile": CERT, "keyFile": KEY}]
        call("PATCH", "/config-profiles",
             {"uuid": prof["uuid"], "name": prof["name"], "config": new_cfg})
        print(f"[+] profile patched ({len(todo)} inbounds)")

    for p in ports:
        sh(f"ufw allow {p}/tcp comment 'xray tls'", check=False)
    print(f"[+] ufw opened: {ports}")
    print("[i] wait ~20s, then: ss -tlnp | grep rw-core")


if __name__ == "__main__":
    main()
