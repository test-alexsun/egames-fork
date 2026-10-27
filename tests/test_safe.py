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

    def get(self, path):
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
        self.cmd = patch.object(s, "command", return_value=types.SimpleNamespace(stdout="[]", returncode=0))
        self.cmd.start()
        self.addCleanup(self.cmd.stop)

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
                host = s.host_body(spec, "pid", "iid", p["domain"], "nid")
                self.assertEqual((host["port"], host["securityLayer"]), (443, "TLS"))
                self.assertEqual(host["path"], spec["service_name"] if spec["network"] == "grpc" else spec["path"])

    def test_pq_has_real_seed_and_no_vision(self):
        p = self.plan()
        ib = next(i for i in p["config"]["inbounds"] if i["tag"] == "EGADDON-PQ")
        self.assertTrue(ib["settings"]["decryption"].startswith("mlkem768x25519plus."))
        self.assertEqual(ib["settings"]["flow"], "")
        self.assertEqual(ib["streamSettings"]["network"], "raw")

    def test_missing_pq_generator_does_not_create_fake_pq(self):
        self.rt.core = Mock(side_effect=RuntimeError("no vlessenc"))
        p = self.plan()
        self.assertNotIn("EGADDON-PQ", [i["tag"] for i in p["config"]["inbounds"]])

    def test_vmess_and_missing_hy2_mount_reported(self):
        p = self.plan()
        self.assertTrue(any("VMess skipped" in d for d in p["diagnostics"]))
        self.assertTrue(any("Hysteria2 skipped" in d and "not mounted" in d for d in p["diagnostics"]))

    def test_hy2_version_2_and_udp443(self):
        self.rt.node["Mounts"] = [{"Source": "/etc/ssl", "Destination": "/tls"}]
        p = self.plan()
        ib = next(i for i in p["config"]["inbounds"] if i["tag"] == "EGADDON-HY2")
        self.assertEqual(ib["settings"]["version"], 2)
        self.assertEqual(ib["streamSettings"]["hysteriaSettings"]["version"], 2)
        self.assertEqual(ib["port"], 443)

    def test_hy2_udp_conflict_does_not_touch_tcp443(self):
        self.rt.node["Mounts"] = [{"Source": "/etc/ssl", "Destination": "/tls"}]
        p = self.plan({("tcp", 443), ("udp", 443)})
        self.assertNotIn("EGADDON-HY2", [i["tag"] for i in p["config"]["inbounds"]])
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

    def test_real_xray_rejection_skips_inbound_before_mutation(self):
        base_validator = self.rt.validate_xray
        def validate(config):
            if any(i["tag"] == "EGADDON-XREALITY" for i in config["inbounds"]):
                raise RuntimeError("unsupported transport")
            return base_validator(config)
        self.rt.validate_xray = validate
        p = self.plan()
        self.assertNotIn("EGADDON-XREALITY", [i["tag"] for i in p["config"]["inbounds"]])
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


if __name__ == "__main__":
    unittest.main()
