"""Durable API migration; Panel regenerates UUIDs when inbound tags change.

Never edit generated Node files or the database. Snapshot remains sufficient for
rollback even if a profile PATCH succeeded but its HTTP reply was lost.
"""
import copy
import json
from pathlib import Path
import time

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


def restore_bindings(client, snapshot, mapping):
    from egames_safe import active_ids, unwrap_list
    profile = client.get('/config-profiles/' + snapshot['profile']['uuid'])
    ids = {i['tag']: i['uuid'] for i in profile['inbounds']}
    old = {i['uuid']: ids[mapping.get(i['tag'], i['tag'])] for i in snapshot['profile']['inbounds']}
    affected = {i['uuid'] for i in snapshot['profile']['inbounds'] if i['tag'] in mapping}
    for squad in snapshot['squads']:
        members = [i['uuid'] for i in squad.get('inbounds', [])]
        if affected.intersection(members):
            client.patch('/internal-squads', {'uuid': squad['uuid'], 'inbounds': [old.get(i, i) for i in members]})
    for node in snapshot['nodes']:
        members = active_ids(node)
        if affected.intersection(members):
            client.patch('/nodes', {'uuid': node['uuid'], 'configProfile': {
                'activeConfigProfileUuid': node['configProfile']['activeConfigProfileUuid'],
                'activeInbounds': [old.get(i, i) for i in members]}})
    for host in snapshot['hosts']:
        binding = host.get('inbound') or {}
        iid = binding.get('configProfileInboundUuid')
        if iid in affected:
            client.patch('/hosts', {'uuid': host['uuid'], 'inbound': {
                **binding, 'configProfileInboundUuid': old[iid]}})
    # Verify all relations, including intentionally excluded/disabled endpoints.
    hosts = {h['uuid']: h for h in unwrap_list(client.get('/hosts'), 'hosts')}
    for h in snapshot['hosts']:
        expected = copy.deepcopy(h.get('inbound'))
        if expected and expected.get('configProfileInboundUuid') in affected:
            expected['configProfileInboundUuid'] = old[expected['configProfileInboundUuid']]
        if hosts[h['uuid']].get('inbound') != expected:
            raise RuntimeError('Host binding read-back mismatch')
    for path, key, saved in (('/nodes', 'nodes', snapshot['nodes']), ('/internal-squads', 'internalSquads', snapshot['squads'])):
        current = {x['uuid']: x for x in unwrap_list(client.get(path), key)}
        for item in saved:
            members = active_ids(item) if key == 'nodes' else [i['uuid'] for i in item.get('inbounds', [])]
            actual = active_ids(current[item['uuid']]) if key == 'nodes' else [i['uuid'] for i in current[item['uuid']].get('inbounds', [])]
            if set(actual) != {old.get(i, i) for i in members}:
                raise RuntimeError('Membership read-back mismatch')


def rollback(client, rt, directory, snapshot):
    from egames_safe import private_json, profile_patch
    client.patch('/config-profiles', profile_patch(snapshot['profile'], snapshot['profile']['config']))
    # The original UUIDs may no longer exist: resolve original tags again.
    restore_bindings(client, snapshot, {tag: tag for tag in snapshot['mapping']})
    if client.get('/config-profiles/' + snapshot['profile']['uuid'])['config'] != snapshot['profile']['config']:
        raise RuntimeError('Rollback config mismatch')
    verify_runtime(client, rt, {**snapshot, 'config': snapshot['profile']['config'],
                               'mapping': {t: t for t in snapshot['mapping']}})
    private_json(Path(directory) / 'state.json', snapshot['state'])
    snapshot['status'] = 'rolled_back'
    private_json(Path(directory) / 'tag-migration.json', snapshot)


