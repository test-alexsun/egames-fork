#!/usr/bin/env python3
"""
Remnawave (eGames) Config Profile + Hosts Injector
Idempotent automation script per technical specification.

- Reads / merges Config Profile JSON (inbounds) via REST API only
- Creates / updates Hosts bound to inbounds
- Attaches profile & inbounds to Node and Internal Squad
- Never overwrites existing Reality privateKey / shortIds
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:
    print("requests required: pip install requests", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG = logging.getLogger("remnawave_injector")


def setup_logging(level: str = "INFO") -> None:
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class RemnawaveClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        cookie: str = "",
        timeout: int = 30,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            }
        )
        if cookie:
            # EGAMES_COOKIE format: name=value
            if "=" in cookie:
                name, value = cookie.split("=", 1)
                self.session.cookies.set(name.strip(), value.strip())
            else:
                LOG.warning("egames_cookie does not look like name=value, ignoring")

    def _url(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        return f"{self.base}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict] = None,
        params: Optional[Dict] = None,
        expected: Tuple[int, ...] = (200, 201, 204),
    ) -> Any:
        url = self._url(path)
        LOG.debug("%s %s body=%s", method.upper(), url, json_body)
        try:
            resp = self.session.request(
                method,
                url,
                json=json_body,
                params=params,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            LOG.error("Network error: %s", exc)
            raise

        if resp.status_code not in expected:
            LOG.error(
                "API %s %s → %s: %s",
                method.upper(),
                path,
                resp.status_code,
                resp.text[:800],
            )
            raise RuntimeError(f"API error {resp.status_code}: {resp.text[:400]}")

        if resp.status_code == 204 or not resp.content:
            return None
        try:
            data = resp.json()
        except Exception:
            return resp.text

        # Remnawave often wraps payload in {"response": ...}
        if isinstance(data, dict) and "response" in data:
            return data["response"]
        return data

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Dict, **kw) -> Any:
        return self.request("POST", path, json_body=body, **kw)

    def patch(self, path: str, body: Dict, **kw) -> Any:
        return self.request("PATCH", path, json_body=body, **kw)

    def put(self, path: str, body: Dict, **kw) -> Any:
        return self.request("PUT", path, json_body=body, **kw)

    def health(self) -> bool:
        try:
            # Several possible health endpoints across versions
            for p in ("/system/health", "/health", "/nodes"):
                try:
                    self.get(p, expected=(200, 201))
                    return True
                except Exception:
                    continue
            return False
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Reality key helpers (only for NEW inbounds)
# ---------------------------------------------------------------------------

def generate_reality_keys() -> Tuple[str, str]:
    """Generate X25519 private/public key pair for REALITY (best-effort)."""
    try:
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        import base64

        priv = X25519PrivateKey.generate()
        priv_bytes = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_bytes = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        # Xray uses URL-safe base64 without padding
        private_b64 = base64.urlsafe_b64encode(priv_bytes).decode().rstrip("=")
        public_b64 = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")
        return private_b64, public_b64
    except Exception as exc:
        LOG.warning("cryptography not available (%s), using placeholder Reality keys", exc)
        # Fallback placeholders — operator should replace via panel UI
        return "REPLACE_PRIVATE_KEY", "REPLACE_PUBLIC_KEY"


def random_short_id() -> str:
    return secrets.token_hex(8)


# ---------------------------------------------------------------------------
# Inbound builders (Xray-core compatible)
# ---------------------------------------------------------------------------

def build_inbound(spec: Dict[str, Any], existing: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Build a full Xray inbound object from schema entry.
    If `existing` is provided, preserve Reality keys and clients.
    """
    tag = spec["tag"]
    protocol = spec["protocol"]
    port = int(spec.get("port", 0))
    network = spec.get("network", "tcp")
    security = spec.get("security", "none")

    inbound: Dict[str, Any] = {
        "tag": tag,
        "listen": "0.0.0.0",
        "port": port,
        "protocol": protocol,
        "settings": {},
        "streamSettings": {
            "network": network,
            "security": security if security != "none" else "none",
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"],
        },
    }

    # ----- protocol settings -----
    if protocol == "vless":
        inbound["settings"] = {
            "clients": [],
            "decryption": "none",
        }
        flow = spec.get("flow")
        if flow:
            # flow is per-client; keep empty clients, panel manages users
            pass
    elif protocol == "trojan":
        inbound["settings"] = {"clients": []}
    elif protocol == "vmess":
        inbound["settings"] = {"clients": []}
    elif protocol == "shadowsocks":
        method = spec.get("method", "2022-blake3-aes-128-gcm")
        # Panel injects users; password left empty for 2022 methods that use key
        inbound["settings"] = {
            "method": method,
            "password": "",
            "network": "tcp,udp",
        }
    elif protocol == "hysteria2":
        inbound["settings"] = {
            "clients": [],
        }

    # ----- streamSettings -----
    ss = inbound["streamSettings"]

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
    elif network == "tcp" and security == "reality":
        ss["tcpSettings"] = {
            "header": {"type": "none"},
        }

    if security == "reality":
        # Preserve keys from existing inbound if present
        existing_reality = {}
        if existing:
            existing_reality = (
                existing.get("streamSettings", {}).get("realitySettings") or {}
            )

        private_key = existing_reality.get("privateKey")
        short_ids = existing_reality.get("shortIds")
        public_key = None
        if not private_key or private_key.startswith("REPLACE_"):
            private_key, public_key = generate_reality_keys()
            short_ids = [random_short_id()]
            LOG.info("Generated new Reality keys for inbound tag=%s", tag)
        else:
            LOG.info("Preserving existing Reality keys for inbound tag=%s", tag)

        ss["realitySettings"] = {
            "show": False,
            "dest": "www.cloudflare.com:443",
            "xver": 0,
            "serverNames": ["www.cloudflare.com", "cloudflare.com"],
            "privateKey": private_key,
            "shortIds": short_ids or [random_short_id()],
        }
        if public_key:
            # publicKey is not always stored in inbound; useful for hosts
            ss["realitySettings"]["_publicKey"] = public_key

    elif security == "tls":
        # Certificates are usually managed by the node / reverse-proxy.
        # Leave empty so panel / node can inject.
        ss["tlsSettings"] = {
            "serverName": "",
            "allowInsecure": False,
            "alpn": ["h2", "http/1.1"],
        }

    # Prefer existing clients / settings if inbound already exists
    if existing:
        if "settings" in existing and existing["settings"].get("clients") is not None:
            inbound["settings"]["clients"] = existing["settings"]["clients"]
        # Keep any extra fields that panel may have added
        for k in ("sniffing",):
            if k in existing:
                inbound[k] = existing[k]

    return inbound


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_profile(client: RemnawaveClient, name: str, uuid: Optional[str] = None) -> Optional[Dict]:
    data = client.get("/config-profiles")
    profiles = data.get("configProfiles") if isinstance(data, dict) else data
    if not isinstance(profiles, list):
        # some versions return list directly
        profiles = data if isinstance(data, list) else []

    if uuid:
        for p in profiles:
            if p.get("uuid") == uuid:
                return p
        return None

    for p in profiles:
        if p.get("name") == name:
            return p
    return None


