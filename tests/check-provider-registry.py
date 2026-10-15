"""New compatible provider routing, effort metadata and credential isolation."""
from pathlib import Path
import copy
import json
import sys
import uuid

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/gateway'))
from provider_registry import load_registry
import core
import io
from provider_relay import translated_events

# The actual Merge route must use OpenAI-compatible Responses and provider-only auth.
merge = core.GatewayCore('merge_fixture_capability_12345678901234567890', 12345, set(), lambda provider: 'merge-fixture-key' if provider == 'merge' else 'wrong-provider-key')
headers = [('Host', merge.host), ('Authorization', 'Bearer native-private-fixture'), ('ChatGPT-Account-Id', 'native-account-fixture'), ('Content-Type', 'application/json')]
tool = {'type': 'namespace', 'name': 'functions', 'tools': [{'type': 'function', 'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}]}
payload = {'model': 'zai/glm-5.3-flash', 'instructions': 'PROJECT_FIXTURE_REQUIREMENTS', 'input': [{'role': 'user', 'content': 'fixture message'}], 'tools': [tool], 'reasoning': {'effort': 'max'}}
prepared = merge.prepare('POST', merge.prefix + '/backend-api/codex/responses', headers, json.dumps(payload).encode())
assert prepared.url == 'https://api-gateway.merge.dev/v1/openai/responses'
assert dict(prepared.headers)['Authorization'] == 'Bearer merge-fixture-key'
assert not any(name.lower() == 'chatgpt-account-id' for name, _ in prepared.headers)
forwarded = json.loads(prepared.body)
if core.MODELS['zai/glm-5.3-flash'].get('reasoning_mode')=='provider_default':
    assert 'reasoning' not in forwarded
else:
    allowed=core.EXTERNAL['zai/glm-5.3-flash'][3]
    assert forwarded['reasoning']['effort']==('max' if 'max' in allowed else core.EXTERNAL['zai/glm-5.3-flash'][2])
assert 'Merge Gateway' in forwarded['instructions']
assert 'native-private-fixture' not in prepared.body.decode()
wire_name = forwarded['tools'][0]['name']
call = {'type': 'function_call', 'name': wire_name, 'call_id': 'fixture-call', 'arguments': '{"cmd":"Write-Output fixture"}'}
events = [{'type': 'response.output_item.done', 'item': call}, {'type': 'response.completed', 'response': {'output': [call]}}]
stream = io.BytesIO(''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode())
translated = [event for frame, event in translated_events(stream, prepared.tools) if event]
assert translated[-1]['response']['output'][0]['namespace'] == 'functions'
assert translated[-1]['response']['output'][0]['name'] == 'exec_command'
print('PASS: Merge compatible endpoint, separate credentials, effort and streamed Codex function-tool mapping.')

directory = root / '.local/test-work' / ('registry-' + uuid.uuid4().hex[:8])
directory.mkdir(parents=True)
providers = json.loads((root / 'config/providers.json').read_text())
catalog = json.loads((root / 'config/models.json').read_text())
model = copy.deepcopy(next(model for model in catalog['models'] if model['slug'] == 'nvidia/nemotron-3-ultra-550b-a55b:free'))
model.update(slug='fixture/text-model', display_name='Fixture Text Model',default_reasoning_level='high',
    supported_reasoning_levels=[{'effort':'high','description':'Owned high-effort fixture'}],better_codex_provider='fixture',better_codex_removed=False)
catalog['models'].append(model)
providers['fixture'] = {'label': 'Fixture Provider', 'adapter': 'responses', 'endpoint': 'https://provider.example/v1/responses', 'default_model': model['slug'], 'models': {model['slug']: {'output_limit': 2048}}}
(directory / 'models.json').write_text(json.dumps(catalog))
(directory / 'providers.json').write_text(json.dumps(providers))
core.PROVIDERS, models, core.EXTERNAL = load_registry(directory)
gateway = core.GatewayCore('fixture_capability_12345678901234567890', 12345, {'gpt-native-fixture'}, lambda provider: 'external-fixture-key' if provider == 'fixture' else 'fixture-key')
headers = [('Host', gateway.host), ('Authorization', 'Bearer native-fixture-credential'), ('Content-Type', 'application/json'), ('ChatGPT-Account-Id', 'private-native-account')]
path = gateway.prefix + '/backend-api/codex/responses'
payload = {'model': model['slug'], 'input': [{'role': 'user', 'content': 'fixture message'}], 'reasoning': {'effort': 'high'}, 'tools': []}
prepared = gateway.prepare('POST', path, headers, json.dumps(payload).encode())
assert prepared.provider == 'fixture' and prepared.url == providers['fixture']['endpoint']
assert dict(prepared.headers)['Authorization'] == 'Bearer external-fixture-key'
assert not any(name.lower() == 'chatgpt-account-id' for name, _ in prepared.headers)
assert b'native-fixture-credential' not in prepared.body
assert json.loads(prepared.body)['reasoning']['effort'] == 'high'
assert 'Fixture Provider' in json.loads(prepared.body)['instructions']
payload['model'] = 'unknown-model'
try: gateway.prepare('POST', path, headers, json.dumps(payload).encode()); raise AssertionError('Unknown model accepted')
except core.GatewayError as error: assert error.status == 422
payload['model'] = 'gpt-native-fixture'
native = gateway.prepare('POST', path, headers, json.dumps(payload).encode())
assert native.url.startswith('https://chatgpt.com/') and dict(native.headers)['authorization'] == 'Bearer native-fixture-credential'
for endpoint in ('http://provider.example/v1/responses', 'https://user:secret@provider.example/v1/responses', 'https://chatgpt.com/backend-api/codex/responses'):
    providers['fixture']['endpoint'] = endpoint
    (directory / 'providers.json').write_text(json.dumps(providers))
    try: load_registry(directory); raise AssertionError('Unsafe external endpoint accepted')
    except ValueError: pass
print('PASS: configuration-only provider addition, independent effort metadata, native credential isolation, native routing and unsafe/unknown route rejection.')
