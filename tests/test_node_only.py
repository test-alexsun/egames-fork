import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import egames_node as n
import egames_safe as s
from test_safe import API, Runtime

NODE = "30000000-0000-4000-8000-000000000001"


class RemoteSettingsTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"node_uuid": NODE}
        self.sub = {"Config": {"Image": "remnawave/subscription-page:latest", "Env": [
            "REMNAWAVE_PANEL_URL=https://panel.example.com", "REMNAWAVE_API_TOKEN=test-secret",
            "EGAMES_COOKIE=gate=testvalue"]}}

    def test_discovers_remote_url_token_and_cookie_without_local_panel(self):
        result = n.remote_settings([self.sub], self.cfg)
        self.assertEqual(result["panel_api_url"], "https://panel.example.com/api")
        self.assertEqual(result["panel_api_token"], "test-secret")
        self.assertEqual(result["panel_cookie"], "gate=testvalue")

    def test_rejects_local_panel_and_ambiguous_subscriptions(self):
        with self.assertRaisesRegex(RuntimeError, "without a local Panel"):
            n.remote_settings([self.sub, {"Config": {"Image": "remnawave/backend:3"}}], self.cfg)
        with self.assertRaises(RuntimeError):
            n.remote_settings([self.sub, self.sub], self.cfg)

    def test_requires_explicit_node_and_tls(self):
        with self.assertRaisesRegex(RuntimeError, "node_uuid"):
            n.remote_settings([self.sub], {})
        for url in ("http://panel.example.com", "https://user:pass@panel.example.com", "https://panel.example.com?secret=1", "https://localhost"):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                n.remote_settings([self.sub], {**self.cfg, "panel_api_url": url})

    def test_private_overrides_and_cookie_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            token, cookie = Path(temp) / "token", Path(temp) / "cookie"
            token.write_text("override-token"); cookie.write_text("name=override")
            token.chmod(0o600); cookie.chmod(0o600)
            result = n.remote_settings([self.sub], {**self.cfg, "token_file": str(token), "cookie_file": str(cookie)})
            self.assertEqual(result["panel_api_token"], "override-token")
            self.assertEqual(result["panel_cookie"], "name=override")
        with self.assertRaisesRegex(RuntimeError, "cookie"):
            n.remote_settings([self.sub], {**self.cfg, "panel_cookie": "name=value\r\nInjected: x"})

    @unittest.skipUnless(os.name == "posix", "POSIX file modes")
    def test_rejects_public_credential_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "token"
            path.write_text("secret"); path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "0600"):
                n.private_value(path)

    def test_check_subscription_without_user_is_explicitly_unverified(self):
        with patch("builtins.print") as output:
            n.check_subscription({})
        self.assertIn("NOT TESTED", output.call_args.args[0])

    def test_runtime_discovers_node_nginx_and_remote_api_without_panel(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "nginx.conf"
            config.write_text("# synthetic mounted config")
            shm = {"Source": "/dev/shm", "Destination": "/dev/shm", "RW": True}
            containers = [
                {"Id": "node", "Config": {"Image": "remnawave/node:latest"},
                 "HostConfig": {"NetworkMode": "host"}, "Mounts": [shm]},
                {"Id": "nginx", "Config": {"Image": "nginx:1.30"},
                 "HostConfig": {"NetworkMode": "host"}, "Mounts": [shm,
                    {"Source": str(config), "Destination": "/etc/nginx/conf.d/default.conf"}]}, self.sub]
            def command(args, *a, **kw):
                out = "node nginx subscription" if args == ["docker", "ps", "-q"] else (
                    json.dumps(containers) if args[:2] == ["docker", "inspect"] else (
                    "Xray 26.7.28 synthetic" if args[-1] == "version" and "exec" in args else ""))
                return Mock(stdout=out, returncode=0)
            with patch.object(s, "command", side_effect=command):
                runtime = s.Runtime({**self.cfg, "deployment": "node-only"})
            self.assertIsNone(runtime.panel)
            self.assertEqual(runtime.node["Id"], "node")
            self.assertEqual(runtime.api, "https://panel.example.com/api")
            self.assertEqual(runtime.cookie, "gate=testvalue")

    def test_subscription_rejects_html_empty_and_wrong_node(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.url"
            path.write_text("https://sub.example.com/test/json"); path.chmod(0o600)
            cfg = {"subscription_test_url_file": str(path), "subscription_domain": "sub.example.com", "host_address": "node.example.com"}
            session = Mock()
            with patch.object(n.requests, "Session") as factory:
                factory.return_value.__enter__.return_value = session
                for payload in ({"html": True}, [], [{"outbounds": []}]):
                    session.get.return_value.json.return_value = payload
                    with self.assertRaises(RuntimeError):
                        n.check_subscription(cfg)
                session.get.return_value.json.return_value = [{"outbounds": [{"settings": {"vnext": [{"address": "node.example.com"}]}}]}]
                n.check_subscription(cfg)
                self.assertFalse(session.get.call_args.kwargs["allow_redirects"])


class RemotePlanTests(unittest.TestCase):
    def test_remote_profile_tags_do_not_conflict_with_existing_other_node(self):
        with tempfile.TemporaryDirectory() as temp:
            api, rt = API(), Runtime(temp)
            other = {"uuid": "other-profile", "inbounds": [{"tag": "EGADDON-WS", "uuid": "other-ib"}]}
            get = api.get
            def read(path):
                return {"configProfiles": [api.profile, other]} if path == "/config-profiles" else get(path)
            api.get = read
            before = copy.deepcopy(api.profile)
            with patch.object(s, "command", return_value=Mock(stdout="[]", returncode=0)), patch.object(s, "lookup_country_code", return_value="DE"):
                plan = s.plan(api, rt, {"node_uuid": NODE, "tag_prefix": "EGADDON-30000000"}, {}, set())
            self.assertTrue(all(spec["tag"].startswith("EGADDON-30000000-") for spec in plan["specs"]))
            self.assertEqual(api.profile, before)
            self.assertEqual(api.writes, [])
            self.assertEqual(s.host_remark("EGADDON-30000000-GRPC", "DE"), "\U0001f1e9\U0001f1ea | Trojan | gRPC TLS")

    def test_wrong_node_state_and_changed_prefix_fail_before_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            api, rt = API(), Runtime(temp)
            with patch.object(s, "command", return_value=Mock(stdout="[]", returncode=0)):
                for state in ({"node_uuid": "different"}, {"tag_prefix": "EGADDON-OTHER"}):
                    with self.assertRaises(RuntimeError):
                        s.plan(api, rt, {}, state, set())
            self.assertEqual(api.writes, [])
