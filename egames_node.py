"""Node-only entry point; reuse the transactional adapter with a remote Panel."""
from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import requests
import yaml


def private_value(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise RuntimeError("Credential must be a regular private file")
    if os.name == "posix" and (p.stat().st_uid != os.geteuid() or p.stat().st_mode & 0o077):
        raise RuntimeError("Credential files must be owned by the current user with mode 0600")
    return p.read_text(encoding="utf-8").strip()


def remote_settings(containers, cfg):
    if any("remnawave/backend" in c.get("Config", {}).get("Image", "").lower() for c in containers):
        raise RuntimeError("Node-only mode requires a VPS without a local Panel")
    subscriptions = [c for c in containers if "remnawave/subscription-page" in c.get("Config", {}).get("Image", "").lower()]
    env = {}
    if len(subscriptions) == 1:
        env = dict(e.split("=", 1) for e in subscriptions[0].get("Config", {}).get("Env", []) if "=" in e)
    base = cfg.get("panel_api_url") or env.get("REMNAWAVE_PANEL_URL", "").rstrip("/")
    if base and not base.endswith("/api"):
        base += "/api"
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("Node-only mode requires the remote Panel HTTPS API URL")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError("Node-only mode requires a remote Panel hostname")
    try:
        if ipaddress.ip_address(parsed.hostname).is_loopback:
            raise RuntimeError("Node-only mode requires a remote Panel hostname")
    except ValueError:
        pass
    token = cfg.get("panel_api_token") or os.environ.get("PANEL_API_TOKEN", "")
    if not token and cfg.get("token_file"):
        token = private_value(cfg["token_file"])
    token = token or env.get("REMNAWAVE_API_TOKEN", "")
    cookie = cfg.get("panel_cookie", "")
    if not cookie and cfg.get("cookie_file"):
        cookie = private_value(cfg["cookie_file"])
    cookie = cookie or env.get("EGAMES_COOKIE", "")
    if not token or any(c in token for c in "\r\n"):
        raise RuntimeError("Remote Panel API token is required")
    if cookie and not re.fullmatch(r"[A-Za-z0-9_]+=[A-Za-z0-9_]+", cookie):
        raise RuntimeError("Unsupported Panel cookie format")
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", cfg.get("node_uuid", "")):
        raise RuntimeError("Set the explicit target node_uuid from the remote Panel")
    return {"panel_api_url": base, "panel_api_token": token, "panel_cookie": cookie}


def check_subscription(cfg):
    """Validate TLS and an existing user's Xray JSON without printing its URL/data."""
    if not cfg.get("subscription_test_url_file"):
        print("Subscription content: NOT TESTED (set subscription_test_url_file for an existing test user)")
        return
    url = private_value(cfg["subscription_test_url_file"])
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname != cfg.get("subscription_domain") or p.username or p.password or p.fragment:
        raise RuntimeError("Test subscription must use the configured subscription HTTPS hostname")
    with requests.Session() as session:
        session.trust_env = False
        try:
            response = session.get(url, headers={"User-Agent": "Xray"}, timeout=int(cfg.get("timeout", 30)), allow_redirects=False)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError("Subscription content/TLS check failed; response and URL withheld") from None
    if not isinstance(data, list):
        raise RuntimeError("Expected the subscription /json endpoint to return Xray profiles")
    expected = cfg.get("host_address")
    endpoints = [server.get("address") for item in data if isinstance(item, dict)
                 for outbound in item.get("outbounds", [])
                 for field in ("vnext", "servers")
                 for server in outbound.get("settings", {}).get(field, [])]
    if not expected or expected not in endpoints:
        raise RuntimeError("Subscription has no profile for the target Node")
    print(f"Subscription JSON/TLS: PASS ({len(data)} profiles); client traffic requires a separate test")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Additional inbounds on eGames Node + Nginx, managed by a remote Panel")
    parser.add_argument("-c", "--config", default=None)
    parser.add_argument("--state-dir", default="/var/lib/egames-node-injector")
    modes = parser.add_mutually_exclusive_group()
    for name in ("check", "dry-run", "status", "install", "repair", "update", "backup", "restore", "uninstall"):
        modes.add_argument("--" + name, dest="mode", action="store_const", const=name)
    args = parser.parse_args(argv)
    try:
        cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) if args.config else {}
        cfg = cfg or {}
        if not isinstance(cfg, dict):
            raise RuntimeError("Configuration must be a YAML mapping")
        cfg.update(deployment="node-only", mode=args.mode or "dry-run", state_dir=args.state_dir)
        for source, target in (("PANEL_API_URL", "panel_api_url"), ("PANEL_API_TOKEN", "panel_api_token"), ("NODE_UUID", "node_uuid"), ("HOST_ADDRESS", "host_address")):
            if os.environ.get(source):
                cfg[target] = os.environ[source]
        cfg.setdefault("tag_prefix", "EGADDON-" + cfg.get("node_uuid", "").split("-")[0].upper())
        from egames_safe import run
        result = run(cfg)
        if cfg["mode"] not in ("restore", "uninstall", "backup"):
            check_subscription(cfg)
        return result
    except (OSError, yaml.YAMLError):
        print("Cannot read configuration/credentials; contents withheld", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
