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
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
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
            resp = self.session.request(method, url, json=body, timeout=self.timeout)
        except requests.RequestException as e:
            LOG.error("Network: %s", e)
            raise
        if resp.status_code not in expected:
            LOG.error("%s %s → %s: %s", method, path, resp.status_code, resp.text[:600])
            raise RuntimeError(f"API {resp.status_code}: {resp.text[:400]}")
        if resp.status_code == 204 or not resp.content:
            return None
        data = resp.json()
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
            return "REPLACE_PRIVATE_KEY", "REPLACE_PUBLIC_KEY"


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


def find_profile(client: RemnawaveClient, name: str) -> Optional[Dict]:
    data = client.get("/config-profiles")
    for p in unwrap_list(data, "configProfiles", "items"):
        if p.get("name") == name:
            return p
    return None


def get_profile(client: RemnawaveClient, uuid: str) -> Dict:
    return client.get(f"/config-profiles/{uuid}")


def list_hosts(client: RemnawaveClient) -> List[Dict]:
    return unwrap_list(client.get("/hosts"), "hosts", "items")


def list_nodes(client: RemnawaveClient) -> List[Dict]:
    return unwrap_list(client.get("/nodes"), "nodes", "items")


def list_squads(client: RemnawaveClient) -> List[Dict]:
    return unwrap_list(client.get("/internal-squads"), "internalSquads", "items")


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
) -> Dict[str, Any]:
    tag = spec["tag"]
    protocol = spec["protocol"]
    port = int(spec.get("port") or 443)
    network = spec.get("network", "raw")
    if network == "tcp":
        network = "raw"
    security = spec.get("security", "none")

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
        inbound["settings"] = {"clients": [], "decryption": "none"}
    elif protocol in ("trojan", "vmess", "hysteria2"):
        inbound["settings"] = {"clients": []}
    elif protocol == "shadowsocks":
        method = spec.get("method", "2022-blake3-aes-256-gcm")
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
        # network type hysteria — minimal
        pass

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

    if existing and existing.get("settings", {}).get("clients") is not None:
        if "clients" in inbound["settings"]:
            inbound["settings"]["clients"] = existing["settings"]["clients"]

    return inbound


def default_xray_shell() -> Dict[str, Any]:
    return {
        "log": {"loglevel": "warning"},
        "dns": {
            "queryStrategy": "UseIPv4",
            "servers": [
                {"address": "https://dns.google/dns-query", "skipFallback": False}
            ],
        },
        "inbounds": [],
        "outbounds": [
            {"tag": "DIRECT", "protocol": "freedom"},
            {"tag": "BLOCK", "protocol": "blackhole"},
        ],
        "routing": {
            "rules": [
                {"ip": ["geoip:private"], "outboundTag": "BLOCK"},
                {"protocol": ["bittorrent"], "outboundTag": "BLOCK"},
            ]
        },
    }


