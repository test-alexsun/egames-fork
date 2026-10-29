"""CODEX_03 regressions. Synthetic API is not real Panel acceptance."""
import copy
from contextlib import ExitStack, nullcontext, redirect_stdout
import io
import json
from pathlib import Path
import types
import unittest
import uuid
from unittest.mock import patch

import egames_safe as s
import test_safe as fixtures


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.t = fixtures.SafeTests()
        self.t.setUp()
        self.t.rt.api, self.t.rt.token, self.t.rt.cookie = 'http://127.0.0.1/api', 'synthetic', ''
        self.addCleanup(self.t.doCleanups)

    def cli(self, mode, yes=True):
        t = self.t
        t.rt.api, t.rt.token, t.rt.cookie = 'http://127.0.0.1/api', 'synthetic', ''
        real_os, real_json, real_read = s.os, s.private_json, s.read_state
        real_recover = s.recover
        def portable_json(path, value):
            # Only Linux platform/permission discovery is replaced on Windows.
            with patch.object(s, 'os', real_os):
                real_json(path, value)
        def portable_read(path):
            with patch.object(s, 'os', real_os):
                return real_read(path)
        def portable_recover(*args):
            with patch.object(s, 'os', real_os):
                return real_recover(*args)
        with ExitStack() as stack:
            for obj, key, value in (
                (s, 'os', types.SimpleNamespace(name='posix', geteuid=lambda: 0)),
                (s.platform, 'freedesktop_os_release', lambda: {'ID': 'debian', 'VERSION_ID': '13'}),
                (s, 'Runtime', lambda cfg: t.rt),
                (s, 'RemnawaveClient', lambda *a, **kw: t.api),
                (s, 'lock', lambda *a: nullcontext()),
                (s, 'secret_text', lambda p: Path(p).read_text()),
                (s, 'sys_stdin_tty', lambda: True),
                (s, 'occupied_ports', lambda: {('tcp', 443)}),
                (s, 'verify', lambda *a: None)):
                stack.enter_context(patch.object(obj, key, value))
            stack.enter_context(patch.object(s.Transaction, 'firewall'))
            stack.enter_context(patch.object(s, 'private_json', portable_json))
            stack.enter_context(patch.object(s, 'read_state', portable_read))
            stack.enter_context(patch.object(s, 'recover', portable_recover))
            stack.enter_context(patch('builtins.input', return_value='APPLY'))
            stack.enter_context(redirect_stdout(io.StringIO()))
            return s.run({'mode': mode, 'state_dir': t.tmp.name, 'yes': yes})

    def test_public_install_repeat_repair_update_backup_restore_uninstall(self):
        original = copy.deepcopy(self.t.api.profile)
        for mode in ('dry-run', 'check', 'status', 'backup', 'install'):
            self.assertEqual(self.cli(mode), 0)
        installed = copy.deepcopy(self.t.api.hosts)
        for mode in ('install', 'repair', 'update'):
            self.t.rt.nginx_text = self.t.rt.nginx_path.read_text()
            self.assertEqual(self.cli(mode), 0)
            self.assertEqual(self.t.api.hosts, installed)
        self.assertEqual(self.cli('restore', yes=False), 0)
        self.assertEqual(self.cli('uninstall'), 0)
        self.assertEqual(self.t.api.profile, original)
        self.assertEqual(len(self.t.api.hosts), 1)
        self.assertEqual(s.read_state(self.t.tmp.name)['tags'], [])
        self.assertEqual(self.cli('restore'), 0)
        self.t.rt.nginx_text = self.t.rt.nginx_path.read_text()
        self.assertEqual(self.cli('install'), 0)
        self.assertEqual(self.cli('uninstall', yes=False), 0)

    def test_summary_is_typed_and_redacted(self):
        data = {'nginx_path': '/etc/nginx.conf', 'operations': [
            {'kind': 'nginx', 'before': 'SECRET OLD', 'after': 'SECRET NEW'},
            {'kind': 'ufw', 'rule': '443/udp'},
            {'kind': 'host', 'after': {'uuid': 'host-id', 'password': 'SECRET'}}]}
        summary = s.rollback_summary(data)
        self.assertEqual(summary[0]['uuid'], 'host-id')
        self.assertEqual(summary[1]['rule'], '443/udp')
        self.assertEqual(summary[2]['path'], '/etc/nginx.conf')
        self.assertNotIn('SECRET', json.dumps(summary))

    def test_public_restore_with_nginx_api_and_ufw_operations(self):
        self.t.apply(self.t.plan())
        path = Path(self.t.tmp.name) / 'journal.json'
        data = json.loads(path.read_text())
        data['operations'].append({'kind': 'ufw', 'rule': '443/udp', 'done': True})
        s.private_json(path, data)
        status = ['Status: active\n443/udp ALLOW Anywhere # ' + s.OWNER]
        def command(args, **kwargs):
            if args[:4] == ['ufw', '--force', 'delete', 'allow']:
                status[0] = 'Status: active\n'
            return types.SimpleNamespace(stdout='', returncode=0)
        with patch.object(s, 'firewall_status', side_effect=lambda: status[0]), \
                patch.object(s, 'command', side_effect=command):
            self.assertEqual(self.cli('restore'), 0)
        self.assertEqual(status[0], 'Status: active\n')
        self.assertEqual(len(self.t.api.profile['inbounds']), 1)

    def test_new_host_post_uuids_are_durable_and_never_reused(self):
        request = self.t.api.request
        def fresh(method, path, body=None):
            result = request(method, path, body)
            if method == 'POST':
                self.t.api.hosts[-1]['uuid'] = str(uuid.uuid4())
                return copy.deepcopy(self.t.api.hosts[-1])
            return result
        self.t.api.request = fresh
        self.t.apply(self.t.plan())
        first = set(s.read_state(self.t.tmp.name)['hosts'])
        s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.t.apply(self.t.plan())
        second = set(s.read_state(self.t.tmp.name)['hosts'])
        self.assertTrue(first.isdisjoint(second))
        s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertEqual(len(self.t.api.hosts), 1)

    def test_metadata_failure_before_and_after_each_final_write_retries(self):
        for target in ('state.json', 'history', 'terminal'):
            for after in (False, True):
                with self.subTest(target=target, after=after):
                    self.t.rt.nginx_text = self.t.rt.nginx_path.read_text()
                    self.t.state = s.read_state(self.t.tmp.name)
                    self.t.apply(self.t.plan())
                    real = s.private_json
                    failed = False
                    def fault(path, value):
                        nonlocal failed
                        hit = ((target == 'state.json' and Path(path).name == target) or
                               (target == 'history' and Path(path).parent.name == 'transactions') or
                               (target == 'terminal' and Path(path).name == 'journal.json' and
                                value.get('status') == 'rolled_back'))
                        if hit and not failed:
                            failed = True
                            if after:
                                real(path, value)
                            raise OSError('simulated ENOSPC/crash boundary')
                        real(path, value)
                    with patch.object(s, 'private_json', side_effect=fault):
                        with self.assertRaises(OSError):
                            s.recover(self.t.api, self.t.rt, self.t.tmp.name)
                    for _ in range(2):
                        s.recover(self.t.api, self.t.rt, self.t.tmp.name)
                    self.assertEqual(s.read_state(self.t.tmp.name)['tags'], [])
                    self.assertEqual(len(self.t.api.profile['inbounds']), 1)
                    journal = json.loads((Path(self.t.tmp.name) / 'journal.json').read_text())
                    self.assertEqual(journal['status'], 'rolled_back')

    def test_nginx_reload_retry_tracks_loaded_configuration_separately(self):
        before = self.t.rt.nginx_text
        loaded = [before]
        def reload_ok():
            loaded[0] = self.t.rt.nginx_path.read_text()
        self.t.rt.reload = reload_ok
        tx = s.Transaction(self.t.api, self.t.rt, self.t.tmp.name, self.t.state)
        tx.nginx(before, '# changed\n' + before)
        with patch.object(self.t.rt, 'reload', side_effect=RuntimeError('signal failed')):
            with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE'):
                tx.rollback()
        self.assertNotEqual(loaded[0], before)
        self.assertEqual(self.t.rt.nginx_path.read_text(), before)
        s.recover(self.t.api, self.t.rt, self.t.tmp.name)
        self.assertEqual(loaded[0], before)

    def test_host_replacement_or_extra_fields_block_deletion(self):
        self.t.apply(self.t.plan())
        original = copy.deepcopy(self.t.api.hosts[-1])
        for change in ({'uuid': 'operator-replacement'}, {'operatorField': 'new relation'}):
            self.t.api.hosts[-1] = {**original, **change}
            with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE'):
                s.recover(self.t.api, self.t.rt, self.t.tmp.name)
            self.assertIn(self.t.api.hosts[-1], self.t.api.hosts)
            self.assertFalse(any(m == 'DELETE' for m, _, _ in self.t.api.writes))

    def test_duplicate_cardinality_blocks_all_writes_and_ownership_adoption(self):
        self.t.apply(self.t.plan())
        self.t.state = s.read_state(self.t.tmp.name)
        self.t.rt.nginx_text = self.t.rt.nginx_path.read_text()
        original_hosts = copy.deepcopy(self.t.api.hosts)
        for owner_tag in (True, False):
            for reverse in (True, False):
                for saved_id in (True, False):
                    state = copy.deepcopy(self.t.state)
                    if not saved_id:
                        self.t.state.pop('host_ids', None)
                    duplicate = {**copy.deepcopy(original_hosts[-1]), 'uuid': 'operator-copy'}
                    if not owner_tag:
                        duplicate['tags'] = []
                    self.t.api.hosts = copy.deepcopy(original_hosts) + [duplicate]
                    if reverse:
                        self.t.api.hosts.reverse()
                    self.t.api.writes.clear()
                    with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
                        self.t.apply(self.t.plan())
                    self.assertFalse(self.t.api.writes)
                    self.t.state = state
        self.assertNotIn('operator-copy', s.read_state(self.t.tmp.name)['hosts'])


if __name__ == '__main__':
    unittest.main()
