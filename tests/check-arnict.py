"""Arnict routing, portable tools, settings and credential isolation; offline."""
from pathlib import Path
import json
import sys

root = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(root / 'src/gateway'), str(root / 'src/desktop')]
from provider_registry import PROVIDERS, MODELS
from core import GatewayCore
from chat_bridge import prepare_chat, response_events
from api_settings import prepare_configuration, credential_profiles
from model_profiles import load_profiles

provider = PROVIDERS['arnict']
assert provider['adapter'] == 'chat_completions'
assert provider['endpoint'] == 'https://api.arnict.com/v1/chat/completions'
assert provider['default_model'] == 'zai/glm-5.3-flash-uncensored'
assert set(provider['models']) == {'zai/glm-5.3-flash-uncensored', 'zai/glm-5.3-uncensored'}
reads = []
def key(pid):
    reads.append(pid)
    return 'arnict-dummy-key' if pid == 'arnict' else 'other-dummy-key'

gateway = GatewayCore('arnict_fixture_capability_12345678901234567890', 12345, set(), key)
headers = [('Host', gateway.host), ('Authorization', 'Bearer native-private-fixture'),
           ('ChatGPT-Account-Id', 'native-account-fixture'), ('Content-Type', 'application/json'),
           ('X-Provider', 'caller-spoof')]
path = gateway.prefix + '/backend-api/codex/responses'
tool = {'type': 'function', 'name': 'fixture', 'parameters': {'type': 'object', 'properties': {}}}
for mid in provider['models']:
    route = MODELS[mid]
    assert route['provider'] == 'arnict' and route['output_limit'] == 131072
    assert route['metadata']['context_window'] == route['metadata']['max_context_window'] == 1048576
    assert route['metadata']['input_modalities'] == (['text', 'image'] if mid == 'zai/glm-5.3-flash-uncensored' else ['text'])
    assert route['metadata']['default_reasoning_level'] == 'low'
    assert [e['effort'] for e in route['metadata']['supported_reasoning_levels']] == ['low', 'high', 'max']
    for effort in ('low', 'high', 'max'):
        payload = {'model': mid, 'instructions': 'PROJECT_FIXTURE', 'input': [{'role': 'user', 'content': 'fixture'}],
                   'reasoning': {'effort': effort}, 'max_output_tokens': 256, 'tools': [tool]}
        prepared = gateway.prepare('POST', path, headers, json.dumps(payload).encode())
        assert prepared.provider == 'arnict' and prepared.url == provider['endpoint']
        outgoing = dict((k.lower(), v) for k, v in prepared.headers)
        assert outgoing['authorization'] == 'Bearer arnict-dummy-key'
        assert 'chatgpt-account-id' not in outgoing and 'x-provider' not in outgoing
        chat = prepare_chat(json.loads(prepared.body), stream=True)
        assert chat['model'] == mid and chat['reasoning_effort'] == effort and chat['max_tokens'] == 256
        assert chat['stream'] and chat['stream_options'] == {'include_usage': True}
        assert 'PROJECT_FIXTURE' in chat['messages'][0]['content']
        assert 'native-private-fixture' not in json.dumps(chat) and 'service_tier' not in chat
        wire = chat['tools'][0]['function']['name']
        reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {'content': None, 'tool_calls': [
            {'id': 'arnict-fixture-call', 'type': 'function', 'function': {'name': wire, 'arguments': '{}'}}]}}]}
        events = [event for _, event in response_events(reply, prepared.tools)]
        assert events[-1]['response']['output'][-1]['name'] == 'fixture'
assert reads == ['arnict'] * 6
nano = PROVIDERS['nanogpt']['default_model']
prepared = gateway.prepare('POST', path, headers, json.dumps({'model': nano, 'input': []}).encode())
assert prepared.provider == 'nanogpt' and reads[-1] == 'nanogpt'
assert dict(prepared.headers)['Authorization'] == 'Bearer other-dummy-key'

catalog = json.loads((root / 'config/models.json').read_text())
metadata = {m['slug']: m for m in catalog['models']}
rows = [{'id': mid, 'provider': pid, 'label': metadata[mid]['display_name'], 'context': metadata[mid]['context_window'],
         'output': route['output_limit'], 'efforts': [e['effort'] for e in metadata[mid]['supported_reasoning_levels']],
         'default_effort': metadata[mid]['default_reasoning_level']}
        for pid, p in PROVIDERS.items() for mid, route in p['models'].items()]
request = {'providers': {pid: {k: p[k] for k in ('label', 'adapter', 'endpoint', 'default_model')} for pid, p in PROVIDERS.items()},
           'models': rows}
saved, _ = prepare_configuration(request, PROVIDERS, catalog)
assert saved['arnict'] == provider
assert credential_profiles(root / '.local/nonexistent-arnict-fixture-keys', saved)['arnict'] == {
    'active': 'default', 'profiles': [{'id': 'default', 'label': 'Default', 'saved': False}]}
settings, _ = load_profiles(root / 'config')
for mid in provider['models']:
    assert settings['models'][mid] == settings['models'][nano]
print('PASS: both Arnict models, limits, efforts, portable tools, settings, instruction profiles and provider-only credentials.')
