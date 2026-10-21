"""Experiential Labs alias, capabilities, tools and credential isolation; offline."""
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

mid = 'glm-5.3-flash-abliterated'
provider = PROVIDERS['experiential']
assert provider['endpoint'] == 'https://api.experientiallabs.ai/v1/chat/completions'
assert provider['adapter'] == 'chat_completions'
assert provider['default_model'] == mid and set(provider['models']) == {mid}
route = MODELS[mid]
assert route['provider'] == 'experiential' and route['output_limit'] == 131072
assert route['metadata']['context_window'] == route['metadata']['max_context_window'] == 1048576
assert route['metadata']['input_modalities'] == ['text', 'image']
assert route['metadata']['default_reasoning_level'] == 'max'
efforts = ['low', 'high', 'max']
assert [e['effort'] for e in route['metadata']['supported_reasoning_levels']] == efforts
settings, profiles = load_profiles(root / 'config')
assert settings['models'][mid] == 'glm-5-3-flash.md'
reads = []


def key(pid):
    reads.append(pid)
    return pid + '-dummy-key'


gateway = GatewayCore('experiential_fixture_capability_12345678901234567890', 12345, set(), key)
headers = [('Host', gateway.host), ('Authorization', 'Bearer native-private-fixture'),
           ('ChatGPT-Account-Id', 'native-account-fixture'), ('Content-Type', 'application/json')]
path = gateway.prefix + '/backend-api/codex/responses'
tool = {'type': 'function', 'name': 'fixture', 'parameters': {'type': 'object', 'properties': {}}}
for effort in efforts:
    payload = apply_profile({'model': mid, 'instructions': 'PROJECT_FIXTURE',
        'input': [{'role': 'user', 'content': 'fixture'}], 'reasoning': {'effort': effort},
        'max_output_tokens': 256, 'tools': [tool]}, settings, profiles)
    prepared = gateway.prepare('POST', path, headers, json.dumps(payload).encode())
    assert prepared.provider == 'experiential' and prepared.url == provider['endpoint']
    outgoing = {k.lower(): v for k, v in prepared.headers}
    assert outgoing['authorization'] == 'Bearer experiential-dummy-key'
    assert 'chatgpt-account-id' not in outgoing
    body = json.loads(prepared.body)
    limit_output(body, route)
    chat = prepare_chat(body, stream=True)
    assert chat['model'] == mid and chat['reasoning_effort'] == effort and chat['max_tokens'] == 256
    assert chat['stream'] and chat['stream_options'] == {'include_usage': True}
    assert 'PROJECT_FIXTURE' in chat['messages'][0]['content']
    assert profiles['glm-5-3-flash.md'] in chat['messages'][0]['content']
    assert 'native-private-fixture' not in json.dumps(chat)
    wire = chat['tools'][0]['function']['name']
    reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {'content': None, 'tool_calls': [
        {'id': 'experiential-fixture-call', 'type': 'function', 'function': {'name': wire, 'arguments': '{}'}}]}}]}
    events = [event for _, event in response_events(reply, prepared.tools)]
    assert events[-1]['response']['output'][-1]['name'] == 'fixture'
assert reads == ['experiential'] * len(efforts)
other = gateway.prepare('POST', path, headers, json.dumps({'model': 'glm-5.3-flash-uncensored', 'input': []}).encode())
assert other.provider == reads[-1] == 'routeway'
assert dict(other.headers)['Authorization'] == 'Bearer routeway-dummy-key'
for cap in (None, 200000):
    body = {} if cap is None else {'max_output_tokens': cap}
    limit_output(body, route)
    assert body['max_output_tokens'] == 131072

catalog = json.loads((root / 'config/models.json').read_text())
metadata = {m['slug']: m for m in catalog['models']}
rows = [{'id': m, 'provider': pid, 'label': metadata[m]['display_name'], 'context': metadata[m]['context_window'],
         'output': r['output_limit'], 'efforts': [e['effort'] for e in metadata[m]['supported_reasoning_levels']],
         'default_effort': metadata[m]['default_reasoning_level'],
         'metadata_mode': r.get('metadata_mode', 'custom'), 'reasoning_mode': r.get('reasoning_mode', 'explicit')}
        for pid, p in PROVIDERS.items() for m, r in p['models'].items()]
request = {'providers': {pid: {k: p[k] for k in ('label', 'adapter', 'endpoint', 'default_model')} for pid, p in PROVIDERS.items()},
           'models': rows}
saved, _ = prepare_configuration(request, PROVIDERS, catalog)
assert saved['experiential'] == provider
assert credential_profiles(root / '.local/nonexistent-experiential-fixture-keys', saved)['experiential']['profiles'][0]['saved'] is False
assert next(m for m in public_catalog(catalog, PROVIDERS)['models'] if m['slug'] == mid)['auto_compact_token_limit'] == min(metadata[mid]['context_window']*80//100, metadata[mid].get('better_codex_auto_compact_token_limit') or metadata[mid].get('auto_compact_token_limit') or metadata[mid]['context_window']*80//100)
print('PASS: Experiential alias, limits, efforts/default, tools, profiles, settings, compaction and isolated credentials.')
