"""LayerCloud routes, reasoning, tools and credential isolation; offline."""
from pathlib import Path
import json
import sys

root = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(root / 'src/gateway'), str(root / 'src/desktop')]
from provider_registry import PROVIDERS, MODELS, public_catalog
from core import GatewayCore
from provider_relay import limit_output
from chat_bridge import prepare_chat, response_events
from api_settings import prepare_configuration, credential_profiles
from model_profiles import load_profiles, apply_profile

expected = {
    'deepseek/deepseek-v4.1-flash:jailbreak': (1048576, 943718, 'deepseek-4-1.md', ['low', 'high', 'max']),
    'zai/glm-5.3:jailbreak': (1310720, 262144, 'glm-5-3-flash.md', ['low', 'high', 'max']),
    'zai/glm-5.3-flash:uncensored': (1310720, 131072, 'glm-5-3-flash.md', ['low', 'high', 'max']),
    'openai/gpt-6-astra:jailbreak': (1050000, 128000, 'chatgpt.md', ['low', 'medium', 'high', 'xhigh', 'max']),
    'openai/gpt-5.6-sol:jailbreak': (1050000, 128000, 'chatgpt.md', ['none', 'low', 'medium', 'high', 'xhigh', 'max']),
}
provider = PROVIDERS['layercloud']
assert provider['adapter'] == 'chat_completions'
assert provider['endpoint'] == 'https://ai.layercloud.org/v1/chat/completions'
assert provider['default_model'] == next(iter(expected)) and set(provider['models']) == set(expected)
reads = []


def key(pid):
    reads.append(pid)
    return pid + '-dummy-key'


gateway = GatewayCore('layercloud_fixture_capability_12345678901234567890', 12345, {'gpt-6-astra', 'gpt-5.6-sol'}, key)
headers = [('Host', gateway.host), ('Authorization', 'Bearer native-private-fixture'),
           ('ChatGPT-Account-Id', 'native-account-fixture'), ('Content-Type', 'application/json'),
           ('X-Provider', 'caller-spoof')]
path = gateway.prefix + '/backend-api/codex/responses'
tool = {'type': 'function', 'name': 'fixture', 'parameters': {'type': 'object', 'properties': {}}}
settings, profiles = load_profiles(root / 'config')
for mid, (context, output, profile, efforts) in expected.items():
    route = MODELS[mid]
    assert route['provider'] == 'layercloud' and route['output_limit'] == output
    assert route['metadata']['context_window'] == route['metadata']['max_context_window'] == context
    assert route['metadata']['input_modalities'] == (['text', 'image'] if mid in {'zai/glm-5.3-flash:uncensored', 'openai/gpt-6-astra:jailbreak', 'openai/gpt-5.6-sol:jailbreak'} else ['text'])
    assert route['metadata']['default_reasoning_level'] == 'low'
    assert [e['effort'] for e in route['metadata']['supported_reasoning_levels']] == efforts
    assert settings['models'][mid] == profile
    for effort in efforts:
        payload = apply_profile({'model': mid, 'instructions': 'PROJECT_FIXTURE',
            'input': [{'role': 'user', 'content': 'fixture'}], 'reasoning': {'effort': effort},
            'max_output_tokens': 256, 'tools': [tool]}, settings, profiles)
        prepared = gateway.prepare('POST', path, headers, json.dumps(payload).encode())
        assert prepared.provider == 'layercloud' and prepared.url == provider['endpoint']
        outgoing = {k.lower(): v for k, v in prepared.headers}
        assert outgoing['authorization'] == 'Bearer layercloud-dummy-key'
        assert 'chatgpt-account-id' not in outgoing and 'x-provider' not in outgoing
        body = json.loads(prepared.body)
        limit_output(body, route)
        chat = prepare_chat(body, stream=True)
        assert chat['model'] == mid and chat['reasoning_effort'] == effort and chat['max_tokens'] == 256
        assert chat['stream'] and chat['stream_options'] == {'include_usage': True}
        assert 'PROJECT_FIXTURE' in chat['messages'][0]['content']
        assert profiles[profile] in chat['messages'][0]['content']
        assert 'native-private-fixture' not in json.dumps(chat) and 'service_tier' not in chat
        wire = chat['tools'][0]['function']['name']
        reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {'content': None, 'tool_calls': [
            {'id': 'layercloud-fixture-call', 'type': 'function', 'function': {'name': wire, 'arguments': '{}'}}]}}]}
        events = [event for _, event in response_events(reply, prepared.tools)]
        assert events[-1]['response']['output'][-1]['name'] == 'fixture'
    for cap in (None, output + 1):
        body = {} if cap is None else {'max_output_tokens': cap}
        limit_output(body, route)
        assert body['max_output_tokens'] == output
assert reads == ['layercloud'] * sum(len(values[3]) for values in expected.values())
other = PROVIDERS['arnict']['default_model']
prepared = gateway.prepare('POST', path, headers, json.dumps({'model': other, 'input': []}).encode())
assert prepared.provider == reads[-1] == 'arnict'
assert dict(prepared.headers)['Authorization'] == 'Bearer arnict-dummy-key'
for mid in ('gpt-6-astra', 'gpt-5.6-sol'):
    native = gateway.prepare('POST', path, headers, json.dumps({'model': mid, 'input': []}).encode())
    assert native.provider == 'openai' and native.url.startswith('https://chatgpt.com/') and reads[-1] == 'arnict'
    assert dict(native.headers)['authorization'] == 'Bearer native-private-fixture'

catalog = json.loads((root / 'config/models.json').read_text())
metadata = {m['slug']: m for m in catalog['models']}
rows = [{'id': mid, 'provider': pid, 'label': metadata[mid]['display_name'], 'context': metadata[mid]['context_window'],
         'output': route['output_limit'], 'efforts': [e['effort'] for e in metadata[mid]['supported_reasoning_levels']],
         'default_effort': metadata[mid]['default_reasoning_level'],
         'metadata_mode': route.get('metadata_mode', 'custom'), 'reasoning_mode': route.get('reasoning_mode', 'explicit')}
        for pid, p in PROVIDERS.items() for mid, route in p['models'].items()]
request = {'providers': {pid: {k: p[k] for k in ('label', 'adapter', 'endpoint', 'default_model')} for pid, p in PROVIDERS.items()},
           'models': rows}
saved, _ = prepare_configuration(request, PROVIDERS, catalog)
assert saved['layercloud'] == provider
assert credential_profiles(root / '.local/nonexistent-layercloud-fixture-keys', saved)['layercloud'] == {
    'active': 'default', 'profiles': [{'id': 'default', 'label': 'Default', 'saved': False}]}
advertised = {m['slug']: m for m in public_catalog(catalog, PROVIDERS)['models']}
assert all(advertised[mid]['auto_compact_token_limit'] == min(advertised[mid]['context_window']*80//100, next(m for m in catalog['models'] if m['slug']==mid).get('auto_compact_token_limit') or advertised[mid]['context_window']*80//100) for mid in expected)
print('PASS: all LayerCloud models, limits, reasoning, tools, settings, profiles, compaction and provider-only credentials.')
