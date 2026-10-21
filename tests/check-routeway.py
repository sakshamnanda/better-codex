"""Routeway model routing, tools, settings and credential isolation; offline."""
from pathlib import Path
import json
import sys

root = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(root / 'src/gateway'), str(root / 'src/desktop')]
from provider_registry import PROVIDERS, MODELS
from core import GatewayCore
from provider_relay import limit_output
from chat_bridge import prepare_chat, response_events
from api_settings import prepare_configuration, credential_profiles
from model_profiles import load_profiles

mid = 'glm-5.3-flash-uncensored'
provider = PROVIDERS['routeway']
assert provider['adapter'] == 'chat_completions'
assert provider['endpoint'] == 'https://api.routeway.ai/v1/chat/completions'
cyber = 'glm-5.3-flash-cybersecurity'
assert provider['default_model'] == mid and set(provider['models']) == {mid, cyber, cyber + ':flex'}
route = MODELS[mid]
assert route['provider'] == 'routeway' and route['output_limit'] == 32768
assert route['metadata']['context_window'] == route['metadata']['max_context_window'] == 262144
assert route['metadata']['input_modalities'] == ['text', 'image']
assert route['metadata']['default_reasoning_level'] == 'low'
efforts = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh']
assert [e['effort'] for e in route['metadata']['supported_reasoning_levels']] == efforts
reads = []
def key(pid):
    reads.append(pid)
    return pid + '-dummy-key'

gateway = GatewayCore('routeway_fixture_capability_12345678901234567890', 12345, set(), key)
headers = [('Host', gateway.host), ('Authorization', 'Bearer native-private-fixture'),
           ('ChatGPT-Account-Id', 'native-account-fixture'), ('Content-Type', 'application/json'),
           ('X-Provider', 'caller-spoof')]
path = gateway.prefix + '/backend-api/codex/responses'
tool = {'type': 'function', 'name': 'fixture', 'parameters': {'type': 'object', 'properties': {}}}
for effort in efforts:
    payload = {'model': mid, 'instructions': 'PROJECT_FIXTURE', 'input': [{'role': 'user', 'content': 'fixture'}],
               'reasoning': {'effort': effort}, 'max_output_tokens': 256, 'tools': [tool]}
    prepared = gateway.prepare('POST', path, headers, json.dumps(payload).encode())
    assert prepared.provider == 'routeway' and prepared.url == provider['endpoint']
    outgoing = {k.lower(): v for k, v in prepared.headers}
    assert outgoing['authorization'] == 'Bearer routeway-dummy-key'
    assert 'chatgpt-account-id' not in outgoing and 'x-provider' not in outgoing
    body = json.loads(prepared.body)
    limit_output(body, route)
    chat = prepare_chat(body, stream=True)
    assert chat['model'] == mid and chat['reasoning_effort'] == effort and chat['max_tokens'] == 256
    assert chat['stream'] and chat['stream_options'] == {'include_usage': True}
    assert 'PROJECT_FIXTURE' in chat['messages'][0]['content']
    assert 'native-private-fixture' not in json.dumps(chat) and 'service_tier' not in chat
    wire = chat['tools'][0]['function']['name']
    reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {'content': None, 'tool_calls': [
        {'id': 'routeway-fixture-call', 'type': 'function', 'function': {'name': wire, 'arguments': '{}'}}]}}]}
    events = [event for _, event in response_events(reply, prepared.tools)]
    assert events[-1]['response']['output'][-1]['name'] == 'fixture'
assert reads == ['routeway'] * len(efforts)
for model in (cyber, cyber + ':flex'):
    route = MODELS[model]
    assert route['provider'] == 'routeway' and route['output_limit'] == 32768
    assert route['metadata']['context_window'] == route['metadata']['max_context_window'] == 1000000
    assert route['reasoning_mode'] == 'provider_default'
    assert route['metadata']['input_modalities'] == ['text', 'image']
    assert [e['effort'] for e in route['metadata']['supported_reasoning_levels']] == ['none']
    payload = {'model': model, 'input': [{'role': 'user', 'content': 'fixture'}],
               'reasoning': {'effort': 'high'}, 'tools': [tool]}
    prepared = gateway.prepare('POST', path, headers, json.dumps(payload).encode())
    body = json.loads(prepared.body)
    limit_output(body, route)
    chat = prepare_chat(body, stream=True)
    assert prepared.provider == 'routeway' and prepared.url == provider['endpoint']
    assert dict(prepared.headers)['Authorization'] == 'Bearer routeway-dummy-key'
    assert chat['model'] == model and chat['max_tokens'] == 32768
    assert 'reasoning_effort' not in chat and 'service_tier' not in chat
    assert chat['tools'] and chat['stream'] and 'native-private-fixture' not in json.dumps(chat)
    assert reads[-1] == 'routeway'
for pid in ('nanogpt', 'arnict'):
    other = PROVIDERS[pid]['default_model']
    prepared = gateway.prepare('POST', path, headers, json.dumps({'model': other, 'input': []}).encode())
    assert prepared.provider == pid and reads[-1] == pid
    assert dict(prepared.headers)['Authorization'] == 'Bearer ' + pid + '-dummy-key'
for cap in (None, 100000):
    body = {} if cap is None else {'max_output_tokens': cap}
    limit_output(body, route)
    assert body['max_output_tokens'] == 32768

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
assert saved['routeway'] == provider
assert credential_profiles(root / '.local/nonexistent-routeway-fixture-keys', saved)['routeway']['profiles'][0]['saved'] is False
settings, _ = load_profiles(root / 'config')
assert settings['models'][mid] == 'glm-5-3-flash.md'
assert settings['models'][cyber] == settings['models'][cyber + ':flex'] == settings['models'][mid]
print('PASS: Routeway models, Flex suffix, contexts, local output caps, efforts/default reasoning, tools, settings, profiles and provider-only credentials.')
