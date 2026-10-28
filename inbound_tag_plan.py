#!/usr/bin/env python3
"""Offline-only migration preview. Never calls an API or writes configuration."""
import argparse
import json
from pathlib import Path


def build_plan(snapshot):
    profiles = snapshot['profiles']
    hosts = snapshot['hosts']
    nodes = snapshot['nodes']
    squads = snapshot['squads']
    all_tags = [i['tag'] for p in profiles for i in p['inbounds']]
    if len(all_tags) != len(set(all_tags)):
        raise ValueError('Current inbound tags are not globally unique')
    by_inbound = {}
    for host in hosts:
        binding = host.get('inbound') or {}
        key = (binding.get('configProfileUuid'), binding.get('configProfileInboundUuid'))
        if all(key):
            by_inbound.setdefault(key, []).append(host)
    changes = []
    for profile in profiles:
        for inbound in profile['inbounds']:
            uid, tag = inbound['uuid'], inbound['tag']
            matching = by_inbound.get((profile['uuid'], uid), [])
            if not matching:
                continue
            names = {h['remark'] for h in matching}
            if len(names) != 1:
                raise ValueError('Multiple Host names for the same inbound; choose a name explicitly')
            name = names.pop()
            if not isinstance(name, str) or not name.strip():
                raise ValueError('Invalid Host name')
            changes.append({'profile_uuid': profile['uuid'], 'old_uuid': uid,
                            'old_tag': tag, 'new_tag': name,
                            'hosts': [h['uuid'] for h in matching],
                            'nodes': [n['uuid'] for n in nodes if
                                      n.get('configProfile', {}).get('activeConfigProfileUuid') == profile['uuid']
                                      and uid in [v if isinstance(v, str) else v['uuid'] for v in
                                                  n['configProfile'].get('activeInbounds', [])]],
                            'squads': [s['uuid'] for s in squads if uid in
                                       [v if isinstance(v, str) else v['uuid'] for v in s.get('inbounds', [])]]})
    desired = [x['new_tag'] for x in changes]
    untouched = set(all_tags) - {x['old_tag'] for x in changes}
    if len(desired) != len(set(desired)) or set(desired) & untouched:
        raise ValueError('Proposed tags conflict globally')
    return changes


def main():
    parser = argparse.ArgumentParser(description='Preview inbound tag migration from a local JSON snapshot; read-only')
    parser.add_argument('snapshot', type=Path)
    args = parser.parse_args()
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
        result = build_plan(snapshot)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, 'Cannot create plan: ' + str(exc) + '\n')
    print(json.dumps({'mode': 'READ ONLY', 'changes': result}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
