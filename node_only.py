"""Read-only remote-Panel adapter. No local backend discovery or API mutations."""
import json
import re
import socket

from egames_safe import (REVIEWED_PANEL, REVIEWED_NODE, active_ids, command,
                         select_one, unwrap_list)


def inspect(client, rt, cfg):
    if not cfg.get('node_uuid') or not cfg.get('token_file') or not cfg.get('panel_api_url', '').startswith('https://'):
        raise RuntimeError('Node-only requires explicit HTTPS API, private token_file and Node UUID')
    version = client.get('/system/metadata').get('version', '').lstrip('v')
    if version not in REVIEWED_PANEL:
        raise RuntimeError('Remote Panel version has no reviewed adapter')
    nodes = unwrap_list(client.get('/nodes'), 'nodes')
    node = select_one(nodes, 'remote Panel Node', cfg['node_uuid'])
    if (node.get('versions') or {}).get('node', '').lstrip('v') not in REVIEWED_NODE:
        raise RuntimeError('Remote Node version has no reviewed adapter')
    local = {'127.0.0.1', '::1'}
    for interface in json.loads(command(['ip', '-j', 'address', 'show']).stdout):
        local.update(a['local'] for a in interface.get('addr_info', []))
    try:
        addresses = {a[4][0] for a in socket.getaddrinfo(node['address'], None)}
    except OSError:
        raise RuntimeError('Cannot resolve selected Node management address') from None
    if not addresses or not addresses.issubset(local):
        raise RuntimeError('Selected remote Node UUID does not identify this VPS unambiguously')
    core = re.search(r'Xray\s+(\d+\.\d+\.\d+)', rt.version)
    if not core or core[1] != node.get('versions', {}).get('xray', '').lstrip('v'):
        raise RuntimeError('Remote Panel core report differs from local Xray')
    pid = node['configProfile']['activeConfigProfileUuid']
    profile = client.get('/config-profiles/' + pid)
    rt.validate_xray(profile['config'])
    rt.validate_nginx(rt.nginx_text)
    hosts = unwrap_list(client.get('/hosts'), 'hosts')
    ids = set(active_ids(node))
    tags = [i['tag'] for i in profile['inbounds'] if i['uuid'] in ids]
    return {'topology': 'node-only', 'canApply': False, 'nodeUuid': node['uuid'],
            'profileUuid': pid, 'connected': bool(node.get('isConnected')),
            'activeTags': tags, 'hosts': sum((h.get('inbound') or {}).get('configProfileUuid') == pid for h in hosts),
            'sharedProfile': any(n['uuid'] != node['uuid'] and n.get('configProfile', {}).get('activeConfigProfileUuid') == pid for n in nodes),
            'reason': 'Distributed apply/recovery requires disposable two-host acceptance; inventory only'}