def merge_inbounds(
    current: Dict[str, Any],
    specs: List[Dict],
    *,
    reality_private_key: str,
    reality_short_id: str,
    reality_server_name: str,
    reality_dest: str,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    cfg = copy.deepcopy(current) if current else default_xray_shell()
    if not cfg.get("outbounds"):
        cfg["outbounds"] = default_xray_shell()["outbounds"]
    if "inbounds" not in cfg or not isinstance(cfg["inbounds"], list):
        cfg["inbounds"] = []
    by_tag = {ib.get("tag"): ib for ib in cfg["inbounds"] if ib.get("tag")}

    added, skipped = [], []
    for spec in specs:
        tag = spec["tag"]
        if tag in by_tag:
            LOG.info("Inbound tag=%s already exists — keep", tag)
            skipped.append(tag)
            continue
        try:
            ib = build_inbound(
                spec,
                reality_private_key=reality_private_key,
                reality_short_id=reality_short_id,
                reality_server_name=reality_server_name,
                reality_dest=reality_dest,
                existing=None,
            )
        except Exception as e:
            LOG.warning("Skip building tag=%s: %s", tag, e)
            continue
        cfg["inbounds"].append(ib)
        added.append(tag)
        LOG.info(
            "Add inbound tag=%s port=%s protocol=%s network=%s",
            tag,
            ib.get("port"),
            ib.get("protocol"),
            ib.get("streamSettings", {}).get("network"),
        )
    return cfg, added, skipped


def push_profile(
    client: RemnawaveClient,
    *,
    uuid: Optional[str],
    name: str,
    config: Dict,
    dry_run: bool,
) -> str:
    if dry_run:
        LOG.info("[DRY-RUN] profile %s", uuid or name)
        return uuid or "dry-run-uuid"

    if uuid:
        body = {"uuid": uuid, "name": name, "config": config}
        try:
            res = client.patch("/config-profiles", body)
        except RuntimeError:
            res = client.put(f"/config-profiles/{uuid}", body)
        return (res or {}).get("uuid") or uuid

    try:
        res = client.post("/config-profiles", {"name": name, "config": config})
        new_uuid = (res or {}).get("uuid")
        if not new_uuid:
            raise RuntimeError(f"Create profile failed: {res}")
        LOG.info("Created profile uuid=%s", new_uuid)
        return new_uuid
    except RuntimeError as e:
        LOG.warning("Full profile rejected (%s) — fallback: minimal + incremental", e)

    inbounds = list(config.get("inbounds") or [])
    if not inbounds:
        raise RuntimeError("No inbounds to create")

    minimal = copy.deepcopy(config)
    minimal["inbounds"] = [inbounds[0]]
    res = client.post("/config-profiles", {"name": name, "config": minimal})
    new_uuid = (res or {}).get("uuid")
    if not new_uuid:
        raise RuntimeError(f"Even minimal profile failed: {res}")
    LOG.info("Created minimal profile uuid=%s with tag=%s", new_uuid, inbounds[0].get("tag"))

    for ib in inbounds[1:]:
        try:
            full = get_profile(client, new_uuid)
            cfg = full.get("config") or minimal
            tags = {x.get("tag") for x in (cfg.get("inbounds") or [])}
            if ib.get("tag") in tags:
                continue
            cfg = copy.deepcopy(cfg)
            cfg.setdefault("inbounds", []).append(ib)
            body = {"uuid": new_uuid, "name": name, "config": cfg}
            try:
                client.patch("/config-profiles", body)
            except RuntimeError:
                client.put(f"/config-profiles/{new_uuid}", body)
            LOG.info("Added inbound tag=%s", ib.get("tag"))
        except Exception as ex:
            LOG.warning("Could not add tag=%s: %s (continue)", ib.get("tag"), ex)

    return new_uuid


def ensure_host(
    client: RemnawaveClient,
    *,
    remark: str,
    address: str,
    port: int,
    profile_uuid: str,
    inbound_uuid: str,
    dry_run: bool,
) -> None:
    hosts = list_hosts(client)
    for h in hosts:
        inn = h.get("inbound") or {}
        if (
            h.get("remark") == remark
            or h.get("configProfileInboundUuid") == inbound_uuid
            or inn.get("configProfileInboundUuid") == inbound_uuid
        ):
            LOG.info("Host exists remark=%s — skip", remark)
            return

    body = {
        "inbound": {
            "configProfileUuid": profile_uuid,
            "configProfileInboundUuid": inbound_uuid,
        },
        "remark": remark,
        "address": address,
        "port": port if port and port > 0 else 443,
        "path": "",
        "sni": address,
        "host": "",
        "alpn": None,
        "fingerprint": "firefox",
        "isDisabled": False,
        "securityLayer": "DEFAULT",
    }
    LOG.info("Create host remark=%s %s:%s", remark, address, body["port"])
    if dry_run:
        return
    client.post("/hosts", body)


def update_squad_inbounds(
    client: RemnawaveClient,
    squad_uuid: str,
    inbound_uuids: List[str],
    dry_run: bool,
) -> None:
    squads = list_squads(client)
    squad = next((s for s in squads if s.get("uuid") == squad_uuid), None)
    if not squad:
        LOG.warning("Squad %s not found", squad_uuid)
        return
    existing = [ib.get("uuid") for ib in (squad.get("inbounds") or []) if ib.get("uuid")]
    merged = list(dict.fromkeys(existing + inbound_uuids))
    body = {"uuid": squad_uuid, "inbounds": merged}
    LOG.info("Squad %s inbounds → %d items", squad_uuid, len(merged))
    if dry_run:
        return
    client.patch("/internal-squads", body)


def activate_node_inbounds(
    client: RemnawaveClient,
    node_uuid: str,
    profile_uuid: str,
    inbound_uuids: List[str],
    dry_run: bool,
) -> None:
    # Remnawave: PATCH /api/nodes  with uuid in body (not path)
    body = {
        "uuid": node_uuid,
        "configProfile": {
            "activeConfigProfileUuid": profile_uuid,
            "activeInbounds": inbound_uuids,
        },
    }
    LOG.info("Node %s → profile %s, %d inbounds", node_uuid, profile_uuid, len(inbound_uuids))
    if dry_run:
        return
    try:
        client.patch("/nodes", body)
    except RuntimeError as e:
        LOG.warning("Node attach failed: %s", e)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(cfg: Dict[str, Any]) -> int:
    dry_run = bool(cfg.get("dry_run"))
    token = (cfg.get("panel_api_token") or "").strip()
    if not token or "REPLACE" in token or "ВАШ" in token:
        LOG.error("Заполните panel_api_token в config.yaml")
        return 1

    host_address = (cfg.get("host_address") or "").strip()
    if not host_address or host_address == "node.example.com":
        LOG.error("Заполните host_address в config.yaml")
        return 1

    client = RemnawaveClient(
        base_url=cfg.get("panel_api_url") or "http://127.0.0.1:3000/api",
        token=token,
        cookie=cfg.get("egames_cookie") or "",
        timeout=int(cfg.get("timeout") or 30),
    )

    LOG.info("=== Pre-flight ===")
    if not client.health():
        LOG.error("API недоступен: %s", cfg.get("panel_api_url"))
        return 1
    LOG.info("API OK")

    reality_sni = (cfg.get("reality_server_name") or host_address).strip()
    reality_dest = (cfg.get("reality_dest") or "/dev/shm/nginx.sock").strip()

    priv, _pub = client.generate_x25519()
    short_id = secrets.token_hex(8)
    LOG.info("Reality shortId prepared")

    profile_name = cfg.get("profile_name") or "eGames-MultiProtocol"
    LOG.info("=== Config Profile: %s ===", profile_name)
    profile = find_profile(client, profile_name)
    current_config: Dict[str, Any] = {}
    profile_uuid: Optional[str] = None

    if profile:
        profile_uuid = profile["uuid"]
        full = get_profile(client, profile_uuid)
        current_config = full.get("config") or {}
        LOG.info("Found profile uuid=%s", profile_uuid)
    else:
        LOG.info("Profile not found — will create")

    specs = cfg.get("target_inbounds") or []
    new_config, added, skipped = merge_inbounds(
        current_config,
        specs,
        reality_private_key=priv,
        reality_short_id=short_id,
        reality_server_name=reality_sni,
        reality_dest=reality_dest,
    )
    LOG.info("Added=%s Skipped=%s", added, skipped)

    profile_uuid = push_profile(
        client, uuid=profile_uuid, name=profile_name, config=new_config, dry_run=dry_run
    )

    tag_to_uuid: Dict[str, str] = {}
    port_by_tag: Dict[str, int] = {s["tag"]: int(s.get("port") or 443) for s in specs}
    if not dry_run:
        full = get_profile(client, profile_uuid)
        for ib in full.get("inbounds") or []:
            if ib.get("tag") and ib.get("uuid"):
                tag_to_uuid[ib["tag"]] = ib["uuid"]
        LOG.info("Inbound UUIDs: %s", tag_to_uuid)
    else:
        for s in specs:
            tag_to_uuid[s["tag"]] = "dry-run"

    LOG.info("=== Node ===")
    nodes = list_nodes(client)
    node_uuid = (cfg.get("node_uuid") or "").strip()
    if not node_uuid and nodes:
        for n in nodes:
            if not n.get("isDisabled"):
                node_uuid = n.get("uuid") or ""
                break
        if not node_uuid:
            node_uuid = nodes[0].get("uuid") or ""
    if node_uuid:
        LOG.info("Node uuid=%s", node_uuid)
        activate_node_inbounds(
            client, node_uuid, profile_uuid, list(tag_to_uuid.values()), dry_run
        )
    else:
        LOG.warning("Нет ноды — пропускаем привязку activeInbounds")

    LOG.info("=== Hosts ===")
    prefix = (cfg.get("host_remark_prefix") or "").strip()
    for spec in specs:
        tag = spec["tag"]
        iu = tag_to_uuid.get(tag)
        if not iu:
            LOG.warning("No UUID for tag=%s — skip host", tag)
            continue
        remark = f"{prefix} | {spec.get('remark', tag)}" if prefix else spec.get("remark", tag)
        ensure_host(
            client,
            remark=remark,
            address=host_address,
            port=port_by_tag.get(tag, 443),
            profile_uuid=profile_uuid,
            inbound_uuid=iu,
            dry_run=dry_run,
        )

    LOG.info("=== Internal Squad ===")
    squad_name = cfg.get("internal_squad_name") or "Default-Squad"
    squads = list_squads(client)
    squad = next((s for s in squads if s.get("name") == squad_name), None)
    if not squad and squads:
        squad = squads[0]
        LOG.info("Squad '%s' not found, using first: %s", squad_name, squad.get("name"))
    if squad:
        update_squad_inbounds(client, squad["uuid"], list(tag_to_uuid.values()), dry_run)
    else:
        LOG.warning("No internal squad found")

    LOG.info("=== Verify ===")
    if not dry_run:
        full = get_profile(client, profile_uuid)
        tags = [ib.get("tag") for ib in (full.get("inbounds") or [])]
        LOG.info("Profile tags: %s", tags)
        missing = [s["tag"] for s in specs if s["tag"] not in tags]
        if missing:
            LOG.warning("Missing after update: %s", missing)
        hosts = list_hosts(client)
        LOG.info("Hosts count: %d", len(hosts))
        LOG.info("OK — inbounds и hosts обработаны")
    else:
        LOG.info("[DRY-RUN] done")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Remnawave eGames Injector")
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.config)
    if not path.is_file():
        print(f"Нет файла {path}. cp config.example.yaml config.yaml", file=sys.stderr)
        return 1

    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    setup_logging(cfg.get("log_level", "INFO"))
    if args.dry_run:
        cfg["dry_run"] = True

    for env_key, cfg_key in (
        ("PANEL_API_TOKEN", "panel_api_token"),
        ("PANEL_API_URL", "panel_api_url"),
        ("EGAMES_COOKIE", "egames_cookie"),
        ("HOST_ADDRESS", "host_address"),
        ("NODE_UUID", "node_uuid"),
    ):
        if os.getenv(env_key):
            cfg[cfg_key] = os.environ[env_key]

    try:
        return run(cfg)
    except Exception as e:
        LOG.exception("Fatal: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
