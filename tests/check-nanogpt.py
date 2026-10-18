"""NanoGPT routing and Chat Completions translation without inference or real keys."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src/gateway'))
from core import GatewayCore, GatewayError, ToolNames
from chat_bridge import prepare_chat, response_events, REASONING
from provider_registry import PROVIDERS, MODELS, public_catalog

mid = 'z-ai/glm-5.3-flash-uncensored'
assert PROVIDERS['nanogpt']['default_model'] == mid
assert MODELS[mid]['output_limit'] == 32768
assert MODELS[mid]['metadata']['context_window'] == 1048576
assert MODELS[mid]['metadata']['input_modalities'] == ['text']
reads = []
def key(provider):
    reads.append(provider)
    return 'nanogpt-dummy-fixture'

gateway = GatewayCore('nanogpt_fixture_capability_12345678901234567890', 12345, set(), key)
headers = [('Host', gateway.host), ('Authorization', 'Bearer native-private-fixture'),
           ('ChatGPT-Account-Id', 'native-account-fixture'), ('Content-Type', 'application/json')]
cases = [(mid, effort) for effort in ('low', 'high')]
cyber = 'z-ai/glm-5.3-flash-cybersecurity'
catalog = json.loads((Path(__file__).resolve().parent.parent / 'config/models.json').read_text())
assert next(model for model in catalog['models'] if model['slug'] == cyber)['better_codex_removed']
assert cyber not in MODELS and cyber not in PROVIDERS['nanogpt']['models']
assert all(model['slug'] != cyber for model in public_catalog(catalog, PROVIDERS)['models'])
try:
    gateway.prepare('POST', gateway.prefix + '/backend-api/codex/responses', headers,
                    json.dumps({'model': cyber, 'input': []}).encode())
    raise AssertionError('Retired NanoGPT model was routed')
except GatewayError as error:
    assert error.status == 422
assert not reads
for mid, effort in cases:
    payload = {'model': mid, 'input': [{'role': 'user', 'content': 'fixture'}],
               'reasoning': {'effort': effort}, 'tools': []}
    prepared = gateway.prepare('POST', gateway.prefix + '/backend-api/codex/responses', headers, json.dumps(payload).encode())
    assert prepared.provider == 'nanogpt'
    assert prepared.url == PROVIDERS['nanogpt']['endpoint']
    assert dict(prepared.headers)['Authorization'] == 'Bearer nanogpt-dummy-fixture'
    assert not any(k.lower() == 'chatgpt-account-id' for k, _ in prepared.headers)
    chat = prepare_chat(json.loads(prepared.body))
    assert chat['model'] == mid and chat['reasoning_effort'] == effort
    assert 'native-private-fixture' not in json.dumps(chat)
assert reads == ['nanogpt'] * len(cases)
assert 'reasoning_effort' not in prepare_chat({'model': mid, 'input': []})
names = ToolNames([{'type': 'function', 'name': 'fixture', 'parameters': {'type': 'object', 'properties': {}}}])
reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {'reasoning': 'fixture reasoning',
    'tool_calls': [{'id': 'nanogpt-fixture-call', 'type': 'function',
                    'function': {'name': 'fixture', 'arguments': '{}'}}]}}]}
list(response_events(reply, names))
assert REASONING.pop('nanogpt-fixture-call') == 'fixture reasoning'
print('PASS: active NanoGPT model, retired route rejection, limits, provider-only credentials, reasoning efforts and tool reasoning continuity.')
