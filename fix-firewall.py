#!/usr/bin/env python3
"""Open in ufw every port used by the inbounds of the eGames profile.

Remnawave inbounds listen on non-standard ports; ufw (default INPUT DROP) blocks them,
so from the outside only 22/443/8443 work. Shadowsocks also needs UDP.
ufw is never enabled or reset by this script; if it is not active, nothing is changed.

    python3 fix-firewall.py            # dry-run: print the plan
    python3 fix-firewall.py --apply
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

TOKEN_FILE = os.environ.get("TOKEN_FILE", "/usr/local/remnawave_reverse/token")
API = os.environ.get("API", "http://127.0.0.1:3000/api").rstrip("/")
PROFILE = os.environ.get("PROFILE", "eGames-MultiProtocol")
TOKEN = open(TOKEN_FILE).read().strip()


def get_profile():
    req = urllib.request.Request(API + "/config-profiles")
    for k, v in {"Authorization": f"Bearer {TOKEN}", "X-Forwarded-For": "127.0.0.1",
                 "X-Forwarded-Proto": "https", "X-Remnawave-Client-Type": "browser"}.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:300]}")
    d = d.get("response", d)
    d = d.get("configProfiles", d) if isinstance(d, dict) else d
    return next((p for p in d if p["name"] == PROFILE), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    prof = get_profile()
    if not prof:
        sys.exit(f"profile {PROFILE} not found")
    rules = []
    for ib in prof["config"].get("inbounds", []):
        port = ib.get("port")
        if not isinstance(port, int):
            continue
        rules.append((f"{port}/tcp", ib["tag"]))
        if ib.get("protocol") == "shadowsocks":
            rules.append((f"{port}/udp", ib["tag"]))
    if not shutil.which("ufw"):
        print("[=] ufw not installed: nothing to do (check the provider's firewall instead)")
        return
    status = subprocess.run(["ufw", "status"], capture_output=True, text=True).stdout
    if "inactive" in status.lower():
        print("[=] ufw is inactive: nothing to do (check the provider's firewall instead)")
        return
    for rule, tag in rules:
        print(f"[+] ufw allow {rule}   # {tag}")
        if a.apply:
            subprocess.run(["ufw", "allow", rule, "comment", f"xray {tag}"], check=False,
                           capture_output=True)
    if not a.apply:
        print("[!] dry-run. Re-run with --apply")
    else:
        print("[+] done. Also check the VPS provider's own firewall (panel of the hoster).")


if __name__ == "__main__":
    main()
