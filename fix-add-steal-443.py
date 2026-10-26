#!/usr/bin/env python3
"""Copy the 'Steal' (443, reality -> nginx.sock) inbound from StealConfig into
eGames-MultiProtocol, re-attach it to the node and to the internal squads.

Why: a node can have only ONE active config profile. After switching the node to
eGames-MultiProtocol, port 443 (which fronts nginx/panel/subscription page via
/dev/shm/nginx.sock) disappeared.

Usage (on the VPS, as root):
    python3 fix-add-steal-443.py            # dry-run: backup + print plan
    python3 fix-add-steal-443.py --apply    # really change the panel
"""
import argparse
import copy
import json
import os
import sys
import time
import urllib.error
import urllib.request

TOKEN_FILE = os.environ.get("TOKEN_FILE", "/usr/local/remnawave_reverse/token")
API = os.environ.get("API", "http://127.0.0.1:3000/api").rstrip("/")
SRC_PROFILE = os.environ.get("SRC_PROFILE", "StealConfig")
DST_PROFILE = os.environ.get("DST_PROFILE", "eGames-MultiProtocol")
TAG = os.environ.get("INBOUND_TAG", "Steal")
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


def profiles():
    r = call("GET", "/config-profiles")
    return r.get("configProfiles", r) if isinstance(r, dict) else r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    plist = profiles()
    src = next((p for p in plist if p["name"] == SRC_PROFILE), None)
    dst = next((p for p in plist if p["name"] == DST_PROFILE), None)
    if not src or not dst:
        sys.exit(f"profiles not found: src={bool(src)} dst={bool(dst)}")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, f"profiles_{stamp}.json")
    with open(path, "w") as f:
        json.dump(plist, f, indent=2)
    os.chmod(path, 0o600)
    print(f"[+] backup: {path}")

    src_cfg = src.get("config") or {}
    dst_cfg = dst.get("config") or {}
    steal = next((ib for ib in src_cfg.get("inbounds", []) if ib.get("tag") == TAG), None)
    if not steal:
        sys.exit(f"inbound '{TAG}' not found in {SRC_PROFILE}")
    if any(ib.get("tag") == TAG for ib in dst_cfg.get("inbounds", [])):
        print(f"[=] '{TAG}' already in {DST_PROFILE}; only re-checking attachments")
    else:
        used = {ib.get("port") for ib in dst_cfg.get("inbounds", [])}
        if steal.get("port") in used:
            sys.exit(f"port {steal.get('port')} already used in {DST_PROFILE}")
        new_cfg = copy.deepcopy(dst_cfg)
        new_cfg.setdefault("inbounds", []).append(copy.deepcopy(steal))
        print(f"[+] plan: add '{TAG}' port={steal.get('port')} to {DST_PROFILE} "
              f"({len(dst_cfg.get('inbounds', []))} -> {len(new_cfg['inbounds'])} inbounds)")
        if not args.apply:
            print("[!] dry-run. Re-run with --apply")
            return
        call("PATCH", "/config-profiles",
             {"uuid": dst["uuid"], "name": dst["name"], "config": new_cfg})
        print("[+] profile patched")

    if not args.apply:
        print("[!] dry-run, nothing else changed")
        return

    # re-read: new inbound gets its own uuid
    dst = next(p for p in profiles() if p["name"] == DST_PROFILE)
    all_uuids = [ib["uuid"] for ib in dst.get("inbounds", []) if ib.get("uuid")]
    new_uuid = next((ib["uuid"] for ib in dst.get("inbounds", []) if ib.get("tag") == TAG), None)
    if not new_uuid:
        sys.exit("new inbound uuid not found after patch")
    print(f"[+] {DST_PROFILE}: {len(all_uuids)} inbounds, '{TAG}'={new_uuid}")

    nodes = call("GET", "/nodes")
    nodes = nodes if isinstance(nodes, list) else nodes.get("nodes", [])
    for n in nodes:
        call("PATCH", "/nodes", {"uuid": n["uuid"], "configProfile": {
            "activeConfigProfileUuid": dst["uuid"], "activeInbounds": all_uuids}})
        print(f"[+] node {n.get('name')}: {len(all_uuids)} active inbounds")

    squads = call("GET", "/internal-squads")
    squads = squads if isinstance(squads, list) else squads.get("internalSquads", [])
    dst_set = set(all_uuids)
    for s in squads:
        have = [ib.get("uuid") for ib in (s.get("inbounds") or []) if ib.get("uuid")]
        if dst_set.intersection(have) and new_uuid not in have:
            call("PATCH", "/internal-squads", {"uuid": s["uuid"], "inbounds": have + [new_uuid]})
            print(f"[+] squad {s.get('name')}: +{TAG}")

    print("[!] Check Hosts in the panel: a host for port 443 must point to the "
          f"'{TAG}' inbound of {DST_PROFILE} (old host still references StealConfig).")


if __name__ == "__main__":
    main()
