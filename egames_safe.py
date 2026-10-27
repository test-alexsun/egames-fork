"""Conservative adapter for the eGames single-host Nginx layout.

The panel profile is the source of truth. No runtime config or database edits.
All subprocess arguments are arrays; diagnostics never include captured output.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import platform
from contextlib import contextmanager
from pathlib import Path

from remnawave_injector import RemnawaveClient, build_inbound, unwrap_list

OWNER = "EGAMES_ADDON"
BEGIN = "# BEGIN EGAMES_ADDON"
END = "# END EGAMES_ADDON"
REVIEWED_PANEL = {"3.4.7"}
REVIEWED_NODE = {"3.4.3"}


def command(args, data=None, check=True):
    try:
        r = subprocess.run(args, input=data, text=True, capture_output=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(f"Cannot execute {args[0]}") from None
    if check and r.returncode:
        raise RuntimeError(f"Command failed: {args[0]} (exit {r.returncode}); output withheld")
    return r


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def private_json(path, value):
    """Atomic owner-only journal/state; never briefly create a world-readable secret."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise RuntimeError("Refusing symlink state path")
    if os.name == "posix" and (path.parent.stat().st_uid != os.geteuid() or path.parent.stat().st_mode & 0o077):
        raise RuntimeError("State/backup directory must belong to current user with mode 700")
    fd, tmp = tempfile.mkstemp(prefix=".egames-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600) if hasattr(os, "fchmod") else None
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if os.name == "posix":
            parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def lock(directory):
    import fcntl
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.geteuid() or directory.stat().st_mode & 0o077:
        raise RuntimeError("State directory must be private (owner/mode 700), without symlinks")
    fd = os.open(directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def read_state(directory):
    p = Path(directory) / "state.json"
    if not p.exists():
        return {"owner": OWNER, "tags": [], "hosts": [], "paths": {}}
    if p.is_symlink() or (os.name == "posix" and (p.stat().st_mode & 0o077 or p.stat().st_uid != os.geteuid())):
        raise RuntimeError("State must be a regular owner-only file (chmod 600)")
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("owner") != OWNER:
        raise RuntimeError("Invalid state owner")
    return data


def select_one(items, description, identity=""):
    if identity:
        items = [i for i in items if identity in (i.get("Id"), i.get("Name", "").lstrip("/"), i.get("uuid"))]
    if len(items) != 1:
        raise RuntimeError(f"Ambiguous/missing {description}: {len(items)} candidates; specify its identity")
    return items[0]


def mount_source(container, path):
    matches = []
    for m in container.get("Mounts", []):
        dest = m["Destination"].rstrip("/")
        if path == dest or path.startswith(dest + "/"):
            matches.append((len(dest), str(Path(m["Source"]) / path[len(dest):].lstrip("/"))))
    if not matches:
        raise RuntimeError(f"No Docker mount exposes {path}")
    return max(matches)[1]


def shared_directory(a, b, directory):
    if mount_source(a, directory) != mount_source(b, directory):
        raise RuntimeError(f"Containers do not share {directory}")
    for c in (a, b):
        if not any(m.get("RW") and (directory == m["Destination"] or
                   directory.startswith(m["Destination"].rstrip("/") + "/")) for m in c.get("Mounts", [])):
            raise RuntimeError(f"Shared socket directory is not writable: {directory}")


def nginx_blocks(text):
    """Find top-level server blocks, ignoring braces in quoted strings/comments."""
    tokens = list(re.finditer(r'#[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]|[^\s{};]+|;', text))
    depth, start, server = 0, None, False
    blocks = []
    for t in tokens:
        v = t.group()
        if v.startswith("#"):
            continue
        if v == "server" and depth == 0:
            server = True
        elif v == "{":
            if depth == 0 and server:
                start = t.end()
            depth += 1
            server = False
        elif v == "}":
            depth -= 1
            if depth < 0:
                raise RuntimeError("Unbalanced Nginx configuration")
            if depth == 0 and start is not None:
                blocks.append((start, t.start(), text[start:t.start()]))
                start = None
    if depth:
        raise RuntimeError("Unbalanced Nginx configuration")
    return blocks


def node_server(text, domain):
    found = []
    for block in nginx_blocks(text):
        names = re.search(r"\bserver_name\s+([^;]+);", block[2])
        if names and domain in names[1].split():
            found.append(block)
    if len(found) != 1:
        raise RuntimeError("Cannot uniquely locate selfsteal server block")
    if not re.search(r"\blisten\s+unix:/dev/shm/nginx\.sock\s+ssl\s+proxy_protocol\s*;", found[0][2]):
        raise RuntimeError("Unsupported eGames HTTPS listener; expected Unix TLS + PROXY protocol")
    if not re.search(r"\broot\s+", found[0][2]) or re.search(r"\bauth_request\s+", found[0][2]):
        raise RuntimeError("Selected domain is not an unprotected selfsteal website")
    return found[0]


def managed_nginx(text):
    parts = re.findall(re.escape(BEGIN) + r".*?" + re.escape(END), text, flags=re.S)
    if len(parts) > 1 or text.count(BEGIN) != text.count(END):
        raise RuntimeError("Ambiguous managed Nginx blocks")
    return parts[0] if parts else ""


def add_routes(text, domain, routes):
    start, end, block = node_server(text, domain)
    if BEGIN in block or END in block:
        if block.count(BEGIN) != 1 or block.count(END) != 1:
            raise RuntimeError("Malformed managed Nginx markers")
        block = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", block, flags=re.S)
    # Paths are generated in our own namespace; refuse existing prefix/exact/regex collisions.
    for route in routes:
        if route["path"] in block:
            raise RuntimeError("Existing Nginx location intersects a managed path")
    if re.search(r"\blocation\s+(?:~|~\*)", block):
        raise RuntimeError("Selfsteal regex locations require manual review")
    managed = [BEGIN]
    for route in routes:
        path, port, network = route["path"], route["port"], route["network"]
        if not re.fullmatch(r"/egadd/?[a-f0-9]{24}/?", path):
            raise RuntimeError("Unsafe route path")
        managed.append(f"    location ^~ {path} {{")
        if network == "grpc":
            managed += [f"        grpc_pass grpc://127.0.0.1:{port};", "        grpc_set_header Host $host;",
                        "        grpc_read_timeout 3600s;", "        grpc_send_timeout 3600s;"]
        else:
            managed += [f"        proxy_pass http://127.0.0.1:{port};", "        proxy_http_version 1.1;",
                        "        proxy_set_header Host $host;", "        proxy_set_header X-Forwarded-Proto https;",
                        "        proxy_read_timeout 3600s;", "        proxy_send_timeout 3600s;",
                        "        proxy_buffering off;", "        proxy_request_buffering off;"]
            if network == "ws":
                managed += ["        proxy_set_header Upgrade $http_upgrade;", '        proxy_set_header Connection "upgrade";']
            else:
                managed += ['        proxy_set_header Connection "";']
        managed.append("    }")
    managed.append(END)
    new_block = block.rstrip() + "\n" + "\n".join(managed) + "\n"
    return text[:start] + new_block + text[end:]


def transports(ib):
    if ib["protocol"] == "hysteria":
        return {"udp"}
    return {"tcp", "udp"} if ib["protocol"] == "shadowsocks" else {"tcp"}


def port_entries(config):
    result = []
    for ib in config.get("inbounds", []):
        p = ib.get("port")
        if not isinstance(p, int) or not 0 < p < 65536:
            raise RuntimeError("Port ranges/socket inbounds require a dedicated adapter")
        for proto in transports(ib):
            result.append((proto, p, ib.get("tag")))
    return result


def check_ports(current, candidate, occupied):
    old = {(p, n, t) for p, n, t in port_entries(current)}
    seen = set()
    for proto, port, tag in port_entries(candidate):
        # Conservatively reject even address-specific reuse; wildcard IPv6 can overlap IPv4.
        if (proto, port) in seen:
            raise RuntimeError(f"Duplicate {proto.upper()} port {port}")
        seen.add((proto, port))
        if (proto, port, tag) not in old and (proto, port) in occupied:
            raise RuntimeError(f"Occupied {proto.upper()} port {port}")


def occupied_ports():
    result = set()
    for proto, flags in (("tcp", "-Hlnpt"), ("udp", "-Hlnpu")):
        out = command(["ss", flags]).stdout
        for line in out.splitlines():
            fields = line.split()
            if len(fields) < 5:
                raise RuntimeError("Unexpected ss output")
            match = re.search(r":(\d+)$", fields[3])
            if match:
                result.add((proto, int(match[1])))
    return result


def choose_port(occupied, used):
    for _ in range(300):
        port = 20000 + secrets.randbelow(40000)
        if port not in used and all((p, port) not in occupied for p in ("tcp", "udp")):
            used.add(port)
            return port
    raise RuntimeError("No unoccupied port found")


def pq_pair(output):
    block = output.split("Authentication: ML-KEM-768, Post-Quantum", 1)
    if len(block) != 2:
        raise RuntimeError("Installed Xray has no recognized ML-KEM-768 generator")
    d = re.search(r'"decryption"\s*:\s*"([^"\n]+)"', block[1])
    e = re.search(r'"encryption"\s*:\s*"([^"\n]+)"', block[1])
    if not d or not e or not d[1].startswith("mlkem768x25519plus."):
        raise RuntimeError("Invalid VLESS Encryption generator result")
    if len(base64.urlsafe_b64decode(d[1].split(".")[-1] + "==")) != 64:
        raise RuntimeError("Generator did not return an ML-KEM-768 seed")
    return d[1], e[1]


class Runtime:
    def __init__(self, cfg):
        ids = command(["docker", "ps", "-q"]).stdout.split()
        if not ids:
            raise RuntimeError("No running Docker containers")
        containers = json.loads(command(["docker", "inspect", *ids]).stdout)
        def image(c):
            return c.get("Config", {}).get("Image", "").lower()
        self.node = select_one([c for c in containers if "remnawave/node" in image(c)], "local Node", cfg.get("node_container", ""))
        self.nginx = select_one([c for c in containers if image(c).split(":")[0].endswith("nginx")], "Nginx", cfg.get("nginx_container", ""))
        self.panel = select_one([c for c in containers if "remnawave/backend" in image(c)], "Panel")
        for c in (self.node, self.nginx):
            if c.get("HostConfig", {}).get("NetworkMode") != "host":
                raise RuntimeError("Only local Node + Nginx with host networking is supported")
        shared_directory(self.node, self.nginx, "/dev/shm")
        self.nginx_inside = "/etc/nginx/conf.d/default.conf"
        self.nginx_path = Path(mount_source(self.nginx, self.nginx_inside))
        if self.nginx_path.is_symlink() or not self.nginx_path.is_file():
            raise RuntimeError("Nginx source must be a mounted regular file")
        self.nginx_text = self.nginx_path.read_text(encoding="utf-8")
        self.api = cfg.get("panel_api_url")
        if not self.api:
            bindings = self.panel.get("NetworkSettings", {}).get("Ports", {}).get("3000/tcp") or []
            bindings = [b for b in bindings if b["HostIp"] in ("127.0.0.1", "0.0.0.0", "")]
            if len(bindings) != 1:
                raise RuntimeError("Cannot uniquely discover the local Panel API")
            self.api = f"http://127.0.0.1:{int(bindings[0]['HostPort'])}/api"
        self.token = cfg.get("panel_api_token") or os.environ.get("PANEL_API_TOKEN", "")
        if not self.token:
            candidates = [Path(cfg.get("token_file", "/usr/local/remnawave_reverse/token"))]
            for p in candidates:
                if p.is_file() and not p.is_symlink():
                    self.token = p.read_text().strip()
                    break
        if not self.token or "REPLACE" in self.token:
            import getpass
            if not sys_stdin_tty():
                raise RuntimeError("No supported admin API token; set PANEL_API_TOKEN or token_file")
            self.token = getpass.getpass("Remnawave API token: ")
        self.xray = None
        for binary in ("/usr/local/bin/rw-core", "/usr/local/bin/xray"):
            r = command(["docker", "exec", self.node["Id"], binary, "version"], check=False)
            if r.returncode == 0 and "Xray" in r.stdout:
                self.xray, self.version = binary, r.stdout.splitlines()[0]
                break
        if not self.xray:
            raise RuntimeError("Cannot detect the actual Node Xray executable")
        command(["docker", "compose", "version"])
        if cfg.get("mode") not in ("restore", "uninstall"):
            command(["docker", "exec", self.nginx["Id"], "nginx", "-t"])

    def core(self, args, data=None, check=True):
        return command(["docker", "exec", "-i", self.node["Id"], self.xray, *args], data, check)

    def validate_xray(self, config):
        # Remnawave injects user flow from settings.flow; retain it for its validator.
        self.core(["run", "-test", "-config", "stdin:"], json.dumps(config))

    def certificate(self, domain):
        _, _, b = node_server(self.nginx_text, domain)
        cert = re.search(r'\bssl_certificate\s+"?([^";\s]+)"?;', b)
        key = re.search(r'\bssl_certificate_key\s+"?([^";\s]+)"?;', b)
        if not cert or not key:
            raise RuntimeError("Cannot discover selfsteal certificate/key")
        for p in (cert[1], key[1]):
            command(["docker", "exec", self.nginx["Id"], "test", "-r", p])
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from datetime import datetime, timezone
        cert_path = Path(mount_source(self.nginx, cert[1]))
        key_path = Path(mount_source(self.nginx, key[1]))
        c = x509.load_pem_x509_certificate(cert_path.read_bytes())
        k = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        def pub(obj):
            return obj.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if pub(c.public_key()) != pub(k.public_key()):
            raise RuntimeError("TLS certificate and private key do not match")
        now = datetime.now(timezone.utc)
        if not c.not_valid_before_utc <= now < c.not_valid_after_utc:
            raise RuntimeError("TLS certificate is not currently valid")
        names = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
        if not any(domain == n or (n.startswith("*.") and domain.split(".", 1)[-1] == n[2:]) for n in names):
            raise RuntimeError("TLS certificate does not cover the node domain")
        return cert_path, key_path

    def validate_nginx(self, candidate):
        # Replace the conf.d wildcard in the real main config, preserving other includes.
        main = command(["docker", "exec", self.nginx["Id"], "cat", "/etc/nginx/nginx.conf"]).stdout
        files = command(["docker", "exec", self.nginx["Id"], "find", "/etc/nginx/conf.d", "-maxdepth", "1", "-name", "*.conf", "-type", "f"]).stdout.splitlines()
        if self.nginx_inside not in files:
            raise RuntimeError("Cannot identify effective Nginx configuration")
        includes = []
        for p in files:
            if not re.fullmatch(r"/etc/nginx/conf.d/[A-Za-z0-9_.-]+\.conf", p):
                raise RuntimeError("Unsupported Nginx include path")
            includes.append(candidate if p == self.nginx_inside else f"include {p};")
        pattern = r"\binclude\s+/etc/nginx/conf\.d/\*\.conf\s*;"
        if len(re.findall(pattern, main)) != 1:
            raise RuntimeError("Unsupported Nginx main include structure")
        main = re.sub(pattern, lambda _: "\n".join(includes), main)
        command(["docker", "exec", "-i", self.nginx["Id"], "nginx", "-t", "-p", "/etc/nginx/", "-c", "/dev/stdin"], main)

    def write_nginx(self, text):
        # A file bind mount pins its inode: os.replace would leave the container on OLD content.
        fd = os.open(self.nginx_path, os.O_WRONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.truncate()
            f.flush()
            os.fsync(f.fileno())

    def reload(self):
        command(["docker", "exec", self.nginx["Id"], "nginx", "-t"])
        command(["docker", "exec", self.nginx["Id"], "nginx", "-s", "reload"])


def sys_stdin_tty():
    import sys
    return sys.stdin.isatty()


def check_platform(release):
    if (release.get("ID"), release.get("VERSION_ID")) not in {
        ("debian", "12"), ("debian", "13"), ("ubuntu", "24.04")
    }:
        raise RuntimeError("Supported OS: Debian 12/13 or Ubuntu 24.04")


def active_ids(node):
    return [i if isinstance(i, str) else i["uuid"] for i in node["configProfile"]["activeInbounds"]]


def profile_patch(profile, config):
    return {"uuid": profile["uuid"], "name": profile["name"], "config": config}


def host_body(spec, profile_uuid, inbound_uuid, domain, node_uuid):
    frontend = spec.get("frontend", False)
    return {"inbound": {"configProfileUuid": profile_uuid, "configProfileInboundUuid": inbound_uuid},
            "remark": f"eGames | {spec['tag']}", "address": domain,
            "port": 443 if frontend else spec["port"], "sni": domain, "host": domain if frontend else "",
            "path": spec.get("service_name", "") if spec["network"] == "grpc" else spec.get("path", "") if spec["network"] in ("ws", "xhttp") else "",
            "fingerprint": "chrome", "alpn": "h2" if spec["network"] == "grpc" else None,
            "securityLayer": "TLS" if frontend else "DEFAULT", "isDisabled": False,
            "nodes": [node_uuid], "tags": [OWNER]}


def plan(client, rt, cfg, state, occupied):
    meta = client.get("/system/metadata")
    version = meta.get("version", "").lstrip("v")
    if version not in REVIEWED_PANEL:
        raise RuntimeError(f"Panel {version or 'unknown'} has no reviewed adapter; supported: {sorted(REVIEWED_PANEL)}")
    nodes = unwrap_list(client.get("/nodes"), "nodes")
    node = select_one([n for n in nodes if not n.get("isDisabled")], "Panel node", cfg.get("node_uuid", ""))
    if not node.get("isConnected") or not (node.get("versions") or {}).get("node"):
        raise RuntimeError("Node is disconnected or does not report its version")
    if node["versions"]["node"].lstrip("v") not in REVIEWED_NODE:
        raise RuntimeError(f"Node version has no reviewed adapter; supported: {sorted(REVIEWED_NODE)}")
    reported = node["versions"].get("xray", "").lstrip("v")
    match = re.search(r"Xray\s+(\d+\.\d+\.\d+)", rt.version)
    if not match or reported != match[1]:
        raise RuntimeError("Panel-reported core differs from the validated local Xray executable")
    if state.get("profile_uuid", node["configProfile"]["activeConfigProfileUuid"]) != node["configProfile"]["activeConfigProfileUuid"]:
        raise RuntimeError("Active profile changed since installation; refusing state migration")
    # Make sure the selected panel node actually points to this VPS.
    addr = node.get("address", "")
    local = {"127.0.0.1", "localhost", "::1"}
    for line in json.loads(command(["ip", "-j", "address", "show"]).stdout):
        local.update(a["local"] for a in line.get("addr_info", []))
    try:
        addresses = {a[4][0] for a in socket.getaddrinfo(addr, None)}
    except OSError:
        raise RuntimeError("Cannot resolve selected Node management address") from None
    if not addresses.intersection(local):
        raise RuntimeError("Selected Panel node does not refer to this VPS")
    if node.get("activePluginUuid"):
        raise RuntimeError("Node plugins need a dedicated validation adapter")
    pid = node["configProfile"]["activeConfigProfileUuid"]
    if any(n["uuid"] != node["uuid"] and n.get("configProfile", {}).get("activeConfigProfileUuid") == pid for n in nodes):
        raise RuntimeError("Active profile is shared by other nodes; refusing global changes")
    profile = client.get(f"/config-profiles/{pid}")
    current = profile.get("config")
    if not isinstance(current, dict) or current.get("snippets"):
        raise RuntimeError("Profile must be a JSON object without generated snippets")
    if any(i.get("settings", {}).get("clients") for i in current.get("inbounds", [])
           if i.get("protocol") in ("vless", "trojan", "shadowsocks", "hysteria")):
        raise RuntimeError("Profile contains manual clients that Panel PATCH would clear; refusing changes")
    old443 = [i for i in current.get("inbounds", []) if i.get("port") == 443 and i.get("protocol") == "vless"
              and i.get("streamSettings", {}).get("security") == "reality"]
    if len(old443) != 1:
        raise RuntimeError("Expected one existing VLESS REALITY TCP 443 listener")
    reality = old443[0]["streamSettings"]["realitySettings"]
    if reality.get("dest", reality.get("target")) != "/dev/shm/nginx.sock" or reality.get("xver") != 1:
        raise RuntimeError("Unsupported REALITY selfsteal target/PROXY protocol")
    domain = cfg.get("host_address") or reality.get("serverNames", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", domain) or "." not in domain:
        raise RuntimeError("Cannot discover a valid node DNS name")
    cert, key = rt.certificate(domain)
    managed = managed_nginx(rt.nginx_text)
    if managed and managed != state.get("nginx_managed"):
        raise RuntimeError("Unowned/externally modified Nginx routes; refusing to overwrite")
    hosts = unwrap_list(client.get("/hosts"), "hosts")
    squads = unwrap_list(client.get("/internal-squads"), "internalSquads")
    old443id = next((i["uuid"] for i in profile["inbounds"] if i["tag"] == old443[0]["tag"]), None)
    if not old443id or old443id not in active_ids(node):
        raise RuntimeError("Existing 443 inbound is not active on the selected node")
    target_squads = [s for s in squads if old443id in [i["uuid"] for i in s.get("inbounds", [])]]
    if not target_squads:
        raise RuntimeError("No Internal Squad authorizes the existing 443 inbound")
    tags = {i["tag"]: i for i in current["inbounds"]}
    all_profiles = unwrap_list(client.get("/config-profiles"), "configProfiles")
    global_tags = {i["tag"] for p in all_profiles if p["uuid"] != pid for i in p.get("inbounds", [])}
    used = {port for _, port, _ in port_entries(current)}
    specs, routes, diagnostics = [], [], ["VMess skipped: no managed users/Hosts/subscription adapter in Panel 3.4.7",
        "SS2022 AES-128 skipped: Panel adapter supports AES-256-GCM; using a 32-byte server key",
        "VLESS REALITY Vision: reusing existing TCP 443; user UUIDs and flow are managed by Panel"]
    desired = copy.deepcopy(current)
    definitions = [("WS", "vless", "ws", "none", True), ("XHTTP", "vless", "xhttp", "none", True),
                   ("GRPC", "trojan", "grpc", "none", True), ("XREALITY", "vless", "xhttp", "reality", False),
                   ("PQ", "vless", "raw", "reality", False), ("SS2022", "shadowsocks", "raw", "none", False),
                   ("HY2", "hysteria", "hysteria", "tls", False)]
    for label, proto, net, security, frontend in definitions:
        tag = f"EGADDON-{label}"
        old = tags.get(tag)
        if tag in global_tags or (old and tag not in state.get("tags", [])):
            raise RuntimeError(f"Unowned inbound tag conflict: {tag}")
        if label == "HY2":
            # Native support exists, but certificate visibility must be proven inside the Node.
            try:
                for path in (cert, key):
                    inside = next((str(Path(m['Destination']) / str(path.relative_to(Path(m['Source']))))
                                   for m in rt.node.get("Mounts", []) if path.is_relative_to(Path(m["Source"]))), "")
                    if not inside:
                        raise RuntimeError("TLS certificate/key not mounted into Node")
                    command(["docker", "exec", rt.node["Id"], "test", "-r", inside])
            except RuntimeError as e:
                if old:
                    raise
                diagnostics.append(f"Hysteria2 skipped: {e}; native protocol=hysteria/version=2 needs readable Node TLS files")
                continue
        path = state.get("paths", {}).get(tag) or (f"/egadd{secrets.token_hex(12)}/" if net == "grpc" else f"/egadd/{secrets.token_hex(12)}/")
        port = old.get("port") if old else (443 if label == "HY2" else choose_port(occupied, used))
        if label == "HY2" and ("udp", 443) in occupied and not old:
            diagnostics.append("Hysteria2 skipped: UDP 443 already occupied (QUIC/HTTP3 or another service)")
            continue
        spec = {"tag": tag, "protocol": proto, "network": net, "security": security, "port": port,
                "path": path, "service_name": path.strip("/"), "frontend": frontend}
        if old:
            ib = copy.deepcopy(old)
            if state.get("inbounds", {}).get(tag) != ib:
                raise RuntimeError(f"Managed inbound drift: {tag}; refusing to overwrite external changes")
        else:
            if label == "PQ":
                try:
                    spec["decryption"], _ = pq_pair(rt.core(["vlessenc"]).stdout)
                    spec["flow"] = ""  # no Vision + PQ transport assumptions
                except RuntimeError:
                    diagnostics.append("PQ skipped: installed core has no validated ML-KEM-768 generator")
                    continue
            tls_cert = tls_key = ""
            if label == "HY2":
                tls_cert, tls_key = [next(str(Path(m["Destination"]) / str(p.relative_to(Path(m["Source"]))))
                    for m in rt.node["Mounts"] if p.is_relative_to(Path(m["Source"]))) for p in (cert, key)]
            ib = build_inbound(spec, reality_private_key=reality["privateKey"],
                reality_short_id=reality["shortIds"][0], reality_server_name=domain,
                reality_dest="/dev/shm/nginx.sock", tls_cert_file=tls_cert, tls_key_file=tls_key)
            if frontend:
                ib["listen"] = "127.0.0.1"
            try:
                probe = copy.deepcopy(current)
                probe["inbounds"].append(ib)
                rt.validate_xray(probe)
            except RuntimeError:
                diagnostics.append(f"{tag} skipped: installed Xray rejects the proposed configuration")
                continue
            desired["inbounds"].append(ib)
        specs.append(spec)
        if frontend:
            routes.append({"path": path, "port": port, "network": net})
    check_ports(current, desired, occupied)
    rt.validate_xray(desired)
    nginx = add_routes(rt.nginx_text, domain, routes)
    rt.validate_nginx(nginx)
    if old443[0] != next(i for i in desired["inbounds"] if i["tag"] == old443[0]["tag"]):
        raise RuntimeError("Original 443 listener was modified")
    return {"profile": profile, "node": node, "squads": target_squads, "hosts": hosts,
            "config": desired, "specs": specs, "nginx": nginx, "domain": domain,
            "diagnostics": diagnostics, "panel_version": version}


def project(value, shape):
    """Compare only writable fields, never timestamps or response-only metadata."""
    if isinstance(shape, dict):
        return {k: project(value.get(k), v) for k, v in shape.items()} if isinstance(value, dict) else value
    return value


def same_operation_value(op, value, expected):
    actual = copy.deepcopy(project(value, expected))
    target = copy.deepcopy(expected)
    # Membership order has no meaning; ORM relation reads may reorder UUIDs.
    for item in (actual, target):
        if isinstance(item, dict) and op["kind"] == "node":
            item["configProfile"]["activeInbounds"].sort()
        elif isinstance(item, dict) and op["kind"] == "squad":
            item["inbounds"].sort()
    return actual == target


def writable_node(node):
    return {"uuid": node["uuid"], "configProfile": {
        "activeConfigProfileUuid": node["configProfile"]["activeConfigProfileUuid"],
        "activeInbounds": active_ids(node)}}


def writable_squad(squad):
    return {"uuid": squad["uuid"], "inbounds": [i["uuid"] for i in squad.get("inbounds", [])]}


def current_object(client, op):
    if op["kind"] == "profile":
        p = client.get(f"/config-profiles/{op['after']['uuid']}")
        return profile_patch(p, p["config"])
    path, key = {"node": ("/nodes", "nodes"), "squad": ("/internal-squads", "internalSquads"),
                 "host": ("/hosts", "hosts")}[op["kind"]]
    values = unwrap_list(client.get(path), key)
    if op["kind"] == "host" and op["method"] == "POST":
        values = [h for h in values if OWNER in h.get("tags", []) and
                  h.get("inbound") == op["after"]["inbound"]]
        if not values:
            return None
        if len(values) != 1:
            raise RuntimeError("Ambiguous created Host during recovery")
        return values[0]
    val = next((v for v in values if v["uuid"] == op["after"]["uuid"]), None)
    if val is None:
        raise RuntimeError("API object disappeared during transaction")
    if op["kind"] == "node":
        return writable_node(val)
    if op["kind"] == "squad":
        return writable_squad(val)
    return val


def firewall_status():
    if not shutil.which("ufw"):
        return None
    result = command(["ufw", "status"]).stdout
    if "Status: inactive" in result:
        return None
    if "Status: active" not in result:
        raise RuntimeError("Cannot determine UFW state")
    return result


def ufw_has_rule(text, rule):
    return bool(re.search(r"(?m)^" + re.escape(rule) + r"(?:\s|$).*\bALLOW\b", text))


class Transaction:
    def __init__(self, client, rt, directory, state):
        self.client, self.rt = client, rt
        self.directory = Path(directory)
        self.path = self.directory / "journal.json"
        self.data = {"owner": OWNER, "status": "pending", "operations": [], "old_state": state,
                     "nginx_path": str(rt.nginx_path), "node_container": rt.node["Id"],
                     "nginx_container": rt.nginx["Id"]}

    def save(self):
        private_json(self.path, self.data)

    def api(self, kind, path, before, after, method="PATCH"):
        if before == after:
            return
        op = {"kind": kind, "path": path, "method": method, "before": before, "after": after}
        self.data["operations"].append(op)
        self.save()  # write intent before any side effect, including an uncertain HTTP result
        self.client.request(method, path, after)
        actual = current_object(self.client, op)
        if not same_operation_value(op, actual, after):
            raise RuntimeError("API read-back differs from submitted change")
        op["done"] = True
        self.save()

    def nginx(self, before, after):
        if before == after:
            return
        self.data["operations"].append({"kind": "nginx", "before": before, "after": after})
        self.save()
        self.rt.write_nginx(after)
        self.rt.reload()
        self.data["operations"][-1]["done"] = True
        self.save()

    def firewall(self, specs):
        status = firewall_status()
        if status is None:
            return
        for spec in specs:
            if spec["frontend"]:
                continue
            for proto in transports({"protocol": spec["protocol"]}):
                rule = f"{spec['port']}/{proto}"
                if ufw_has_rule(status, rule):
                    continue
                self.data["operations"].append({"kind": "ufw", "rule": rule})
                self.save()
                command(["ufw", "allow", rule, "comment", OWNER])
                if not ufw_has_rule(firewall_status() or "", rule):
                    raise RuntimeError("UFW rule creation not confirmed")
                self.data["operations"][-1]["done"] = True
                self.save()
                status = firewall_status() or ""
    def rollback(self):
        errors = []
        for op in reversed(self.data["operations"]):
            try:
                if op["kind"] == "ufw":
                    status = firewall_status()
                    if status is None:
                        raise RuntimeError("UFW state changed during rollback")
                    lines = [line for line in status.splitlines() if re.match(re.escape(op["rule"]) + r"\s", line)]
                    if not lines:
                        continue
                    if not all(OWNER in line for line in lines):
                        raise RuntimeError("Firewall ownership changed; refusing rule deletion")
                    command(["ufw", "--force", "delete", "allow", op["rule"], "comment", OWNER])
                    if ufw_has_rule(firewall_status() or "", op["rule"]):
                        raise RuntimeError("UFW rollback not confirmed")
                elif op["kind"] == "nginx":
                    actual = self.rt.nginx_path.read_text(encoding="utf-8")
                    if actual == op["before"]:
                        continue
                    if actual != op["after"]:
                        raise RuntimeError("Nginx drift blocks automatic rollback")
                    self.rt.validate_nginx(op["before"])
                    self.rt.write_nginx(op["before"])
                    self.rt.reload()
                else:
                    actual = current_object(self.client, op)
                    if op["method"] == "POST":
                        if actual is None:
                            continue
                        if not same_operation_value(op, actual, op["after"]):
                            raise RuntimeError("Created Host changed externally; not removing it")
                        self.client.request("DELETE", f"/hosts/{actual['uuid']}")
                        if current_object(self.client, op) is not None:
                            raise RuntimeError("Host deletion not confirmed")
                    else:
                        if same_operation_value(op, actual, op["before"]):
                            continue
                        if not same_operation_value(op, actual, op["after"]):
                            raise RuntimeError("API object drift blocks automatic rollback")
                        self.client.patch(op["path"], op["before"])
                        if not same_operation_value(op, current_object(self.client, op), op["before"]):
                            raise RuntimeError("API rollback read-back failed")
                op["rolled_back"] = True
                self.save()
            except Exception:
                errors.append(op["kind"])
                # Later dependent rollback steps can remove live inbounds. Stop at first failure.
                break
        self.data["status"] = "rollback_incomplete" if errors else "rolled_back"
        self.save()
        if errors:
            raise RuntimeError(f"Rollback INCOMPLETE at {errors[0]}; preserve journal.json and inspect manually")
        private_json(self.directory / "state.json", self.data["old_state"])


def bind_hosts_and_node(tx, p, state):
    client = tx.client
    full = client.get(f"/config-profiles/{p['profile']['uuid']}")
    tag_ids = {i["tag"]: i["uuid"] for i in full["inbounds"]}
    managed_ids = []
    for spec in p["specs"]:
        if spec["tag"] not in tag_ids:
            raise RuntimeError("Missing managed inbound UUID after profile update")
        iid = tag_ids[spec["tag"]]
        managed_ids.append(iid)
        body = host_body(spec, full["uuid"], iid, p["domain"], p["node"]["uuid"])
        saved_id = state.get("host_ids", {}).get(spec["tag"])
        matches = [h for h in p["hosts"] if h.get("uuid") == saved_id] if saved_id else [
            h for h in p["hosts"] if h.get("inbound") == body["inbound"]]
        if len(matches) > 1:
            raise RuntimeError("Duplicate Hosts for managed endpoint; refusing automatic ownership")
        if matches:
            h = matches[0]
            if OWNER not in h.get("tags", []) or h["uuid"] not in state.get("hosts", []):
                raise RuntimeError("Unowned Host uses a managed inbound; review required")
            before = project(h, body)
            tx.api("host", "/hosts", {"uuid": h["uuid"], **before}, {"uuid": h["uuid"], **body})
        else:
            tx.api("host", "/hosts", None, body, "POST")
    for squad in p["squads"]:
        before = writable_squad(squad)
        after = {**before, "inbounds": list(dict.fromkeys(before["inbounds"] + managed_ids))}
        tx.api("squad", "/internal-squads", before, after)
    before = writable_node(p["node"])
    after = copy.deepcopy(before)
    after["configProfile"]["activeInbounds"] = list(dict.fromkeys(active_ids(p["node"]) + managed_ids))
    tx.api("node", "/nodes", before, after)


def verify(client, rt, p):
    # Poll boundedly for panel-driven Node sync, then require its local listeners.
    for _ in range(15):
        nodes = unwrap_list(client.get("/nodes"), "nodes")
        node = next(n for n in nodes if n["uuid"] == p["node"]["uuid"])
        occupied = occupied_ports()
        expected = {(proto, spec["port"]) for spec in p["specs"] for proto in
                    ({"udp"} if spec["protocol"] == "hysteria" else
                     {"tcp", "udp"} if spec["protocol"] == "shadowsocks" else {"tcp"})}
        if node.get("isConnected") and expected.issubset(occupied):
            break
        time.sleep(2)
    else:
        raise RuntimeError("Node did not synchronize/start every expected listener")
    command(["docker", "exec", rt.nginx["Id"], "nginx", "-t"])
    if ("tcp", 443) not in occupied:
        raise RuntimeError("Original TCP 443 listener disappeared")
    return node


def apply(client, rt, p, directory, state):
    if shutil.disk_usage(directory).free < 20 * 1024 * 1024:
        raise RuntimeError("Not enough free space for backups/journal")
    # Recheck before the first write: do not lose a concurrent panel edit.
    latest = client.get(f"/config-profiles/{p['profile']['uuid']}")
    if latest["config"] != p["profile"]["config"] or rt.nginx_path.read_text(encoding="utf-8") != rt.nginx_text:
        raise RuntimeError("Configuration changed since planning")
    check_ports(p["profile"]["config"], p["config"], occupied_ports())
    tx = Transaction(client, rt, directory, state)
    tx.save()
    backup_path = Path(directory) / "backups" / f"{time.time_ns()}.json"
    private_json(backup_path, {"owner": OWNER, "profile": p["profile"], "node": p["node"],
                              "hosts": p["hosts"], "squads": p["squads"], "nginx": rt.nginx_text})
    try:
        tx.api("profile", "/config-profiles", profile_patch(p["profile"], p["profile"]["config"]),
               profile_patch(p["profile"], p["config"]))
        tx.nginx(rt.nginx_text, p["nginx"])
        tx.firewall(p["specs"])
        bind_hosts_and_node(tx, p, state)
        verify(client, rt, p)
        hosts = unwrap_list(client.get("/hosts"), "hosts")
        tags = [s["tag"] for s in p["specs"]]
        history_path = Path(directory) / "transactions" / f"{time.time_ns()}.json"
        inbound_tags = {i["uuid"]: i["tag"] for i in client.get(f"/config-profiles/{p['profile']['uuid']}")["inbounds"]}
        new_state = {"owner": OWNER, "profile_uuid": p["profile"]["uuid"], "node_uuid": p["node"]["uuid"],
            "history": state.get("history", []) + [str(history_path)],
            "nginx_managed": managed_nginx(p["nginx"]),
            "host_ids": {inbound_tags[h["inbound"]["configProfileInboundUuid"]]: h["uuid"] for h in hosts
                         if OWNER in h.get("tags", []) and h.get("inbound", {}).get("configProfileInboundUuid") in inbound_tags},
            "tags": tags, "hosts": [h["uuid"] for h in hosts if OWNER in h.get("tags", []) and
                                    h.get("inbound", {}).get("configProfileUuid") == p["profile"]["uuid"]],
            "paths": {s["tag"]: s["path"] for s in p["specs"]},
            "inbounds": {i["tag"]: i for i in p["config"]["inbounds"] if i["tag"] in tags},
            "last_backup": str(backup_path)}
        private_json(Path(directory) / "state.json", new_state)
        tx.data["status"] = "committed"
        tx.save()
        private_json(history_path, tx.data)
    except BaseException:
        tx.rollback()
        raise


def recover(client, rt, directory, path=None):
    path = Path(path) if path else Path(directory) / "journal.json"
    if not path.resolve().is_relative_to(Path(directory).resolve()):
        raise RuntimeError("Recovery path outside installer state")
    if not path.is_file() or path.is_symlink() or (os.name == "posix" and path.stat().st_mode & 0o077):
        raise RuntimeError("Missing/private journal required for restore")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("owner") != OWNER or data.get("nginx_path") != str(rt.nginx_path) or data.get("node_container") != rt.node["Id"]:
        raise RuntimeError("Recovery journal does not match this installation")
    tx = Transaction(client, rt, directory, data["old_state"])
    tx.data = data
    tx.rollback()
    print("Rollback confirmed by API/file read-back. Original node/profile identity preserved.")


def run(cfg):
    if os.name != "posix":
        raise RuntimeError("Installer requires Linux; portable mock tests can run on Windows")
    check_platform(platform.freedesktop_os_release())
    mode = cfg.get("mode", "dry-run")
    if mode not in ("dry-run", "check", "status") and os.geteuid() != 0:
        raise RuntimeError("Mutating modes require root")
    directory = Path(cfg.get("state_dir", "/var/lib/egames-injector"))
    rt = Runtime(cfg)
    client = RemnawaveClient(rt.api, rt.token, timeout=int(cfg.get("timeout", 30)))
    if mode in ("restore", "uninstall"):
        with lock(directory):
            if mode == "restore":
                recover(client, rt, directory)
            else:
                state = read_state(directory)
                for path in reversed(state.get("history", [])):
                    recover(client, rt, directory, path)
                print("Managed additions removed through recorded transactions; original components retained.")
        return 0
    state = read_state(directory)
    if (directory / "journal.json").exists():
        journal = json.loads((directory / "journal.json").read_text(encoding="utf-8"))
        if journal["status"] not in ("committed", "rolled_back"):
            raise RuntimeError("An unfinished transaction exists; run --restore before further changes")
    p = plan(client, rt, cfg, state, occupied_ports())
    print(f"Panel {p['panel_version']}; Node {p['node']['versions']['node']}; {rt.version}")
    print(f"Active profile: {p['profile']['name']}; public endpoint: {p['domain']}:443")
    for d in p["diagnostics"]:
        print(d)
    print("TAG | public port | local port | transport")
    for s in p["specs"]:
        print(f"{s['tag']} | {443 if s['frontend'] else s['port']} | {s['port']} | {s['network']}")
    if mode in ("dry-run", "check", "status"):
        print("Read-only plan complete. Xray and Nginx validators passed; no client connection tested.")
        return 0
    if mode == "backup":
        with lock(directory):
            path = directory / "backups" / f"manual-{time.time_ns()}.json"
            private_json(path, {"owner": OWNER, "profile": p["profile"], "hosts": p["hosts"],
                               "node": p["node"], "squads": p["squads"], "nginx": rt.nginx_text})
            print(f"Private backup: {path}")
        return 0
    with lock(directory):
        # Lock also covers reading state and constructing the final plan.
        if (directory / "journal.json").exists():
            status = json.loads((directory / "journal.json").read_text(encoding="utf-8"))["status"]
            if status not in ("committed", "rolled_back"):
                raise RuntimeError("An unfinished transaction exists; run --restore")
        state = read_state(directory)
        p = plan(client, rt, cfg, state, occupied_ports())
        print("Final locked plan (public ports may differ from the preview):")
        for spec in p["specs"]:
            print(f"{spec['tag']}: {443 if spec['frontend'] else spec['port']}")
        apply(client, rt, p, directory, state)
    print("Applied and read back; Node connected, local listeners present, Nginx reloaded.")
    print("Remote client traffic and subscription content still require an end-to-end client check.")
    print("Active UFW received only missing public rules. Other firewall/provider rules need a separate check.")
    return 0
