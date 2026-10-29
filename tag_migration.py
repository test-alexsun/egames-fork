"""Read-only tag proposal. Remnawave 3.4.7 replaces UUIDs on tag rename.

Mutating migration and legacy restore are deliberately unavailable because
UUID preservation is a required invariant. No direct database or runtime edits.
"""
import copy
import json
from pathlib import Path

from inbound_tags import migration_mapping, rename_config


def prepare(client, state):
    from egames_safe import unwrap_list, REVIEWED_PANEL, REVIEWED_NODE
    if client.get('/system/metadata')['version'].lstrip('v') not in REVIEWED_PANEL:
        raise RuntimeError('Panel version has no reviewed tag migration adapter')
    nodes = unwrap_list(client.get('/nodes'), 'nodes')
    node = next(n for n in nodes if n['uuid'] == state['node_uuid'])
    if (node.get('versions') or {}).get('node', '').lstrip('v') not in REVIEWED_NODE or not node.get('isConnected'):
        raise RuntimeError('Unsupported/disconnected Node')
    if node['configProfile']['activeConfigProfileUuid'] != state['profile_uuid']:
        raise RuntimeError('Active profile changed')
    if any(n['uuid'] != node['uuid'] and n.get('configProfile', {}).get('activeConfigProfileUuid') == state['profile_uuid'] for n in nodes):
        raise RuntimeError('Profile shared with another Node')
    profile = client.get('/config-profiles/' + state['profile_uuid'])
    if profile['config'].get('snippets') or any(i.get('settings', {}).get('clients') for i in profile['config']['inbounds']):
        raise RuntimeError('Generated snippets or manual clients require dedicated migration')
    for ib in profile['config']['inbounds']:
        if ib['tag'] in state['tags'] and state.get('inbounds', {}).get(ib['tag']) != ib:
            raise RuntimeError('Managed inbound drift blocks migration')
    profiles = unwrap_list(client.get('/config-profiles'), 'configProfiles')
    occupied = {i['tag'] for p in profiles if p['uuid'] != profile['uuid'] for i in p['inbounds']}
    mapping = migration_mapping(profile['config'], state['tags'], occupied)
    config = rename_config(profile['config'], mapping)
    templates = client.get('/subscription-templates')
    if any(tag in json.dumps(templates) for tag in mapping):
        raise RuntimeError('Subscription template references require a dedicated migration')
    return {'profile': profile, 'config': config, 'mapping': mapping,
            'nodes': nodes,
            'hosts': unwrap_list(client.get('/hosts'), 'hosts'),
            'squads': unwrap_list(client.get('/internal-squads'), 'internalSquads'),
            'state': copy.deepcopy(state)}


def migrate(client, rt, directory, state):
    """Fail closed: Panel 3.4.7 has no inbound UUID-preserving rename API."""
    raise RuntimeError('Technical tag rename is blocked: Panel regenerates inbound UUIDs; retain tags and use Host display names')


def rollback(client, rt, directory, snapshot):
    """Old snapshots lack revision/epoch guards and contain invalidated UUIDs."""
    raise RuntimeError('Legacy tag restore is blocked: UUID history and external drift cannot be proven safe; preserve snapshot for independent recovery')


def verify_runtime(client, rt, snapshot):
    raise RuntimeError('Tag mutation is unavailable in the UUID-preserving adapter')


if __name__ == '__main__':
    import argparse
    from egames_safe import Runtime, read_state
    from remnawave_injector import RemnawaveClient
    parser = argparse.ArgumentParser(description='Read-only technical tag migration proposal; UUID-changing writes are blocked')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--plan', action='store_true')
    modes.add_argument('--restore', action='store_true')
    parser.add_argument('--state-dir', default='/var/lib/egames-injector')
    args = parser.parse_args()
    if args.restore:
        parser.exit(1, 'Legacy restore blocked: Panel rename replaces UUIDs. No API writes performed.\n')
    state = read_state(args.state_dir)
    rt = Runtime({'node_uuid': state['node_uuid']})
    client = RemnawaveClient(rt.api, rt.token, cookie=rt.cookie)
    proposal = prepare(client, state)
    print(json.dumps({'mapping': proposal['mapping'], 'canApply': False,
                      'reason': 'Panel 3.4.7 replaces UUIDs on rename'}, indent=2))
