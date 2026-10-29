"""Configuration-derived tags and explicit reference migration (no credential edits)."""
import copy


def effective_flow(inbound):
    """Panel 3.4.7 getVlessFlow semantics, including explicit empty override."""
    if inbound.get('protocol') != 'vless' or not isinstance(inbound.get('settings'), dict):
        return ''
    settings = inbound['settings']
    if 'flow' in settings:
        return 'xtls-rprx-vision' if settings['flow'] == 'xtls-rprx-vision' else ''
    stream = inbound.get('streamSettings', {})
    return 'xtls-rprx-vision' if (stream.get('security') in ('tls', 'reality') and
                                stream.get('network') in ('raw', 'tcp')) else ''


def descriptive_tag(inbound, *, spaced=False):
    protocol = inbound['protocol']
    stream = inbound.get('streamSettings', {})
    network = stream.get('network', 'raw')
    names = {'vless': 'Vless', 'trojan': 'Trojan', 'shadowsocks': 'Shadowsocks', 'hysteria': 'Hysteria2'}
    suffix = ' -' if spaced else '-'
    if protocol not in names:
        raise ValueError('Unsupported managed protocol: ' + protocol)
    if protocol == 'hysteria':
        if inbound.get('settings', {}).get('version') != 2:
            raise ValueError('Expected Hysteria version 2')
        return 'Hysteria2-QUIC' + suffix + 'udp'
    if protocol == 'shadowsocks':
        networks = set(inbound.get('settings', {}).get('network', 'tcp,udp').split(','))
        if not networks or networks - {'tcp', 'udp'}:
            raise ValueError('Unknown Shadowsocks network')
        net = '+'.join(n for n in ('tcp', 'udp') if n in networks)
        return 'Shadowsocks-' + net.upper() + suffix + net
    transport = {'ws': 'WS', 'xhttp': 'XHTTP', 'grpc': 'gRPC', 'raw': 'TCP', 'tcp': 'TCP'}.get(network)
    if transport is None:
        raise ValueError('Unsupported managed transport: ' + network)
    if network in ('raw', 'tcp') and stream.get('security') == 'reality':
        transport = 'Vision' if effective_flow(inbound) else 'Reality'
    return names[protocol] + '-' + transport + suffix + 'tcp'


def allocate(base, occupied):
    tag, suffix = base, 2
    while tag in occupied:
        tag = f'{base}-{suffix}'
        suffix += 1
    occupied.add(tag)
    return tag


def rename_config(config, mapping):
    """Only inbound declarations and inboundTag references; outbound tags are separate."""
    result = copy.deepcopy(config)
    for inbound in result.get('inbounds', []):
        inbound['tag'] = mapping.get(inbound['tag'], inbound['tag'])
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'inboundTag':
                    if not isinstance(child, list) or not all(isinstance(t, str) for t in child):
                        raise ValueError('Expected inboundTag array')
                    value[key] = [mapping.get(t, t) for t in child]
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(result)
    tags = [i['tag'] for i in result.get('inbounds', [])]
    if len(tags) != len(set(tags)):
        raise ValueError('Duplicate inbound tags')
    for rule in result.get('routing', {}).get('rules', []):
        if set(rule.get('inboundTag', [])) - set(tags):
            raise ValueError('Dangling routing inboundTag')
    return result


def migration_mapping(config, managed, occupied=()):
    owned = set(managed)
    used = set(occupied) | {i['tag'] for i in config['inbounds'] if i['tag'] not in owned}
    mapping = {}
    for inbound in config['inbounds']:
        old = inbound['tag']
        if old in owned:
            mapping[old] = allocate(descriptive_tag(inbound), used)
    if owned - set(mapping):
        raise ValueError('Managed inbound missing from profile')
    return mapping
