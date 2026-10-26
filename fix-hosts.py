#!/usr/bin/env python3
"""Fix Remnawave hosts after moving the node to eGames-MultiProtocol.

  1. host on port 443 ('Steal')  -> re-point to inbound 'Steal-443' of eGames profile
  2. hosts whose inbound is not active on any node (stale StealConfig 'XHTTP' 8443)
     and hosts without inbound (e.g. Hysteria2, removed from the profile) -> disable
     (only hosts listed in DISABLE_HOSTS; nothing is deleted)

Usage (on the VPS, as root):
    python3 fix-hosts.py            # dry-run: backup + plan
    python3 fix-hosts.py --apply
Rollback: restore from the JSON backup (hosts_*.json in BACKUP_DIR) via the panel UI/API.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

TOKEN_FILE = os.environ.get("TOKEN_FILE", "/usr/local/remnawave_reverse/token")
API = os.environ.get("API", "http://127.0.0.1:3000/api").rstrip("/")
PROFILE = os.environ.get("DST_PROFILE", "eGames-MultiProtocol")
NEW_TAG = os.environ.get("NEW_TAG", "Steal-443")
REPOINT_REMARK = os.environ.get("REPOINT_REMARK", "Steal")
DISABLE_HOSTS = [x for x in os.environ.get(
    "DISABLE_HOSTS", "XHTTP,EE-ee | 💨 Hysteria2").split(",") if x]
BACKUP_DIR = os.environ.get("BACKUP_DIR", "/root/remnawave-backup")
TOKEN = open(TOKEN_FILE).read().strip()


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Forwarded-For", "127.0.0.1")
    req.add_header("X-Forwarded-Proto", "https")
    req.add_header("X-Remnawave-Client-Type", "browser")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode() or "{}"
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} {method} {path}: {e.read().decode()[:500]}")
    d = json.loads(raw)
    return d.get("response", d) if isinstance(d, dict) else d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    profs = call("GET", "/config-profiles")
    profs = profs.get("configProfiles", profs) if isinstance(profs, dict) else profs
    prof = next((p for p in profs if p["name"] == PROFILE), None)
    if not prof:
        sys.exit(f"profile {PROFILE} not found")
    ib = next((i for i in prof.get("inbounds", []) if i.get("tag") == NEW_TAG), None)
    if not ib:
        sys.exit(f"inbound {NEW_TAG} not found in {PROFILE} (run fix-add-steal-443.py first)")

    hosts = call("GET", "/hosts")
    hosts = hosts if isinstance(hosts, list) else hosts.get("hosts", [])
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"hosts_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(path, "w") as f:
        json.dump(hosts, f, indent=2)
    os.chmod(path, 0o600)
    print(f"[+] backup: {path}")

    plan = []
    for h in hosts:
        remark = h.get("remark")
        cur = (h.get("inbound") or {}).get("configProfileInboundUuid")
        if remark == REPOINT_REMARK and cur != ib["uuid"]:
            plan.append((h, "repoint", {"uuid": h["uuid"], "inbound": {
                "configProfileUuid": prof["uuid"], "configProfileInboundUuid": ib["uuid"]}}))
        elif remark in DISABLE_HOSTS and not h.get("isDisabled"):
            plan.append((h, "disable", {"uuid": h["uuid"], "isDisabled": True}))

    if not plan:
        print("[=] nothing to do")
        return
    for h, act, _ in plan:
        print(f"[+] plan: {act:8} host '{h.get('remark')}' port {h.get('port')}")
    if not args.apply:
        print("[!] dry-run. Re-run with --apply")
        return
    for h, act, body in plan:
        call("PATCH", "/hosts", body)
        print(f"[+] done: {act} '{h.get('remark')}'")


if __name__ == "__main__":
    main()
