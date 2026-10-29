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

    def test_uuid_changing_migration_is_blocked_with_zero_writes(self):
        original = copy.deepcopy(self.api.__dict__)
        with self.assertRaisesRegex(RuntimeError, 'regenerates inbound UUIDs'):
            m.migrate(self.api, self.rt, self.tmp.name, self.state)
        self.assertEqual(self.api.__dict__, original)

    def test_restore_refuses_legacy_snapshots_and_all_external_drift(self):
        for change in ('dns', 'inbound', 'membership', 'host'):
            with self.subTest(change=change):
                snapshot = m.prepare(self.api, self.state)
                snapshot['status'] = 'committed'
                if change == 'dns':
                    self.api.profile['config']['dns'] = {'servers': ['9.9.9.9']}
                elif change == 'inbound':
                    self.api.profile['config']['inbounds'].append({'tag': 'external', 'port': 5555})
                elif change == 'membership':
                    self.api.squads[0]['inbounds'] = []
                else:
                    self.api.hosts[-1]['uuid'] = 'recreated-by-operator'
                original = copy.deepcopy(self.api.__dict__)
                with self.assertRaisesRegex(RuntimeError, 'Legacy tag restore is blocked'):
                    m.rollback(self.api, self.rt, self.tmp.name, snapshot)
                self.assertEqual(self.api.__dict__, original)

    def test_plan_is_read_only_and_checks_managed_drift(self):
        plan = m.prepare(self.api, self.state)
        self.assertIn('EGADDON-XHTTP', plan['mapping'])
        self.assertFalse(self.api.writes)
        self.api.profile['config']['inbounds'][-1]['port'] += 1
        with self.assertRaisesRegex(RuntimeError, 'drift'):
            m.prepare(self.api, self.state)

    def test_template_references_block_proposal(self):
        original = self.api.get
        self.api.get = lambda path: [{'template': {'inboundTag': ['EGADDON-XHTTP']}}] if path == '/subscription-templates' else original(path)
        with self.assertRaisesRegex(RuntimeError, 'template'):
            m.prepare(self.api, self.state)
        self.assertFalse(self.api.writes)

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