def migrate(client, rt, directory, state):
    from egames_safe import private_json, profile_patch
    directory = Path(directory)
    journal = directory / 'tag-migration.json'
    if journal.exists() and json.loads(journal.read_text())['status'] not in ('committed', 'rolled_back'):
        raise RuntimeError('Unfinished tag migration; use tag_migration.py --restore')
    snapshot = prepare(client, state)
    from egames_safe import reviewed_plugin
    node = next(n for n in snapshot['nodes'] if n['uuid'] == state['node_uuid'])
    reviewed_plugin(client, node, rt)
    rt.validate_xray(snapshot['config'])
    rt.validate_nginx(rt.nginx_text)
    snapshot['nginx'] = rt.nginx_text
    snapshot['status'] = 'pending'
    backup = directory / 'backups' / f'tags-{time.time_ns()}.json'
    private_json(backup, snapshot)
    private_json(journal, snapshot)
    attempted = False
    try:
        latest = client.get('/config-profiles/' + state['profile_uuid'])
        if latest['config'] != snapshot['profile']['config']:
            raise RuntimeError('Concurrent profile change')
        for path, key, saved in (('/nodes', 'nodes', snapshot['nodes']), ('/hosts', 'hosts', snapshot['hosts']),
                                 ('/internal-squads', 'internalSquads', snapshot['squads'])):
            from egames_safe import unwrap_list, writable_node, writable_squad
            current = unwrap_list(client.get(path), key)
            normalize = writable_node if key == 'nodes' else writable_squad if key == 'internalSquads' else lambda x: x
            if {x['uuid']: normalize(x) for x in current} != {x['uuid']: normalize(x) for x in saved}:
                raise RuntimeError('Concurrent binding change')
        attempted = True  # A lost reply can still mean the PATCH was committed.
        client.patch('/config-profiles', profile_patch(snapshot['profile'], snapshot['config']))
        restore_bindings(client, snapshot, snapshot['mapping'])
        if client.get('/config-profiles/' + state['profile_uuid'])['config'] != snapshot['config']:
            raise RuntimeError('Migrated config read-back mismatch')
        verify_runtime(client, rt, snapshot)
        new = copy.deepcopy(state)
        mapping = snapshot['mapping']
        new['tags'] = [mapping[t] for t in state['tags']]
        for field in ('paths', 'host_ids'):
            new[field] = {mapping.get(t, t): v for t, v in state.get(field, {}).items()}
        new['inbounds'] = {i['tag']: i for i in snapshot['config']['inbounds'] if i['tag'] in new['tags']}
        new['tag_labels'] = {tag.removeprefix('EGADDON-'): mapping[tag] for tag in state['tags']}
        # Old transaction journals contain deleted inbound UUIDs. Keep them on
        # disk for audit, but never replay them as an installer uninstall.
        new['pre_tag_migration_history'] = state.get('history', [])
        new['history'] = []
        new['tag_migration_backup'] = str(backup)
        private_json(directory / 'state.json', new)
        snapshot['status'] = 'committed'
        private_json(journal, snapshot)
        return new
    except BaseException:
        if attempted:
            rollback(client, rt, directory, snapshot)
        else:
            snapshot['status'] = 'rolled_back'
            private_json(journal, snapshot)
        raise


def verify_runtime(client, rt, snapshot):
    from egames_safe import occupied_ports, unwrap_list, command
    expected = set()
    for ib in snapshot['config']['inbounds']:
        if ib['tag'] not in snapshot['mapping'].values():
            continue
        proto = ib['protocol']
        nets = {'udp'} if proto == 'hysteria' else ({'tcp', 'udp'} if proto == 'shadowsocks' else {'tcp'})
        expected.update((n, ib['port']) for n in nets)
    for _ in range(20):
        node = next(n for n in unwrap_list(client.get('/nodes'), 'nodes') if n['uuid'] == snapshot['state']['node_uuid'])
        if node.get('isConnected') and expected.issubset(occupied_ports()):
            command(['docker', 'exec', rt.nginx['Id'], 'nginx', '-t'])
            return
        time.sleep(2)
    raise RuntimeError('Migrated node/listeners failed health check')


if __name__ == '__main__':
    import argparse
    from egames_safe import Runtime, lock, read_state
    from remnawave_injector import RemnawaveClient
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore', action='store_true', required=True)
    parser.add_argument('--state-dir', default='/var/lib/egames-injector')
    args = parser.parse_args()
    state = read_state(args.state_dir)
    rt = Runtime({'node_uuid': state['node_uuid']})
    client = RemnawaveClient(rt.api, rt.token)
    with lock(args.state_dir):
        snapshot = json.loads((Path(args.state_dir) / 'tag-migration.json').read_text())
        rollback(client, rt, args.state_dir, snapshot)
    print('Tag migration rollback verified; re-run installer check.')
