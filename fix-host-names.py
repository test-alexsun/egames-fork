#!/usr/bin/env python3
"""Uniform, readable host names in Remnawave.

Format:  <flag><node> | <protocol> · <transport> · <security> · <port>
Example: 🇪🇪 ① | VLESS · XHTTP · Reality · 34544

Only 'remark' of ENABLED hosts is changed (matched by their inbound tag). Inbound tags,
uuids, node/squad links and disabled hosts are untouched.

    python3 fix-host-names.py                 # dry-run: backup + plan
    python3 fix-host-names.py --apply
Env: FLAG (default 🇪🇪), NODE_MARK (default ①), TOKEN_FILE, API, BACKUP_DIR
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

FLAG = os.environ.get("FLAG", "🇪🇪")
NODE_MARK = os.environ.get("NODE_MARK", "①")
TOKEN_FILE = os.environ.get("TOKEN_FILE", "/usr/local/remnawave_reverse/token")
API = os.environ.get("API", "http://127.0.0.1:3000/api").rstrip("/")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "/root/remnawave-backup")
NAMES = {  # inbound tag -> (protocol, transport, security)
    "Steal-443": ("VLESS", "TCP", "Reality"),
    "VLESS-REALITY-VISION": ("VLESS", "Vision", "Reality"),
    "VLESS-XHTTP-REALITY": ("VLESS", "XHTTP", "Reality"),
    "VLESS-XHTTP-PQ": ("VLESS", "XHTTP", "Reality PQ"),
    "VLESS-XHTTP-TLS": ("VLESS", "XHTTP", "TLS"),
    "VLESS-WS-TLS": ("VLESS", "WS", "TLS"),
    "VLESS-HTTPUPGRADE-TLS": ("VLESS", "HTTPUpgrade", "TLS"),
    "TROJAN-GRPC-TLS": ("Trojan", "gRPC", "TLS"),
    "SS-2022": ("Shadowsocks", "TCP/UDP", "2022"),
}
TOKEN = open(TOKEN_FILE).read().strip()


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    profs = call("GET", "/config-profiles")
    profs = profs.get("configProfiles", profs) if isinstance(profs, dict) else profs
    tag_by_uuid = {ib["uuid"]: ib["tag"] for p in profs for ib in p.get("inbounds", [])
                   if ib.get("uuid")}
    hosts = call("GET", "/hosts")
    hosts = hosts if isinstance(hosts, list) else hosts.get("hosts", [])

    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"hosts_names_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(path, "w") as f:
        json.dump(hosts, f, indent=2)
    os.chmod(path, 0o600)
    print(f"[+] backup: {path}")

    plan = []
    for h in hosts:
        if h.get("isDisabled"):
            continue
        tag = tag_by_uuid.get((h.get("inbound") or {}).get("configProfileInboundUuid"))
        if tag not in NAMES:
            print(f"[?] skip '{h.get('remark')}' (inbound tag: {tag})")
            continue
        proto, transport, sec = NAMES[tag]
        new = f"{FLAG}{NODE_MARK} | {proto} · {transport} · {sec} · {h.get('port')}"
        if new != h.get("remark"):
            plan.append((h, new))

    for h, new in plan:
        print(f"[+] {h.get('remark')!r}\n      -> {new!r}")
    if not plan:
        print("[=] nothing to do")
        return
    if not args.apply:
        print("[!] dry-run. Re-run with --apply")
        return
    for h, new in plan:
        call("PATCH", "/hosts", {"uuid": h["uuid"], "remark": new})
    print(f"[+] renamed: {len(plan)}")


if __name__ == "__main__":
    main()
