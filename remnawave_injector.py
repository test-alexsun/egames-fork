#!/usr/bin/env python3
"""
Remnawave eGames Config/Hosts Injector
Полностью автоматический: всё из config.yaml.
Создаёт Config Profile (inbounds), Hosts, привязывает к Node и Squad.
"""

from __future__ import annotations

import argparse
import base64
import copy
import logging
import os
import secrets
import sys
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("pip install pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:
    print("pip install requests", file=sys.stderr)
    sys.exit(1)

LOG = logging.getLogger("remnawave_injector")


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class RemnawaveClient:
    def __init__(self, base_url: str, token: str, cookie: str = "", timeout: int = 30) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid API URL")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Remote API requires HTTPS")
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Forwarded-For": "127.0.0.1",
            "X-Forwarded-Proto": "https",
            "X-Remnawave-Client-Type": "browser",
        })
        if cookie and "=" in cookie:
            name, value = cookie.split("=", 1)
            self.session.cookies.set(name.strip(), value.strip())

    def _url(self, path: str) -> str:
        return f"{self.base}{path if path.startswith('/') else '/' + path}"

    def request(
        self,
        method: str,
        path: str,
        body: Optional[Dict] = None,
        expected: Tuple[int, ...] = (200, 201, 204),
    ) -> Any:
        url = self._url(path)
        LOG.debug("%s %s", method, url)
        try:
            resp = self.session.request(method, url, json=body, timeout=self.timeout, allow_redirects=False)
        except requests.RequestException:
            raise RuntimeError(f"API transport failure: {method} {path}") from None
        if resp.status_code not in expected:
            raise RuntimeError(f"API HTTP {resp.status_code}: {method} {path}")
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError(f"API returned invalid JSON: {method} {path}") from None
        if isinstance(data, dict) and "response" in data:
            return data["response"]
        return data

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Dict, **kw) -> Any:
        return self.request("POST", path, body=body, **kw)

    def patch(self, path: str, body: Dict, **kw) -> Any:
        return self.request("PATCH", path, body=body, **kw)

    def put(self, path: str, body: Dict, **kw) -> Any:
        return self.request("PUT", path, body=body, **kw)

    def health(self) -> bool:
        for p in ("/nodes", "/config-profiles", "/system/health"):
            try:
                self.get(p)
                return True
            except Exception:
                continue
        return False

    def generate_x25519(self) -> Tuple[str, str]:
        try:
            data = self.get("/system/tools/x25519/generate")
            kps = data.get("keypairs") or []
            if kps:
                priv = kps[0].get("privateKey") or ""
                pub = kps[0].get("publicKey") or ""
                if priv:
                    return priv, pub
        except Exception as e:
            LOG.warning("Panel keygen unavailable (%s), local fallback", e)
        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from cryptography.hazmat.primitives import serialization

            priv_obj = X25519PrivateKey.generate()
            priv_b = priv_obj.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
            pub_b = priv_obj.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            return (
                base64.urlsafe_b64encode(priv_b).decode().rstrip("="),
                base64.urlsafe_b64encode(pub_b).decode().rstrip("="),
            )
        except Exception:
            raise RuntimeError("No working X25519 generator; refusing placeholder keys") from None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def unwrap_list(data: Any, *keys: str) -> List[Dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            if k in data and isinstance(data[k], list):
                return data[k]
    return []


# ---------------------------------------------------------------------------
# Xray builders (eGames / Remnawave validator compatible)
# ---------------------------------------------------------------------------

def build_inbound(
    spec: Dict[str, Any],
    *,
    reality_private_key: str,
    reality_short_id: str,
    reality_server_name: str,
    reality_dest: str,
    existing: Optional[Dict] = None,
    tls_cert_file: str = "",
    tls_key_file: str = "",
) -> Dict[str, Any]:
    tag = spec["tag"]
    protocol = spec["protocol"]
    port = int(spec.get("port") or 443)
    network = spec.get("network", "raw")
    if network == "tcp":
        network = "raw"
    security = spec.get("security", "none")
    if protocol not in ("vless", "trojan", "shadowsocks", "hysteria"):
        raise ValueError(f"Protocol {protocol} has no supported Remnawave user/subscription adapter")
    if spec.get("flow") and network not in ("raw", "tcp"):
        raise ValueError("Vision requires RAW/TCP, not XHTTP/WS/gRPC")
    if "PQ" in tag.upper() and not spec.get("decryption"):
        raise ValueError("PQ requires actual generated ML-KEM-768 decryption")

    inbound: Dict[str, Any] = {
        "tag": tag,
        "port": port,
        "protocol": protocol,
        "settings": {},
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"],
        },
        "streamSettings": {
            "network": network,
        },
    }

    if protocol == "vless":
        inbound["settings"] = {"clients": [], "decryption": spec.get("decryption", "none")}
        if "flow" in spec:
            inbound["settings"]["flow"] = spec["flow"]
    elif protocol == "hysteria":
        inbound["settings"] = {"version": 2, "clients": []}
    elif protocol == "trojan":
        inbound["settings"] = {"clients": []}
    elif protocol == "shadowsocks":
        method = spec.get("method", "2022-blake3-aes-256-gcm")
        if method != "2022-blake3-aes-256-gcm":
            raise ValueError("Reviewed Remnawave SS2022 adapter requires AES-256-GCM (32 bytes)")
        pwd = ""
        if existing and existing.get("settings", {}).get("password"):
            pwd = existing["settings"]["password"]
        else:
            n = 16 if "128" in method else 32
            pwd = base64.b64encode(secrets.token_bytes(n)).decode()
        inbound["settings"] = {
            "method": method,
            "password": pwd,
            "network": "tcp,udp",
            "clients": [],
        }

    ss = inbound["streamSettings"]
    if security and security != "none":
        ss["security"] = security

    if network == "ws":
        ss["wsSettings"] = {
            "path": spec.get("path", f"/{tag.lower()}"),
            "headers": {},
        }
    elif network == "xhttp":
        ss["xhttpSettings"] = {
            "path": spec.get("path", f"/{tag.lower()}"),
            "mode": "auto",
            "host": "",
        }
    elif network == "grpc":
        ss["grpcSettings"] = {
            "serviceName": spec.get("service_name", tag.lower()),
            "multiMode": False,
        }
    elif network == "httpupgrade":
        ss["httpupgradeSettings"] = {
            "path": spec.get("path", f"/{tag.lower()}"),
            "host": "",
        }
    elif network == "hysteria":
        ss["hysteriaSettings"] = {"version": 2}

    if security == "reality":
        old = (existing or {}).get("streamSettings", {}).get("realitySettings") or {}
        priv = old.get("privateKey") or reality_private_key
        shorts = old.get("shortIds") or [reality_short_id]
        sni_list = old.get("serverNames") or [reality_server_name]
        dest = old.get("dest") or old.get("target") or reality_dest
        reality: Dict[str, Any] = {
            "show": False,
            "shortIds": shorts,
            "privateKey": priv,
            "serverNames": sni_list,
            "spiderX": "",
        }
        if str(dest).startswith("/"):
            reality["dest"] = dest
            reality["xver"] = 1
        else:
            reality["dest"] = dest if ":" in str(dest) else f"{dest}:443"
            reality["xver"] = 0
        ss["realitySettings"] = reality
        if old.get("privateKey"):
            LOG.info("Preserve Reality keys for tag=%s", tag)
        else:
            LOG.info("New Reality keys for tag=%s", tag)
    elif security == "tls":
        ss["tlsSettings"] = {
            "serverName": reality_server_name or "",
            "allowInsecure": False,
        }
        if tls_cert_file and tls_key_file:
            ss["tlsSettings"]["certificates"] = [
                {"certificateFile": tls_cert_file, "keyFile": tls_key_file}
            ]
        else:
            raise ValueError(f"TLS certificate/key required for {tag}")

    if existing and existing.get("settings", {}).get("clients") is not None:
        if "clients" in inbound["settings"]:
            inbound["settings"]["clients"] = existing["settings"]["clients"]

    return inbound


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(cfg: Dict[str, Any]) -> int:
    from egames_safe import run as safe_run
    return safe_run(cfg)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe eGames add-on for existing Remnawave + Node + Nginx")
    parser.add_argument("-c", "--config", default=None)
    parser.add_argument("--state-dir", default="/var/lib/egames-injector")
    modes = parser.add_mutually_exclusive_group()
    for name in ("dry-run", "check", "status", "install", "repair", "update", "backup", "restore", "uninstall"):
        modes.add_argument("--" + name, dest="mode", action="store_const", const=name)
    args = parser.parse_args()
    cfg = {}
    if args.config:
        try:
            with Path(args.config).open(encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            parser.error("Cannot read a valid YAML configuration; contents withheld")
        if not isinstance(cfg, dict):
            parser.error("Config must be a YAML mapping")
        if cfg.get("target_inbounds"):
            parser.error("Legacy target_inbounds config is unsafe; migrate using config.example.yaml")
    cfg["mode"] = args.mode or "dry-run"
    cfg["state_dir"] = args.state_dir
    if cfg.get("dry_run"):
        cfg["mode"] = "dry-run"
    for env_key, key in (("PANEL_API_TOKEN", "panel_api_token"), ("PANEL_API_URL", "panel_api_url"),
                         ("HOST_ADDRESS", "host_address"), ("NODE_UUID", "node_uuid")):
        if os.getenv(env_key):
            cfg[key] = os.environ[env_key]
    setup_logging(cfg.get("log_level", "INFO"))
    try:
        return run(cfg)
    except Exception as e:
        # Lower layers use sanitized errors; never print tracebacks containing server responses.
        LOG.error("%s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
