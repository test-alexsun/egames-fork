"""Regression cases for CODEX_01 findings; all fixtures are synthetic."""
import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

import egames_safe as s
from inbound_tags import effective_flow, descriptive_tag
import test_safe as fixtures


class Audit02Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SafeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.t = self.fixture

    def test_concurrent_access_revocation_before_apply_has_zero_mutations(self):
        for kind in ('squad', 'node', 'host'):
            with self.subTest(kind=kind):
                p = self.t.plan()
                if kind == 'squad':
                    self.t.api.squads[0]['inbounds'] = []
                elif kind == 'node':
                    self.t.api.nodes[0]['configProfile']['activeInbounds'] = []
                else:
                    self.t.api.hosts[0]['isDisabled'] = True
                with self.assertRaisesRegex(RuntimeError, 'Concurrent'):
                    self.t.apply(p)
                self.assertFalse(self.t.api.writes)
                self.t.api = fixtures.API()

    def test_mid_transaction_revocation_preserved(self):
        p = self.t.plan()
        tx = s.Transaction(self.t.api, self.t.rt, self.t.tmp.name, self.t.state)
        before = s.writable_squad(p['squads'][0])
        self.t.api.squads[0]['inbounds'] = []
        with self.assertRaisesRegex(RuntimeError, 'Concurrent'):
            tx.api('squad', '/internal-squads', before, {**before, 'inbounds': before['inbounds'] + ['new']})
        self.assertFalse(self.t.api.writes)
        self.assertEqual(self.t.api.squads[0]['inbounds'], [])

    def test_repeat_preserves_node_disable(self):
        self.t.apply(self.t.plan())
        self.t.state = s.read_state(self.t.tmp.name)
        self.t.rt.nginx_text = self.t.rt.nginx_path.read_text()
        node = self.t.api.nodes[0]
        removed = s.active_ids(node)[-1]
        node['configProfile']['activeInbounds'] = s.active_ids(node)[:-1]
        self.t.apply(self.t.plan())
        self.assertNotIn(removed, s.active_ids(node))

    def test_repeat_keeps_host_operator_node_scope_and_custom_tags(self):
        self.t.apply(self.t.plan())
        self.t.state = s.read_state(self.t.tmp.name)
        self.t.rt.nginx_text = self.t.rt.nginx_path.read_text()
        host = self.t.api.hosts[1]
        host['tags'].append('operator-category')
        host['nodes'] = []
        self.t.apply(self.t.plan())
        self.assertIn('operator-category', host['tags'])
        self.assertEqual(host['nodes'], [])

    def test_interrupted_nginx_write_is_recovered_but_external_drift_is_not(self):
        for interrupted in (True, False):
            with self.subTest(interrupted=interrupted):
                before = self.t.rt.nginx_text
                after = '# new header\n' + before
                tx = s.Transaction(self.t.api, self.t.rt, self.t.tmp.name, self.t.state)
                def partial(text):
                    self.t.rt.nginx_path.write_text(text[:12] + before[12:])
                    raise OSError('simulated disk error')
                with patch.object(self.t.rt, 'write_nginx', side_effect=partial):
                    with self.assertRaises(OSError):
                        tx.nginx(before, after)
                if not interrupted:
                    self.t.rt.nginx_path.write_text('# operator edit')
                    with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE'):
                        tx.rollback()
                    self.assertEqual(self.t.rt.nginx_path.read_text(), '# operator edit')
                else:
                    tx.rollback()
                    self.assertEqual(self.t.rt.nginx_path.read_text(), before)
                self.t.rt.nginx_path.write_text(before)

    def test_recovery_accepts_recreated_container_but_rejects_other_image(self):
        self.t.apply(self.t.plan())
        self.t.rt.node['Id'] = 'new-container-id'
        s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertEqual(len(self.t.api.profile['inbounds']), 1)
        self.t.state = s.read_state(self.t.tmp.name)
        self.t.rt.nginx_text = self.t.rt.nginx_path.read_text()
        self.t.apply(self.t.plan())
        self.t.rt.node['Image'] = 'different-digest'
        self.t.api.writes.clear()
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertFalse(self.t.api.writes)

    def test_second_interruption_during_partial_nginx_recovery_is_recoverable(self):
        before = self.t.rt.nginx_text
        after = '# new header\n' + before
        tx = s.Transaction(self.t.api, self.t.rt, self.t.tmp.name, self.t.state)
        def first_failure(text):
            self.t.rt.nginx_path.write_text(text[:12] + before[12:])
            raise OSError('write failed')
        with patch.object(self.t.rt, 'write_nginx', side_effect=first_failure):
            with self.assertRaises(OSError):
                tx.nginx(before, after)
        def second_failure(text):
            actual = self.t.rt.nginx_path.read_text()
            self.t.rt.nginx_path.write_text(text[:4] + actual[4:])
            raise OSError('recovery write failed')
        with patch.object(self.t.rt, 'write_nginx', side_effect=second_failure):
            with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE'):
                tx.rollback()
        s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertEqual(self.t.rt.nginx_path.read_text(), before)

    def test_new_transaction_restore_retains_historical_migration_guard(self):
        self.t.state['tag_migration_backup'] = 'historical-snapshot'
        self.t.state['pre_tag_migration_history'] = ['old-schema-journal']
        self.t.apply(self.t.plan())
        s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertEqual(s.read_state(self.t.tmp.name)['tag_migration_backup'], 'historical-snapshot')
        self.assertEqual(len(self.t.api.profile['inbounds']), 1)

    def test_old_schema_and_migrated_epoch_journals_cannot_replay(self):
        self.t.apply(self.t.plan())
        path = Path(self.t.tmp.name) / 'journal.json'
        data = json.loads(path.read_text())
        data['schema'] = 1
        s.private_json(path, data)
        self.t.api.writes.clear()
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertFalse(self.t.api.writes)
        state = s.read_state(self.t.tmp.name)
        state['tag_migration_backup'] = 'historical'
        s.private_json(Path(self.t.tmp.name) / 'state.json', state)
        with self.assertRaisesRegex(RuntimeError, 'invalidated UUID'):
            s.recover(self.t.api, self.t.rt, self.t.tmp.name)

    def test_missing_http2_blocks_required_grpc(self):
        self.t.rt.nginx_text = self.t.rt.nginx_text.replace('http2 on;', '')
        with self.assertRaisesRegex(RuntimeError, 'Required capabilities unavailable: GRPC'):
            self.t.plan()
        self.assertFalse(self.t.api.writes)

    def test_optional_and_required_hy2_are_distinct(self):
        p = self.t.plan()
        self.assertFalse(p['capabilities']['HY2']['required'])
        self.assertEqual(p['capabilities']['HY2']['status'], 'unavailable')
        self.assertIn('not mounted', p['capabilities']['HY2']['reason'])
        with self.assertRaisesRegex(RuntimeError, 'Required capabilities unavailable: HY2'):
            s.plan(self.t.api, self.t.rt, {'required_protocols': ['HY2']}, self.t.state, {('tcp', 443)})

    def test_false_vision_advertising_is_blocked(self):
        ib = self.t.api.profile['config']['inbounds'][0]
        self.assertEqual(effective_flow(ib), 'xtls-rprx-vision')
        ib['settings']['flow'] = ''
        self.assertEqual(effective_flow(ib), '')
        with self.assertRaisesRegex(RuntimeError, 'does not provide Panel Vision'):
            self.t.plan()
        ib['settings']['flow'] = 'xtls-rprx-vision'
        self.assertEqual(descriptive_tag(ib), 'Vless-Vision-tcp')
        ib['streamSettings']['network'] = 'xhttp'
        del ib['settings']['flow']
        self.assertEqual(effective_flow(ib), '')

    def test_restricted_or_ipv4_only_ufw_is_not_silently_expanded(self):
        spec = {'frontend': False, 'protocol': 'vless', 'port': 34567}
        for line in ('34567/tcp ALLOW 192.0.2.0/24', '34567/tcp DENY Anywhere',
                     '34567/tcp ALLOW Anywhere'):
            with self.subTest(line=line), patch.object(s, 'firewall_status', return_value=line):
                with self.assertRaises(RuntimeError):
                    s.check_firewall([spec])
        with patch.object(s, 'firewall_status', return_value='34567/tcp ALLOW Anywhere\n34567/tcp (v6) ALLOW Anywhere (v6)'):
            self.assertEqual(s.check_firewall([spec])['ufw'], 'reviewed')
        status = {'text': 'Status: active'}
        def ufw(args, *a, **kw):
            if 'delete' in args:
                status['text'] = 'Status: active'
            else:
                status['text'] = 'Status: active\n34567/tcp ALLOW Anywhere # ' + s.OWNER
            return types.SimpleNamespace(stdout='', returncode=0)
        tx = s.Transaction(self.t.api, self.t.rt, self.t.tmp.name, self.t.state)
        with patch.object(s, 'firewall_status', side_effect=lambda: status['text']), patch.object(s, 'command', side_effect=ufw):
            with self.assertRaisesRegex(RuntimeError, 'IPv4-only'):
                tx.firewall([spec])
            tx.rollback()
        self.assertEqual(status['text'], 'Status: active')

    def test_fake_occupied_ports_do_not_prove_node_sync(self):
        p = self.t.plan()
        self.t.apply(p)
        self.t.rt.owned_listeners = lambda: {('tcp', 443)}
        self.t.rt.applied_inbounds = lambda: []
        with patch.object(s.time, 'sleep'), self.assertRaisesRegex(RuntimeError, 'did not synchronize'):
            s.verify(self.t.api, self.t.rt, p)
        self.t.rt.applied_inbounds = lambda: copy.deepcopy(p['config']['inbounds'])
        self.t.rt.owned_listeners = lambda: {(proto, i['port']) for i in p['config']['inbounds'] for proto in s.transports(i)}
        self.t.rt.core_pids = lambda: {456}
        self.t.api.nodes[0]['isDisabled'] = True
        with patch.object(s.time, 'sleep'), self.assertRaisesRegex(RuntimeError, 'did not synchronize'):
            s.verify(self.t.api, self.t.rt, p)

    def test_node_only_apply_is_blocked_before_runtime_or_panel_discovery(self):
        with patch.object(s.os, 'name', 'posix'), patch.object(s.os, 'geteuid', return_value=0, create=True), \
                patch.object(s.platform, 'freedesktop_os_release', return_value={'ID': 'debian', 'VERSION_ID': '13'}), \
                patch.object(s, 'Runtime') as runtime:
            with self.assertRaisesRegex(RuntimeError, 'read-only'):
                s.run({'mode': 'install', 'topology': 'node-only'})
            runtime.assert_not_called()

    def test_lost_response_compensates_known_identity_and_blocks_uncertain_post(self):
        self.t.rt.node['Mounts'] = [{'Source': '/etc/ssl', 'Destination': '/tls'}]
        original_request = self.t.api.request
        for target in range(1, 12):
            with self.subTest(target=target):
                self.t.api = fixtures.API()
                self.t.state = {'owner': s.OWNER, 'tags': [], 'hosts': [], 'paths': {}}
                self.t.rt.nginx_path.write_text(self.t.rt.nginx_text)
                original_request = self.t.api.request
                count = 0
                def uncertain(method, path, body=None):
                    nonlocal count
                    result = original_request(method, path, body)
                    count += 1
                    if count == target:
                        raise RuntimeError('Lost response after commit')
                    return result
                self.t.api.request = uncertain
                with self.assertRaisesRegex(RuntimeError, 'Lost response|INCOMPLETE'):
                    self.t.apply(self.t.plan())
                if 3 <= target <= 9:
                    # POST has committed but its UUID reply was lost: do not adopt
                    # or delete an object inferred from its endpoint/category.
                    self.assertGreater(len(self.t.api.hosts), 1)
                    self.assertFalse(any(m == 'DELETE' for m, _, _ in self.t.api.writes))
                    continue
                self.assertEqual(len(self.t.api.profile['inbounds']), 1)
                self.assertEqual(len(self.t.api.hosts), 1)
                self.assertEqual(s.active_ids(self.t.api.nodes[0]), ['20000000-0000-4000-8000-000000000001'])

    def test_abrupt_process_exit_during_nginx_overwrite_recovers(self):
        code = r'''
import os, sys, types
from pathlib import Path
import egames_safe as s
directory = Path(sys.argv[1])
path = directory / 'nginx.conf'
before = path.read_text()
def die(text):
    path.write_text(text[:10] + before[10:])
    os._exit(29)
rt = types.SimpleNamespace(nginx_path=path, node={'Id':'local-node','Mounts':[]}, nginx={'Id':'local-nginx'}, write_nginx=die)
tx = s.Transaction(None, rt, directory, {'owner':s.OWNER,'tags':[],'hosts':[],'paths':{}})
tx.nginx(before, '# interrupted header\n' + before)
'''
        result = subprocess.run([sys.executable, '-B', '-c', code, self.t.tmp.name], cwd=Path(s.__file__).parent,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 29, result.stderr)
        s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertEqual(self.t.rt.nginx_path.read_text(), self.t.rt.nginx_text)

    def test_committing_journal_recovers_after_state_history_gap(self):
        self.t.apply(self.t.plan())
        journal = Path(self.t.tmp.name) / 'journal.json'
        data = json.loads(journal.read_text())
        data['status'] = 'committing'
        s.private_json(journal, data)
        Path(data['history_path']).unlink()
        (Path(self.t.tmp.name) / 'state.json').unlink()
        s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertTrue(Path(data['history_path']).exists())
        self.assertEqual(s.read_state(self.t.tmp.name)['tags'], [])
        self.assertEqual(len(self.t.api.profile['inbounds']), 1)

    def test_stopped_nginx_file_recovers_even_if_panel_is_unavailable(self):
        self.t.apply(self.t.plan())
        self.t.rt.recovery = True
        self.t.rt.nginx['State'] = {'Running': False}
        self.t.api.get = lambda path: (_ for _ in ()).throw(RuntimeError('Panel unreachable'))
        with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE'):
            s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertEqual(self.t.rt.nginx_path.read_text(), self.t.rt.nginx_text)

    def test_node_generated_config_and_socket_ownership_must_both_match(self):
        p = self.t.plan()
        self.t.apply(p)
        self.t.rt.owned_listeners = lambda: {(proto, i['port']) for i in p['config']['inbounds'] for proto in s.transports(i)}
        self.t.rt.applied_inbounds = lambda: copy.deepcopy(p['config']['inbounds'])
        self.t.rt.core_pids = lambda: {456}
        self.assertEqual(s.verify(self.t.api, self.t.rt, p)['uuid'], p['node']['uuid'])
        actual = copy.deepcopy(p['config']['inbounds'])
        actual[1]['streamSettings']['network'] = 'grpc'
        self.t.rt.applied_inbounds = lambda: actual
        with patch.object(s.time, 'sleep'), self.assertRaisesRegex(RuntimeError, 'did not synchronize'):
            s.verify(self.t.api, self.t.rt, p)

    def test_runtime_socket_check_rejects_foreign_process(self):
        rt = object.__new__(s.Runtime)
        rt.node = {'Id': 'node'}
        def cmd(args, *a, **kw):
            value = 'PID COMMAND\n123 rw-core\n' if 'top' in args else 'LISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=999,fd=4))\n'
            return types.SimpleNamespace(stdout=value, returncode=0)
        with patch.object(s, 'command', side_effect=cmd):
            self.assertNotIn(('tcp', 443), rt.owned_listeners())

    def test_node_only_inventory_uses_remote_panel_without_writes(self):
        import node_only
        cfg = {'panel_api_url': 'https://panel.example.com/api', 'token_file': '/private/token',
               'node_uuid': self.t.api.nodes[0]['uuid']}
        with patch.object(node_only, 'command', return_value=types.SimpleNamespace(stdout='[]')):
            result = node_only.inspect(self.t.api, self.t.rt, cfg)
            self.assertFalse(result['canApply'])
            self.assertTrue(result['connected'])
            self.t.api.nodes[0]['address'] = '192.0.2.10'
            with self.assertRaisesRegex(RuntimeError, 'does not identify this VPS'):
                node_only.inspect(self.t.api, self.t.rt, cfg)
        self.assertFalse(self.t.api.writes)

    def test_owned_legacy_tag_and_uuid_are_preserved_on_repeat(self):
        self.t.apply(self.t.plan())
        self.t.state = s.read_state(self.t.tmp.name)
        self.t.rt.nginx_text = self.t.rt.nginx_path.read_text()
        tag = self.t.state['tag_labels']['XHTTP']
        legacy = 'EGADDON-XHTTP'
        self.t.state['tag_labels']['XHTTP'] = legacy
        self.t.state['tags'] = [legacy if t == tag else t for t in self.t.state['tags']]
        self.t.state['paths'][legacy] = self.t.state['paths'].pop(tag)
        self.t.state['host_ids'][legacy] = self.t.state['host_ids'].pop(tag)
        ib = self.t.state['inbounds'].pop(tag)
        ib['tag'] = legacy
        self.t.state['inbounds'][legacy] = ib
        for i in self.t.api.profile['config']['inbounds']:
            if i['tag'] == tag:
                i['tag'] = legacy
        for i in self.t.api.profile['inbounds']:
            if i['tag'] == tag:
                i['tag'] = legacy
                uuid = i['uuid']
        self.t.apply(self.t.plan())
        self.assertEqual(next(i['uuid'] for i in self.t.api.profile['inbounds'] if i['tag'] == legacy), uuid)

    def test_spaced_tag_is_used_for_new_inbounds(self):
        p = self.t.plan()
        self.assertEqual(next(i['tag'] for i in p['specs'] if i['label'] == 'XHTTP'), 'Vless-XHTTP -tcp')

    def test_recovery_discovery_does_not_exec_stopped_containers(self):
        shared = {'Source': '/dev/shm', 'Destination': '/dev/shm', 'RW': True}
        containers = [
            {'Id': 'node', 'Config': {'Image': 'remnawave/node:3.4.3'}, 'Mounts': [shared],
             'HostConfig': {'NetworkMode': 'host'}, 'State': {'Running': False}},
            {'Id': 'nginx', 'Config': {'Image': 'nginx:1.30'}, 'Mounts': [shared,
             {'Source': str(self.t.rt.nginx_path), 'Destination': '/etc/nginx/conf.d/default.conf', 'RW': True}],
             'HostConfig': {'NetworkMode': 'host'}, 'State': {'Running': False}},
            {'Id': 'panel', 'Config': {'Image': 'remnawave/backend:3.4.7'},
             'HostConfig': {'PortBindings': {'3000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '3000'}]}}}]
        def cmd(args, *a, **kw):
            if 'inspect' in args:
                return types.SimpleNamespace(stdout=json.dumps(containers))
            if args == ['docker', 'ps', '-aq']:
                return types.SimpleNamespace(stdout='node nginx panel')
            raise AssertionError('Recovery unexpectedly executes a running-service prerequisite')
        with patch.object(s, 'command', side_effect=cmd):
            rt = s.Runtime({'mode': 'restore', 'panel_api_token': 'synthetic-token'})
        self.assertEqual(rt.api, 'http://127.0.0.1:3000/api')
        self.assertIsNone(rt.xray)

    def test_symlink_nginx_include_is_kept_in_staged_validation(self):
        rt = object.__new__(s.Runtime)
        rt.nginx = {'Id': 'nginx'}
        rt.nginx_inside = '/etc/nginx/conf.d/default.conf'
        staged = []
        def cmd(args, data=None, **kw):
            if args[-1] == '/etc/nginx/nginx.conf':
                out = 'events {} http { include /etc/nginx/conf.d/*.conf; }'
            elif 'find' in args:
                self.assertIn('-L', args)
                self.assertNotIn('-type', args)
                out = rt.nginx_inside + '\n/etc/nginx/conf.d/linked.conf\n'
            elif 'mktemp' in args:
                out = '/tmp/egames-nginx-Ab123.conf'
            else:
                out = ''
            if data:
                staged.append(data)
            return types.SimpleNamespace(stdout=out, returncode=0)
        with patch.object(s, 'command', side_effect=cmd):
            rt.validate_nginx(self.t.rt.nginx_text)
        self.assertIn('include /etc/nginx/conf.d/linked.conf;', staged[0])

    def test_file_certificate_mount_blocks_apply_before_loading_secrets(self):
        rt = object.__new__(s.Runtime)
        rt.cfg = {'mode': 'install'}
        rt.nginx_text = self.t.rt.nginx_text
        rt.nginx = {'Id': 'nginx', 'Mounts': [{'Destination': '/etc/nginx/ssl/example/fullchain.pem'}]}
        with self.assertRaisesRegex(RuntimeError, 'pin old inodes'):
            rt.certificate('node.example.com')

    def test_new_external_reference_prevents_cascading_profile_rollback(self):
        p = self.t.plan()
        self.t.apply(p)
        new_id = self.t.api.profile['inbounds'][-1]['uuid']
        self.t.api.hosts.append({'uuid': 'external', 'inbound': {
            'configProfileUuid': p['profile']['uuid'], 'configProfileInboundUuid': new_id}})
        with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE'):
            s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertIn(new_id, [i['uuid'] for i in self.t.api.profile['inbounds']])


class SecretInputTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'POSIX ownership/modes')
    def test_permissions_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'token'
            path.write_text('synthetic-secret')
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, 'owner-only'):
                s.secret_text(path)
            path.chmod(0o600)
            self.assertEqual(s.secret_text(path), 'synthetic-secret')
            with patch.object(s.os, 'geteuid', return_value=path.stat().st_uid + 1):
                with self.assertRaisesRegex(RuntimeError, 'owner-only'):
                    s.secret_text(path)
            link = Path(tmp) / 'link'
            link.symlink_to(path)
            with self.assertRaisesRegex(RuntimeError, 'symlinks'):
                s.secret_text(link)


if __name__ == '__main__':
    unittest.main()