def get_full_profile(client: RemnawaveClient, uuid: str) -> Dict:
    return client.get(f"/config-profiles/{uuid}")


def merge_inbounds(
    current_config: Dict[str, Any],
    target_specs: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """
    Idempotent merge of target inbounds into existing Xray config.
    Returns (new_config, added_tags, skipped_tags).
    """
    cfg = copy.deepcopy(current_config) if current_config else {}
    inbounds: List[Dict] = list(cfg.get("inbounds") or [])
    by_tag = {ib.get("tag"): ib for ib in inbounds if ib.get("tag")}

    added: List[str] = []
    skipped: List[str] = []

    for spec in target_specs:
        tag = spec["tag"]
        if tag in by_tag:
            LOG.info("Inbound already exists (tag=%s) — keeping current definition", tag)
            skipped.append(tag)
            # Optional warning if port differs
            existing_port = by_tag[tag].get("port")
            wanted_port = spec.get("port")
            if wanted_port is not None and existing_port != wanted_port:
                LOG.warning(
                    "Port mismatch for tag=%s: existing=%s wanted=%s (left unchanged)",
                    tag,
                    existing_port,
                    wanted_port,
                )
            continue

        new_ib = build_inbound(spec, existing=None)
        inbounds.append(new_ib)
        by_tag[tag] = new_ib
        added.append(tag)
        LOG.info("Will add inbound tag=%s port=%s protocol=%s", tag, new_ib.get("port"), new_ib.get("protocol"))

    cfg["inbounds"] = inbounds

    # Minimal defaults if profile was empty
    if "log" not in cfg:
        cfg["log"] = {"loglevel": "warning"}
    if "routing" not in cfg:
        cfg["routing"] = {"domainStrategy": "AsIs", "rules": []}

    return cfg, added, skipped


def update_profile(client: RemnawaveClient, uuid: str, name: str, config: Dict, dry_run: bool) -> Dict:
    body = {
        "uuid": uuid,
        "name": name,
        "config": config,
    }
    if dry_run:
        LOG.info("[DRY-RUN] Would PATCH config-profile %s", uuid)
        return {"uuid": uuid, "name": name}
    # Prefer PATCH; some versions accept PUT
    try:
        return client.patch("/config-profiles", body)
    except RuntimeError:
        LOG.warning("PATCH failed, trying PUT /config-profiles/{uuid}")
        return client.put(f"/config-profiles/{uuid}", body)


def create_profile(client: RemnawaveClient, name: str, config: Dict, dry_run: bool) -> Dict:
    body = {"name": name, "config": config}
    if dry_run:
        LOG.info("[DRY-RUN] Would create config-profile name=%s", name)
        return {"uuid": "dry-run-uuid", "name": name}
    return client.post("/config-profiles", body)


def list_hosts(client: RemnawaveClient) -> List[Dict]:
    data = client.get("/hosts")
    if isinstance(data, dict):
        return data.get("hosts") or data.get("items") or []
    return data if isinstance(data, list) else []


def ensure_host(
    client: RemnawaveClient,
    *,
    remark: str,
    address: str,
    port: int,
    profile_uuid: str,
    inbound_uuid: str,
    node_uuids: List[str],
    dry_run: bool,
) -> Optional[Dict]:
    hosts = list_hosts(client)
    existing = None
    for h in hosts:
        if h.get("remark") == remark or h.get("configProfileInboundUuid") == inbound_uuid:
            existing = h
            break

    payload = {
        "remark": remark,
        "address": address,
        "port": port if port and port > 0 else 443,
        "configProfileUuid": profile_uuid,
        "configProfileInboundUuid": inbound_uuid,
        "nodes": node_uuids,
        "isDisabled": False,
    }

    if existing:
        LOG.info("Host already exists remark=%s — updating if needed", remark)
        if dry_run:
            return existing
        try:
            return client.patch(f"/hosts/{existing['uuid']}", payload)
        except Exception as exc:
            LOG.warning("Host update failed: %s", exc)
            return existing

    LOG.info("Creating host remark=%s address=%s:%s", remark, address, payload["port"])
    if dry_run:
        return None
    return client.post("/hosts", payload)


def list_nodes(client: RemnawaveClient) -> List[Dict]:
    data = client.get("/nodes")
    if isinstance(data, dict):
        return data.get("nodes") or data.get("items") or []
    return data if isinstance(data, list) else []


def list_internal_squads(client: RemnawaveClient) -> List[Dict]:
    data = client.get("/internal-squads")
    if isinstance(data, dict):
        return data.get("internalSquads") or data.get("items") or []
    return data if isinstance(data, list) else []


def attach_inbounds_to_squad(
    client: RemnawaveClient,
    squad_uuid: str,
    inbound_uuids: List[str],
    dry_run: bool,
) -> None:
    if not inbound_uuids:
        return
    # Typical payload: add inbounds to squad
    body = {"inboundUuids": inbound_uuids}
    if dry_run:
        LOG.info("[DRY-RUN] Would attach %d inbounds to squad %s", len(inbound_uuids), squad_uuid)
        return
    try:
        client.patch(f"/internal-squads/{squad_uuid}", body)
        LOG.info("Attached inbounds to internal squad %s", squad_uuid)
    except Exception as exc:
        # Alternative endpoint shapes across versions
        try:
            client.post(f"/internal-squads/{squad_uuid}/inbounds", {"uuids": inbound_uuids})
            LOG.info("Attached inbounds (POST) to squad %s", squad_uuid)
        except Exception as exc2:
            LOG.warning("Could not attach inbounds to squad: %s / %s", exc, exp2 if (exp2 := exc2) else "")


def run(cfg: Dict[str, Any]) -> int:
    dry_run = bool(cfg.get("dry_run", False))
    client = RemnawaveClient(
        base_url=cfg["panel_api_url"],
        token=cfg["panel_api_token"],
        cookie=cfg.get("egames_cookie") or "",
        timeout=int(cfg.get("timeout", 30)),
    )

    LOG.info("=== Pre-flight check ===")
    if not client.health():
        LOG.error("Panel API is not reachable at %s", cfg["panel_api_url"])
        return 1
    LOG.info("API reachable")

    profile_name = cfg.get("profile_name", "eGames-MultiProtocol")
    profile_uuid = cfg.get("profile_uuid") or None

    LOG.info("=== Fetch Config Profile ===")
    profile = find_profile(client, profile_name, profile_uuid)
    if profile:
        LOG.info("Found profile name=%s uuid=%s", profile.get("name"), profile.get("uuid"))
        full = get_full_profile(client, profile["uuid"])
        current_config = full.get("config") or {}
        profile_uuid = profile["uuid"]
    else:
        LOG.info("Profile '%s' not found — will create", profile_name)
        current_config = {}
        profile_uuid = None

    LOG.info("=== Schema merge ===")
    target_specs = cfg.get("target_inbounds") or []
    new_config, added, skipped = merge_inbounds(current_config, target_specs)
    LOG.info("Added: %s | Skipped (already present): %s", added, skipped)

    LOG.info("=== Push Profile ===")
    if profile_uuid:
        result = update_profile(client, profile_uuid, profile_name, new_config, dry_run)
    else:
        result = create_profile(client, profile_name, new_config, dry_run)
        profile_uuid = result.get("uuid") if isinstance(result, dict) else None

    if not profile_uuid:
        LOG.error("No profile UUID after create/update")
        return 1

    # Re-fetch to obtain inbound UUIDs assigned by panel
    if not dry_run:
        full = get_full_profile(client, profile_uuid)
        profile_uuid = full.get("uuid", profile_uuid)
        inbounds_meta = full.get("inbounds") or []
    else:
        inbounds_meta = []

    # Map tag → inbound uuid
    tag_to_uuid: Dict[str, str] = {}
    for ib in inbounds_meta:
        t = ib.get("tag")
        u = ib.get("uuid")
        if t and u:
            tag_to_uuid[t] = u

    LOG.info("=== Resolve Node ===")
    nodes = list_nodes(client)
    node_uuid = cfg.get("node_uuid") or ""
    if not node_uuid and nodes:
        # Prefer first online / enabled node
        for n in nodes:
            if n.get("isConnected") or n.get("isNodeOnline") or not n.get("isDisabled"):
                node_uuid = n.get("uuid")
                break
        if not node_uuid:
            node_uuid = nodes[0].get("uuid")
    if node_uuid:
        LOG.info("Using node uuid=%s", node_uuid)
    else:
        LOG.warning("No node UUID resolved — hosts will be created without node binding")

    node_list = [node_uuid] if node_uuid else []

    LOG.info("=== Sync Hosts ===")
    host_address = cfg.get("host_address") or "127.0.0.1"
    prefix = cfg.get("host_remark_prefix") or ""

    for spec in target_specs:
        tag = spec["tag"]
        remark = f"{prefix} | {spec.get('remark', tag)}" if prefix else spec.get("remark", tag)
        inbound_uuid = tag_to_uuid.get(tag)
        if not inbound_uuid and not dry_run:
            LOG.warning("No inbound UUID for tag=%s — skip host", tag)
            continue
        ensure_host(
            client,
            remark=remark,
            address=host_address,
            port=int(spec.get("port") or 443),
            profile_uuid=profile_uuid,
            inbound_uuid=inbound_uuid or "dry-run",
            node_uuids=node_list,
            dry_run=dry_run,
        )

    LOG.info("=== Internal Squad ===")
    squad_name = cfg.get("internal_squad_name") or "Default-Squad"
    squads = list_internal_squads(client)
    squad = next((s for s in squads if s.get("name") == squad_name), None)
    if squad:
        inbound_uuids = list(tag_to_uuid.values())
        attach_inbounds_to_squad(client, squad["uuid"], inbound_uuids, dry_run)
    else:
        LOG.warning("Internal squad '%s' not found — skip attach", squad_name)

    LOG.info("=== Verification ===")
    if not dry_run:
        final = get_full_profile(client, profile_uuid)
        final_tags = [ib.get("tag") for ib in (final.get("inbounds") or [])]
        LOG.info("Profile inbounds tags: %s", final_tags)
        missing = [s["tag"] for s in target_specs if s["tag"] not in final_tags]
        if missing:
            LOG.warning("Still missing tags after update: %s", missing)
        else:
            LOG.info("All target inbounds present in profile")
    else:
        LOG.info("[DRY-RUN] Verification skipped")

    LOG.info("Done.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remnawave eGames Config/Hosts Injector (idempotent)"
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Override config dry_run=true",
    )
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        example = Path("config.example.yaml")
        if example.is_file():
            LOG.error("Config not found: %s  (copy from %s)", cfg_path, example)
        else:
            LOG.error("Config not found: %s", cfg_path)
        return 1

    cfg = load_config(cfg_path)
    setup_logging(cfg.get("log_level", "INFO"))

    if args.dry_run:
        cfg["dry_run"] = True

    # Env overrides (useful for CI / secrets)
    if os.getenv("PANEL_API_TOKEN"):
        cfg["panel_api_token"] = os.environ["PANEL_API_TOKEN"]
    if os.getenv("PANEL_API_URL"):
        cfg["panel_api_url"] = os.environ["PANEL_API_URL"]
    if os.getenv("EGAMES_COOKIE"):
        cfg["egames_cookie"] = os.environ["EGAMES_COOKIE"]
    if os.getenv("HOST_ADDRESS"):
        cfg["host_address"] = os.environ["HOST_ADDRESS"]

    try:
        return run(cfg)
    except Exception as exc:
        LOG.exception("Fatal: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
