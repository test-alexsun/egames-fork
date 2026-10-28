import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from inbound_tags import allocate, descriptive_tag, migration_mapping, rename_config
import tag_migration as m
from test_safe import API, Runtime
import egames_safe as s


class CascadingAPI(API):
    """Model actual Panel deletion semantics, including lost replies."""
    def request(self, method, path, body=None):
        previous = {i['uuid'] for i in self.profile['inbounds']}
        lose = self.lose_reply
        self.lose_reply = False
        super().request(method, path, body)
        if path == '/config-profiles':
            deleted = previous - {i['uuid'] for i in self.profile['inbounds']}
            for n in self.nodes:
                n['configProfile']['activeInbounds'] = [i for i in s.active_ids(n) if i not in deleted]
            for q in self.squads:
                q['inbounds'] = [i for i in q['inbounds'] if i['uuid'] not in deleted]
            for h in self.hosts:
                if (h.get('inbound') or {}).get('configProfileInboundUuid') in deleted:
                    h['inbound'] = {'configProfileUuid': None, 'configProfileInboundUuid': None}
        if lose:
            raise RuntimeError('Reply lost after commit')


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api = CascadingAPI()
        self.rt = Runtime(self.tmp.name)
        self.ib = {'tag': 'EGADDON-XHTTP', 'port': 12345, 'protocol': 'vless',
                   'settings': {'clients': [], 'decryption': 'none'},
                   'streamSettings': {'network': 'xhttp', 'xhttpSettings': {'path': '/keep/'}}}
        self.api.profile['config']['inbounds'].append(copy.deepcopy(self.ib))
        self.api.profile['inbounds'].append({'tag': self.ib['tag'], 'uuid': 'legacy'})
        self.api.profile['config']['routing'] = {'rules': [{'inboundTag': [self.ib['tag']], 'outboundTag': self.ib['tag']}]}
        self.api.nodes[0]['configProfile']['activeInbounds'].append('legacy')
        self.api.squads[0]['inbounds'].append({'uuid': 'legacy'})
        self.api.hosts.append({'uuid': 'managed-host', 'remark': 'Keep name', 'isDisabled': True,
                               'inbound': {'configProfileUuid': self.api.profile['uuid'], 'configProfileInboundUuid': 'legacy'}})
        self.state = {'owner': s.OWNER, 'profile_uuid': self.api.profile['uuid'], 'node_uuid': self.api.nodes[0]['uuid'],
                      'tags': [self.ib['tag']], 'inbounds': {self.ib['tag']: self.ib}, 'paths': {self.ib['tag']: '/keep/'},
                      'hosts': ['managed-host'], 'host_ids': {self.ib['tag']: 'managed-host'}, 'history': ['old.json']}
        self.health = patch.object(m, 'verify_runtime')
        self.health.start()
        self.addCleanup(self.health.stop)

    def test_api_cascade_rebound_and_only_tags_changed(self):
        before = copy.deepcopy(self.api.profile['config'])
        new = m.migrate(self.api, self.rt, self.tmp.name, self.state)
        mapping = {'EGADDON-XHTTP': 'Vless-XHTTP-tcp'}
        self.assertEqual(self.api.profile['config'], rename_config(before, mapping))
        self.assertEqual(new['paths'], {'Vless-XHTTP-tcp': '/keep/'})
        self.assertEqual(new['history'], [])
        h = self.api.hosts[-1]
        self.assertTrue(h['isDisabled'])
        self.assertEqual(h['remark'], 'Keep name')
        self.assertEqual(h['inbound']['configProfileInboundUuid'], 'iid-Vless-XHTTP-tcp')
        self.assertIn('iid-Vless-XHTTP-tcp', s.active_ids(self.api.nodes[0]))
        self.assertIn({'uuid': 'iid-Vless-XHTTP-tcp'}, self.api.squads[0]['inbounds'])
        self.assertEqual(self.api.profile['config']['routing']['rules'][0]['outboundTag'], 'EGADDON-XHTTP')

    def test_failure_and_lost_reply_restore_new_original_uuids(self):
        for lost in (False, True):
            with self.subTest(lost=lost):
                original = copy.deepcopy(self.api.profile['config'])
                if lost:
                    self.api.lose_reply = True
                else:
                    self.api.fail = '/hosts'
                with self.assertRaises(RuntimeError):
                    m.migrate(self.api, self.rt, self.tmp.name, self.state)
                self.assertEqual(self.api.profile['config'], original)
                self.assertEqual(self.api.hosts[-1]['inbound']['configProfileInboundUuid'], 'iid-EGADDON-XHTTP')
                self.assertEqual(json.loads((Path(self.tmp.name) / 'tag-migration.json').read_text())['status'], 'rolled_back')

    def test_drift_refused_before_api_write(self):
        self.api.profile['config']['inbounds'][-1]['port'] += 1
        with self.assertRaisesRegex(RuntimeError, 'drift'):
            m.migrate(self.api, self.rt, self.tmp.name, self.state)
        self.assertFalse(self.api.writes)

    def test_health_failure_rolls_back(self):
        with patch.object(m, 'verify_runtime', side_effect=[RuntimeError('health failed'), None]):
            with self.assertRaisesRegex(RuntimeError, 'health failed'):
                m.migrate(self.api, self.rt, self.tmp.name, self.state)
        self.assertEqual(self.api.profile['config']['inbounds'][-1]['tag'], 'EGADDON-XHTTP')

    def test_template_references_block_before_write(self):
        original = self.api.get
        self.api.get = lambda path: [{'template': {'inboundTag': ['EGADDON-XHTTP']}}] if path == '/subscription-templates' else original(path)
        with self.assertRaisesRegex(RuntimeError, 'template'):
            m.migrate(self.api, self.rt, self.tmp.name, self.state)
        self.assertFalse(self.api.writes)

    def test_concurrent_binding_edit_not_overwritten(self):
        original = self.api.get
        reads = 0
        def get(path):
            nonlocal reads
            if path == '/hosts':
                reads += 1
                if reads == 2:
                    self.api.hosts[-1]['remark'] = 'Operator edit'
            return original(path)
        self.api.get = get
        with self.assertRaisesRegex(RuntimeError, 'Concurrent'):
            m.migrate(self.api, self.rt, self.tmp.name, self.state)
        self.assertFalse(self.api.writes)
        self.assertEqual(self.api.hosts[-1]['remark'], 'Operator edit')

    def test_naming_and_unique_suffixes(self):
        used = set()
        tags = [allocate(descriptive_tag(self.ib), used) for _ in range(3)]
        self.assertEqual(tags, ['Vless-XHTTP-tcp', 'Vless-XHTTP-tcp-2', 'Vless-XHTTP-tcp-3'])
        self.assertEqual(descriptive_tag({'protocol': 'trojan', 'streamSettings': {'network': 'grpc'}}), 'Trojan-gRPC-tcp')
        self.assertEqual(descriptive_tag({'protocol': 'hysteria', 'settings': {'version': 2}}), 'Hysteria2-QUIC-udp')
        self.assertEqual(descriptive_tag({'protocol': 'shadowsocks'}), 'Shadowsocks-TCP+UDP-tcp+udp')

    def test_routing_dangling_and_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            rename_config({'inbounds': [self.ib], 'routing': {'rules': [{'inboundTag': ['absent']}]}}, {})
        with self.assertRaises(ValueError):
            rename_config({'inbounds': [self.ib, self.ib]}, {})

    def test_global_collision_and_untouched_baseline(self):
        plan = m.prepare(self.api, self.state)
        mapping = migration_mapping(plan['profile']['config'], self.state['tags'], ['Vless-XHTTP-tcp'])
        self.assertEqual(mapping[self.ib['tag']], 'Vless-XHTTP-tcp-2')
        self.assertEqual(plan['config']['inbounds'][0], plan['profile']['config']['inbounds'][0])


if __name__ == '__main__':
    unittest.main()
