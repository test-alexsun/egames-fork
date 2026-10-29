import copy
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import egames_safe as s
from remnawave_injector import RemnawaveClient, build_inbound

FIXTURES = Path(__file__).parent / "fixtures"


class API:
    def __init__(self):
        data = json.loads((FIXTURES / "egames.json").read_text())
        self.__dict__.update(data)
        self.writes = []
        self.version = "3.4.7"
        self.fail = None
        self.lose_reply = False
        self.plugins = {}

    def get(self, path):
        if path == '/subscription-templates':
            return []
        if path.startswith("/node-plugins/"):
            return copy.deepcopy(self.plugins.get(path.split("/")[-1].split("?")[0], {}))
        if path == "/system/metadata":
            return {"version": self.version}
        if path == "/nodes":
            return copy.deepcopy(self.nodes)
        if path == "/hosts":
            return copy.deepcopy(self.hosts)
        if path == "/internal-squads":
            return copy.deepcopy(self.squads)
        if path == "/config-profiles":
            return {"configProfiles": [copy.deepcopy(self.profile)]}
        if path.startswith("/config-profiles/"):
            return copy.deepcopy(self.profile)
        raise AssertionError(path)

    def patch(self, path, body):
        return self.request("PATCH", path, body)

    def request(self, method, path, body=None):
        self.writes.append((method, path, copy.deepcopy(body)))
        if self.fail == path:
            self.fail = None
            raise RuntimeError("API HTTP 500")
        if path == "/config-profiles":
            known = {i["tag"]: i["uuid"] for i in self.profile["inbounds"]}
            self.profile.update(copy.deepcopy(body))
            self.profile["inbounds"] = [{"tag": i["tag"], "uuid": known.get(i["tag"], "iid-" + i["tag"])}
                                        for i in body["config"]["inbounds"]]
        elif path == "/nodes":
            n = next(n for n in self.nodes if n["uuid"] == body["uuid"])
            n["configProfile"] = copy.deepcopy(body["configProfile"])
        elif path == "/internal-squads":
            q = next(q for q in self.squads if q["uuid"] == body["uuid"])
            q["inbounds"] = [{"uuid": i} for i in body["inbounds"]]
        elif path == "/hosts" and method == "POST":
            self.hosts.append({**copy.deepcopy(body), "uuid": "host-" + str(len(self.hosts))})
        elif path == "/hosts" and method == "PATCH":
            next(h for h in self.hosts if h["uuid"] == body["uuid"]).update(copy.deepcopy(body))
        elif path.startswith("/hosts/") and method == "DELETE":
            self.hosts = [h for h in self.hosts if h["uuid"] != path.split("/")[-1]]
        else:
            raise AssertionError((method, path))
        if self.lose_reply:
            self.lose_reply = False
            raise RuntimeError("API timeout after server accepted request")
        if path == '/hosts' and method == 'POST':
            return copy.deepcopy(self.hosts[-1])


class Runtime:
    def __init__(self, directory):
        self.nginx_path = Path(directory) / "nginx.conf"
        self.nginx_text = (FIXTURES / "nginx.conf").read_text()
        self.nginx_path.write_text(self.nginx_text)
        self.node = {"Id": "local-node", "Mounts": []}
        self.version = "Xray 26.10.21 synthetic"
        self.nginx = {"Id": "local-nginx"}
        self.validations = []

    def certificate(self, domain):
        s.node_server(self.nginx_text, domain)
        return Path("/etc/ssl/fullchain.pem"), Path("/etc/ssl/privkey.pem")

    def core(self, args):
        seed = s.base64.urlsafe_b64encode(b"x" * 64).decode().rstrip("=")
        return types.SimpleNamespace(stdout='Authentication: ML-KEM-768, Post-Quantum\n"decryption": "mlkem768x25519plus.native.600s.' + seed + '"\n"encryption": "client-value"')

    def validate_xray(self, config):
        self.validations.append(copy.deepcopy(config))

    def validate_nginx(self, config):
        s.nginx_blocks(config)

    def verify_mounted_file(self, inside, path):
        pass

    def core_pids(self):
        return {123}

    def write_nginx(self, config):
        self.nginx_path.write_text(config)

    def reload(self):
        pass


class SafeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api = API()
        self.rt = Runtime(self.tmp.name)
        self.state = {"owner": s.OWNER, "tags": [], "hosts": [], "paths": {}}
        self.cmd = patch.object(s, "command", side_effect=lambda args, *a, **kw:
            types.SimpleNamespace(stdout="Status: inactive\n" if args[:2] == ["ufw", "status"] else "[]",
                                  returncode=0))
        self.cmd.start()
        self.addCleanup(self.cmd.stop)
        self.geo = patch.object(s, "lookup_country_code", return_value="FI")
        self.lookup_country = self.geo.start()
        self.addCleanup(self.geo.stop)

    def plan(self, occupied=None):
        return s.plan(self.api, self.rt, {}, self.state, occupied or {("tcp", 443)})

    def apply(self, plan):
        with patch.object(s, "verify"), patch.object(s, "occupied_ports", return_value={("tcp", 443)}), \
                patch.object(s.Transaction, "firewall"):
            s.apply(self.api, self.rt, plan, self.tmp.name, self.state)

    def test_dry_run_has_no_writes(self):
        before = sorted(Path(self.tmp.name).rglob("*"))
        original = copy.deepcopy(self.api.__dict__)
        self.plan()
        self.assertEqual(self.api.__dict__, original)
        self.assertEqual(sorted(Path(self.tmp.name).rglob("*")), before)

    def test_fixture_is_independent_of_runner_ufw_installation(self):
        with patch.object(s.shutil, 'which', return_value='/usr/sbin/ufw'):
            self.assertIsNone(s.firewall_status())
            self.plan()
        self.assertEqual(self.api.writes, [])

    def test_country_host_names_cover_all_eight_protocols(self):
        expected = {
            "Steal": "VLESS | TCP REALITY Vision",
            "EGADDON-WS": "VLESS | WS TLS",
            "EGADDON-XHTTP": "VLESS | XHTTP TLS",
            "EGADDON-GRPC": "Trojan | gRPC TLS",
            "EGADDON-XREALITY": "VLESS | XHTTP REALITY",
            "EGADDON-PQ": "VLESS | TCP REALITY ML-KEM768",
            "EGADDON-SS2022": "Shadowsocks | 2022 AES-256-GCM",
            "EGADDON-HY2": "Hysteria2 | QUIC TLS",
        }
        for tag, label in expected.items():
            self.assertEqual(s.host_remark(tag, "fi"), "\U0001f1eb\U0001f1ee | " + label)
        self.assertEqual(s.host_remark("Steal", "DE"), "\U0001f1e9\U0001f1ea | VLESS | TCP REALITY Vision")
        for code in ("XX", "ZZ", "Finland", "", None, 12):
            with self.subTest(code=code), self.assertRaisesRegex(RuntimeError, "ISO 3166"):
                s.country_code(code)

    def test_explicit_country_avoids_geoip_and_invalid_country_has_no_writes(self):
        p = s.plan(self.api, self.rt, {"host_country_code": " de "}, self.state, {("tcp", 443)})
        self.assertEqual(p["country_code"], "DE")
        self.lookup_country.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "ISO 3166"):
            s.plan(self.api, self.rt, {"host_country_code": "ZZ"}, self.state, {("tcp", 443)})
        self.assertEqual(self.api.writes, [])

    def test_country_rename_preserves_original_host_fields_and_repeats_without_writes(self):
        old = copy.deepcopy(self.api.hosts[0])
        self.apply(self.plan())
        current = self.api.hosts[0]
        self.assertEqual(current, {**old, "remark": s.host_remark("STEAL", "FI")})
        self.assertTrue(all(h["remark"].startswith("\U0001f1eb\U0001f1ee | ") for h in self.api.hosts))
        self.state = s.read_state(self.tmp.name)
        self.rt.nginx_text = self.rt.nginx_path.read_text()
        names = {h["uuid"]: h["remark"] for h in self.api.hosts}
        self.api.writes.clear()
        self.apply(self.plan())
        self.assertEqual({h["uuid"]: h["remark"] for h in self.api.hosts}, names)
        self.assertEqual(self.api.writes, [])

    def test_repeat_preserves_operator_exclusions_from_existing_squad(self):
        self.apply(self.plan())
        self.state = s.read_state(self.tmp.name)
        self.rt.nginx_text = self.rt.nginx_path.read_text()
        squad = self.api.squads[0]
        squad['inbounds'] = squad['inbounds'][:2]
        chosen = copy.deepcopy(squad['inbounds'])
        self.api.writes.clear()
        self.apply(self.plan())
        self.assertEqual(squad['inbounds'], chosen)
        self.assertFalse(any(path == '/internal-squads' for _, path, _ in self.api.writes))

    def test_repeat_preserves_operator_disabled_managed_host(self):
        self.apply(self.plan())
        self.state = s.read_state(self.tmp.name)
        self.rt.nginx_text = self.rt.nginx_path.read_text()
        host = self.api.hosts[1]
        host['isDisabled'] = True
        self.api.writes.clear()
        self.apply(self.plan())
        self.assertTrue(host['isDisabled'])
        self.assertFalse(any(path == '/hosts' and body.get('uuid') == host['uuid']
                             for _, path, body in self.api.writes))

    def test_country_rename_does_not_touch_original_host_on_other_address(self):
        self.api.hosts[0]["address"] = "other.example.com"
        old = copy.deepcopy(self.api.hosts[0])
        self.apply(self.plan())
        self.assertEqual(self.api.hosts[0], old)

    def test_country_rename_detects_concurrent_original_host_edit(self):
        p = self.plan()
        self.api.hosts[0]["remark"] = "Changed in Panel"
        with self.assertRaisesRegex(RuntimeError, "Concurrent binding"):
            self.apply(p)
        self.assertEqual(self.api.hosts[0]["remark"], "Changed in Panel")

    def native_plugin(self):
        uuid = "11111111-1111-4111-8111-111111111111"
        self.api.nodes[0]["activePluginUuid"] = uuid
        self.rt.node["HostConfig"] = {"CapAdd": ["NET_ADMIN"]}
        self.api.plugins[uuid] = {"uuid": uuid, "pluginConfig": {
            "torrentBlocker": {"enabled": True, "blockDuration": 3600, "ignoreLists": {"ip": []}},
            "ingressFilter": {"enabled": True, "blockedIps": ["192.0.2.0/24"]}}}
        return uuid

    def test_native_plugin_is_preserved_without_plugin_writes(self):
        uuid = self.native_plugin()
        original = copy.deepcopy(self.api.plugins)
        p = self.plan()
        self.apply(p)
        self.assertEqual(self.api.plugins, original)
        self.assertEqual(self.api.nodes[0]["activePluginUuid"], uuid)
        self.assertFalse(any("node-plugins" in path for _, path, _ in self.api.writes))

    def test_plugin_hooks_and_shared_lists_are_rejected(self):
        uuid = self.native_plugin()
        self.api.plugins[uuid]["pluginConfig"]["preStart"] = {"enabled": True, "script": "unsafe"}
        with self.assertRaisesRegex(RuntimeError, "hooks/unknown"):
            self.plan()
        del self.api.plugins[uuid]["pluginConfig"]["preStart"]
        self.api.plugins[uuid]["pluginConfig"]["ingressFilter"]["blockedIps"] = ["@dynamic-list"]
        with self.assertRaisesRegex(RuntimeError, "resolver adapter"):
            self.plan()
        self.assertEqual(self.api.writes, [])

    def test_plugin_drift_fails_before_profile_write(self):
        uuid = self.native_plugin()
        p = self.plan()
        self.api.plugins[uuid]["pluginConfig"]["torrentBlocker"]["enabled"] = False
        with self.assertRaisesRegex(RuntimeError, "changed during"):
            s.apply(self.api, self.rt, p, self.tmp.name, self.state)
        self.assertEqual(self.api.writes, [])

    def test_plugin_added_after_planning_fails_before_profile_write(self):
        p = self.plan()
        self.native_plugin()
        with self.assertRaisesRegex(RuntimeError, "changed during"):
            s.apply(self.api, self.rt, p, self.tmp.name, self.state)
        self.assertEqual(self.api.writes, [])

    def test_plugin_binding_removed_and_non_object_response_fail_closed(self):
        uuid = self.native_plugin()
        p = self.plan()
        self.api.nodes[0]["activePluginUuid"] = None
        with self.assertRaisesRegex(RuntimeError, "changed during"):
            s.verify_plugin(self.api, self.rt, p)
        self.api.nodes[0]["activePluginUuid"] = uuid
        self.api.plugins[uuid] = None
        with self.assertRaisesRegex(RuntimeError, "Cannot read"):
            self.plan()

    def test_missing_plugin_or_net_admin_fails_closed(self):
        uuid = self.native_plugin()
        self.rt.node["HostConfig"]["CapAdd"] = []
        with self.assertRaisesRegex(RuntimeError, "NET_ADMIN"):
            self.plan()
        self.rt.node["HostConfig"]["CapAdd"] = ["NET_ADMIN"]
        del self.api.plugins[uuid]
        with self.assertRaisesRegex(RuntimeError, "Cannot read"):
            self.plan()

    def test_preserves_all_original_sections_and_443(self):
        p = self.plan()
        for key in ("outbounds", "routing", "dns", "policy"):
            self.assertEqual(p["config"][key], self.api.profile["config"][key])
        self.assertEqual(p["config"]["inbounds"][0], self.api.profile["config"]["inbounds"][0])

    def test_tls_frontends_are_local_and_hosts_use_443(self):
        p = self.plan()
        for spec in p["specs"]:
            if spec["frontend"]:
                ib = next(i for i in p["config"]["inbounds"] if i["tag"] == spec["tag"])
                self.assertEqual(ib["listen"], "127.0.0.1")
                self.assertNotEqual(ib["streamSettings"].get("security"), "tls")
                host = s.host_body(spec, "pid", "iid", p["domain"], "nid", p["country_code"])
                self.assertEqual((host["port"], host["securityLayer"]), (443, "TLS"))
                self.assertEqual(host["path"], spec["service_name"] if spec["network"] == "grpc" else spec["path"])

    def test_pq_has_real_seed_and_no_vision(self):
        p = self.plan()
        ib = next(i for i in p["config"]["inbounds"] if i["tag"] == "Vless-Reality -tcp")
        self.assertTrue(ib["settings"]["decryption"].startswith("mlkem768x25519plus."))
        self.assertEqual(ib["settings"]["flow"], "")
        self.assertEqual(ib["streamSettings"]["network"], "raw")

    def test_missing_pq_generator_does_not_create_fake_pq(self):
        self.rt.core = Mock(side_effect=RuntimeError("no vlessenc"))
        p = self.plan()
        self.assertNotIn("Vless-Reality -tcp", [i["tag"] for i in p["config"]["inbounds"]])

    def test_vmess_and_missing_hy2_mount_reported(self):
        p = self.plan()
        self.assertTrue(any("VMess skipped" in d for d in p["diagnostics"]))
        self.assertTrue(any("Hysteria2 skipped" in d and "not mounted" in d for d in p["diagnostics"]))

    def test_hy2_version_2_and_udp443(self):
        self.rt.node["Mounts"] = [{"Source": "/etc/ssl", "Destination": "/tls"}]
        p = self.plan()
        ib = next(i for i in p["config"]["inbounds"] if i["tag"] == "Hysteria2-QUIC -udp")
        self.assertEqual(ib["settings"]["version"], 2)
        self.assertEqual(ib["streamSettings"]["hysteriaSettings"]["version"], 2)
        self.assertEqual(ib["port"], 443)

    def test_hy2_udp_conflict_does_not_touch_tcp443(self):
        self.rt.node["Mounts"] = [{"Source": "/etc/ssl", "Destination": "/tls"}]
        p = self.plan({("tcp", 443), ("udp", 443)})
        self.assertNotIn("Hysteria2-QUIC -udp", [i["tag"] for i in p["config"]["inbounds"]])
        self.assertEqual(p["config"]["inbounds"][0]["port"], 443)

    def test_unknown_panel_fails_closed(self):
        self.api.version = "9.0.0"
        with self.assertRaisesRegex(RuntimeError, "reviewed adapter"):
            self.plan()

    def test_unknown_node_fails_closed(self):
        self.api.nodes[0]["versions"]["node"] = "9.0.0"
        with self.assertRaisesRegex(RuntimeError, "reviewed adapter"):
            self.plan()

    def test_supported_operating_systems(self):
        for distro, version in (("debian", "12"), ("debian", "13"), ("ubuntu", "24.04")):
            s.check_platform({"ID": distro, "VERSION_ID": version})
        with self.assertRaises(RuntimeError):
            s.check_platform({"ID": "unknown", "VERSION_ID": "1"})

    def test_ambiguous_node_fails_closed(self):
        self.api.nodes.append(copy.deepcopy(self.api.nodes[0]))
        with self.assertRaisesRegex(RuntimeError, "Ambiguous"):
            self.plan()

    def test_missing_certificate_fails_before_api_writes(self):
        self.rt.certificate = Mock(side_effect=RuntimeError("missing certificate"))
        with self.assertRaisesRegex(RuntimeError, "certificate"):
            self.plan()
        self.assertFalse(self.api.writes)

    def test_mount_mapping_and_missing_mount(self):
        c = {"Mounts": [{"Type": "volume", "Source": "/volume", "Destination": "/tls"}]}
        self.assertEqual(Path(s.mount_source(c, "/tls/cert.pem")), Path("/volume/cert.pem"))
        with self.assertRaisesRegex(RuntimeError, "No Docker mount"):
            s.mount_source(c, "/elsewhere/key.pem")

    def test_reject_different_socket_mounts(self):
        a = {"Mounts": [{"Source": "/one", "Destination": "/dev/shm", "RW": True}]}
        b = {"Mounts": [{"Source": "/two", "Destination": "/dev/shm", "RW": True}]}
        with self.assertRaisesRegex(RuntimeError, "do not share"):
            s.shared_directory(a, b, "/dev/shm")

    def test_nginx_routes_preserve_panel_api_and_subscription(self):
        p = self.plan()
        old = s.nginx_blocks(self.rt.nginx_text)
        new = s.nginx_blocks(p["nginx"])
        self.assertEqual(old[:2], new[:2])
        self.assertIn("grpc_pass grpc://", p["nginx"])
        self.assertIn("proxy_request_buffering off", p["nginx"])

    def test_nginx_route_patch_is_idempotent(self):
        p = self.plan()
        self.assertEqual(s.add_routes(p["nginx"], p["domain"], [
            {"path": a["path"], "port": a["port"], "network": a["network"]}
            for a in p["specs"] if a["frontend"]]), p["nginx"])

    def test_nginx_route_collision_rejected(self):
        p = self.plan()
        spec = next(a for a in p["specs"] if a["frontend"])
        text = self.rt.nginx_text.replace("root /var/www/html;", "root /var/www/html;\nlocation " + spec["path"] + " { return 404; }")
        with self.assertRaisesRegex(RuntimeError, "intersects"):
            s.add_routes(text, p["domain"], [{"path": spec["path"], "port": 32123, "network": "ws"}])

    def check_nginx_staging(self, reject=False):
        runtime = object.__new__(s.Runtime)
        runtime.nginx = {"Id": "actual-nginx"}
        runtime.nginx_inside = "/etc/nginx/conf.d/default.conf"
        calls = []
        staged = "/tmp/egames-nginx-Ab123C.conf"
        def execute(args, data=None, check=True):
            calls.append((args, data, check))
            output = ""
            if args[-1] == "/etc/nginx/nginx.conf":
                output = "events {}\nhttp { include /etc/nginx/conf.d/*.conf; }\n"
            elif "find" in args:
                output = runtime.nginx_inside + "\n"
            elif "mktemp" in args:
                output = staged + "\n"
            elif "nginx" in args and "-t" in args and reject:
                raise RuntimeError("synthetic Nginx validation failure")
            return types.SimpleNamespace(stdout=output, returncode=0)
        with patch.object(s, "command", side_effect=execute):
            if reject:
                with self.assertRaisesRegex(RuntimeError, "synthetic Nginx"):
                    runtime.validate_nginx(self.rt.nginx_text)
            else:
                runtime.validate_nginx(self.rt.nginx_text)
        self.assertTrue(any("-t" in args and args[-1] == staged for args, _, _ in calls))
        self.assertFalse(any("/dev/stdin" in args for args, _, _ in calls))
        write = next((args, data) for args, data, _ in calls if "sh" in args)
        self.assertIn('umask 077; cat > "$1"', write[0])
        self.assertIn("events {}", write[1])
        self.assertIn(self.rt.nginx_text, write[1])
        self.assertEqual(calls[-1][0][-4:], ["rm", "-f", "--", staged])

    def test_nginx_validator_uses_private_seekable_config(self):
        self.check_nginx_staging()

    def test_nginx_validator_cleans_staging_after_rejection(self):
        self.check_nginx_staging(reject=True)

    def test_duplicate_and_occupied_ports(self):
        config = self.api.profile["config"]
        bad = copy.deepcopy(config)
        bad["inbounds"].append(copy.deepcopy(bad["inbounds"][0]))
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            s.check_ports(config, bad, set())
        bad["inbounds"][-1].update(tag="other", port=2222)
        with self.assertRaisesRegex(RuntimeError, "Occupied"):
            s.check_ports(config, bad, {("tcp", 2222)})

    def test_install_and_repeat_no_duplicate_hosts_or_inbounds(self):
        p = self.plan()
        self.apply(p)
        original = copy.deepcopy(self.api.profile["config"])
        hosts = copy.deepcopy(self.api.hosts)
        self.state = s.read_state(self.tmp.name)
        self.rt.nginx_text = self.rt.nginx_path.read_text()
        p = self.plan()
        self.apply(p)
        self.assertEqual(self.api.profile["config"], original)
        self.assertEqual(self.api.hosts, hosts)
        self.assertEqual(len(self.api.profile["inbounds"]), len({i["tag"] for i in self.api.profile["inbounds"]}))

    def test_repair_host_keeps_uuid_and_does_not_duplicate(self):
        self.apply(self.plan())
        self.state = s.read_state(self.tmp.name)
        self.rt.nginx_text = self.rt.nginx_path.read_text()
        host = self.api.hosts[1]
        identity = host["uuid"]
        host["address"] = "wrong.example.com"
        host["port"] = 8443
        self.apply(self.plan())
        self.assertEqual(next(h for h in self.api.hosts if h["uuid"] == identity)["address"], "node.example.com")
        self.assertEqual(len(self.api.hosts), 7)

    def test_unowned_nginx_marker_fails_closed(self):
        p = self.plan()
        self.rt.nginx_text = p["nginx"]
        with self.assertRaisesRegex(RuntimeError, "Nginx routes"):
            self.plan()

    def test_core_version_mismatch_fails_closed(self):
        self.api.nodes[0]["versions"]["xray"] = "1.0.0"
        with self.assertRaisesRegex(RuntimeError, "differs"):
            self.plan()

    def test_manual_profile_clients_are_not_erased_by_panel_normalization(self):
        self.api.profile["config"]["inbounds"][0]["settings"]["clients"] = [{"id": "manual-user"}]
        with self.assertRaisesRegex(RuntimeError, "manual clients"):
            self.plan()

    def test_membership_readback_ignores_orm_order(self):
        value = {"uuid": "q", "inbounds": ["a", "b"]}
        expected = {"uuid": "q", "inbounds": ["b", "a"]}
        self.assertTrue(s.same_operation_value({"kind": "squad"}, value, expected))

    def test_real_xray_rejection_blocks_required_inbound_before_mutation(self):
        base_validator = self.rt.validate_xray
        def validate(config):
            if any(i["tag"] == "Vless-XHTTP -tcp-2" for i in config["inbounds"]):
                raise RuntimeError("unsupported transport")
            return base_validator(config)
        self.rt.validate_xray = validate
        with self.assertRaisesRegex(RuntimeError, "Required capabilities unavailable: XREALITY"):
            self.plan()
        self.assertFalse(self.api.writes)

    def test_uninstall_history_restores_original_across_repeat(self):
        before = copy.deepcopy(self.api.profile)
        self.apply(self.plan())
        self.state = s.read_state(self.tmp.name)
        self.rt.nginx_text = self.rt.nginx_path.read_text()
        self.apply(self.plan())
        for journal in reversed(s.read_state(self.tmp.name)["history"]):
            s.recover(self.api, self.rt, self.tmp.name, journal)
        self.assertEqual(self.api.profile, before)
        self.assertEqual(len(self.api.hosts), 1)

    def test_backup_and_rollback_restores_original(self):
        original = copy.deepcopy(self.api.__dict__)
        self.apply(self.plan())
        self.assertTrue(list((Path(self.tmp.name) / "backups").glob("*.json")))
        s.recover(self.api, self.rt, self.tmp.name)
        for k in ("profile", "nodes", "squads", "hosts"):
            # API representation permits either object or UUID list for node activeInbounds.
            if k != "nodes":
                self.assertEqual(getattr(self.api, k), original[k])
        self.assertEqual(s.active_ids(self.api.nodes[0]), s.active_ids(original["nodes"][0]))
        self.assertEqual(self.rt.nginx_path.read_text(), (FIXTURES / "nginx.conf").read_text())

    def test_node_api_failure_rolls_back_and_raises(self):
        original = copy.deepcopy(self.api.profile)
        self.api.fail = "/nodes"
        with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
            self.apply(self.plan())
        self.assertEqual(self.api.profile, original)
        self.assertEqual(len(self.api.hosts), 1)

    def test_lost_http_reply_reconciles_before_rollback(self):
        before = copy.deepcopy(self.api.profile["config"])
        after = copy.deepcopy(before)
        after["dns"] = {"servers": ["8.8.8.8"]}
        tx = s.Transaction(self.api, self.rt, self.tmp.name, self.state)
        self.api.lose_reply = True
        with self.assertRaisesRegex(RuntimeError, "timeout"):
            tx.api("profile", "/config-profiles", s.profile_patch(self.api.profile, before), s.profile_patch(self.api.profile, after))
        tx.rollback()
        self.assertEqual(self.api.profile["config"], before)

    def test_rollback_refuses_external_drift(self):
        self.apply(self.plan())
        self.api.nodes[0]["configProfile"]["activeInbounds"].append("external-inbound")
        with self.assertRaisesRegex(RuntimeError, "INCOMPLETE"):
            s.recover(self.api, self.rt, self.tmp.name)
        self.assertEqual(json.loads((Path(self.tmp.name) / "journal.json").read_text())["status"], "rollback_incomplete")

    def test_unowned_tag_is_never_adopted(self):
        self.api.profile["config"]["inbounds"].append({"tag": "EGADDON-WS", "port": 45678, "protocol": "vless"})
        with self.assertRaisesRegex(RuntimeError, "Unowned inbound"):
            self.plan()

    def test_ss2022_key_is_32_bytes(self):
        p = self.plan()
        ib = next(i for i in p["config"]["inbounds"] if i["protocol"] == "shadowsocks")
        self.assertEqual(len(s.base64.b64decode(ib["settings"]["password"])), 32)

    def test_vision_xhttp_and_fake_pq_are_rejected(self):
        args = dict(reality_private_key="x", reality_short_id="00", reality_server_name="x.test", reality_dest="x.test:443")
        with self.assertRaisesRegex(ValueError, "Vision"):
            build_inbound({"tag": "x", "protocol": "vless", "network": "xhttp", "flow": "xtls-rprx-vision"}, **args)
        with self.assertRaisesRegex(ValueError, "PQ requires"):
            build_inbound({"tag": "PQ", "protocol": "vless"}, **args)
        with self.assertRaisesRegex(ValueError, "certificate/key"):
            build_inbound({"tag": "tls", "protocol": "vless", "security": "tls"}, **args)

    def test_api_errors_do_not_echo_secrets_and_no_redirect(self):
        client = RemnawaveClient("http://127.0.0.1:3000/api", "secret-token")
        response = Mock(status_code=400, text="PRIVATE_KEY secret", content=b"private")
        client.session.request = Mock(return_value=response)
        with self.assertRaisesRegex(RuntimeError, "HTTP 400") as e:
            client.get("/nodes")
        self.assertNotIn("secret", str(e.exception))
        self.assertFalse(client.session.request.call_args.kwargs["allow_redirects"])
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            RemnawaveClient("http://remote.example.com/api", "token")

    def test_ufw_rule_matching_keeps_other_rules(self):
        self.assertTrue(s.ufw_has_rule("34567/tcp ALLOW Anywhere # someone", "34567/tcp"))
        self.assertFalse(s.ufw_has_rule("134567/tcp ALLOW Anywhere", "34567/tcp"))

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_backup_permissions(self):
        path = Path(self.tmp.name) / "private.json"
        s.private_json(path, {"key": "secret"})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class GeoIPTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch.object(s.socket, "getaddrinfo", return_value=[
            (s.socket.AF_INET, s.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
        self.dns.start()
        self.addCleanup(self.dns.stop)
        self.factory = patch.object(s.requests, "Session")
        self.session = self.factory.start().return_value.__enter__.return_value
        self.addCleanup(self.factory.stop)

    def test_geoip_uses_endpoint_ip_and_separate_https_session_with_fallback(self):
        self.session.get.side_effect = [Mock(status_code=503), Mock(
            status_code=200, json=Mock(return_value={"ip": "8.8.8.8", "country": "FI"}))]
        self.assertEqual(s.lookup_country_code("node.example.com"), "FI")
        self.assertFalse(self.session.trust_env)
        self.assertEqual(self.session.get.call_args_list[0].args, ("https://ipwho.is/8.8.8.8",))
        self.assertEqual(self.session.get.call_args_list[1].args, ("https://ipinfo.io/8.8.8.8/json",))
        for call in self.session.get.call_args_list:
            self.assertEqual(call.kwargs, {"timeout": (3, 5), "allow_redirects": False})

    def test_geoip_rejects_wrong_ip_unassigned_country_and_redirect(self):
        invalid = [Mock(status_code=200, json=Mock(return_value={"ip": "1.1.1.1", "country_code": "FI"})),
                   Mock(status_code=200, json=Mock(return_value={"ip": "8.8.8.8", "country_code": "ZZ"})),
                   Mock(status_code=302)]
        for response in invalid:
            with self.subTest(response=response):
                self.session.get.side_effect = [response, s.requests.Timeout("private diagnostic")]
                with self.assertRaisesRegex(RuntimeError, "GeoIP unavailable") as error:
                    s.lookup_country_code("node.example.com")
                self.assertNotIn("private diagnostic", str(error.exception))

    def test_geoip_refuses_private_or_multiple_addresses_without_requests(self):
        for ips in (("127.0.0.1",), ("8.8.8.8", "1.1.1.1"), ()):
            with self.subTest(ips=ips), patch.object(s.socket, "getaddrinfo", return_value=[
                    (s.socket.AF_INET, s.socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]):
                with self.assertRaisesRegex(RuntimeError, "public VPS IPv4"):
                    s.lookup_country_code("node.example.com")
        self.session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
