import copy
import unittest

from inbound_tag_plan import build_plan


def sample():
    return {'profiles': [{'uuid': 'p1', 'inbounds': [{'uuid': 'i1', 'tag': 'OLD'}]},
                         {'uuid': 'p2', 'inbounds': [{'uuid': 'i2', 'tag': 'OLD2'}]}],
            'hosts': [{'uuid': 'h1', 'remark': '🇫🇮 | VLESS | WS TLS',
                       'inbound': {'configProfileUuid': 'p1', 'configProfileInboundUuid': 'i1'}},
                      {'uuid': 'h2', 'remark': '🇩🇪 | VLESS | WS TLS',
                       'inbound': {'configProfileUuid': 'p2', 'configProfileInboundUuid': 'i2'}}],
            'nodes': [{'uuid': 'n1', 'configProfile': {'activeConfigProfileUuid': 'p1', 'activeInbounds': [{'uuid': 'i1'}]}},
                      {'uuid': 'n2', 'configProfile': {'activeConfigProfileUuid': 'p2', 'activeInbounds': ['i2']}}],
            'squads': [{'uuid': 's1', 'inbounds': [{'uuid': 'i1'}, {'uuid': 'i2'}]}]}


class PlanTests(unittest.TestCase):
    def test_preview_preserves_input_and_captures_all_references(self):
        data = sample()
        before = copy.deepcopy(data)
        plan = build_plan(data)
        self.assertEqual(data, before)
        self.assertEqual(plan[0]['new_tag'], '🇫🇮 | VLESS | WS TLS')
        self.assertEqual((plan[0]['hosts'], plan[0]['nodes'], plan[0]['squads']), (['h1'], ['n1'], ['s1']))
        self.assertEqual(plan[1]['nodes'], ['n2'])

    def test_collision_and_ambiguous_host_fail_closed(self):
        data = sample()
        data['hosts'][1]['remark'] = data['hosts'][0]['remark']
        with self.assertRaisesRegex(ValueError, 'conflict'):
            build_plan(data)
        data = sample()
        host = copy.deepcopy(data['hosts'][0])
        host['remark'] = 'other'
        data['hosts'].append(host)
        with self.assertRaisesRegex(ValueError, 'Multiple Host names'):
            build_plan(data)

    def test_collision_with_unchanged_inbound_is_rejected(self):
        data = sample()
        data['profiles'][1]['inbounds'][0]['tag'] = data['hosts'][0]['remark']
        data['hosts'].pop()
        with self.assertRaisesRegex(ValueError, 'conflict'):
            build_plan(data)


if __name__ == '__main__':
    unittest.main()
