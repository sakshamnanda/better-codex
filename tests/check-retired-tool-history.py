"""Completed retired tools remain context, never become newly callable tools."""
from pathlib import Path
import copy
import json
import sys
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/gateway'))
sys.path.insert(0, str(root / 'src/desktop'))
from core import GatewayCore, GatewayError
from runtime_mixed import prepare_routed_request

gateway = GatewayCore('fixture_capability_12345678901234567890', 12345, {'native-fixture'}, lambda p: 'provider-key-fixture')
headers = [('Host', gateway.host), ('Authorization', 'Bearer native-secret-fixture'), ('Content-Type', 'application/json')]
path = gateway.prefix + '/backend-api/codex/responses'
tools = [{'type': 'namespace', 'name': 'collaboration', 'tools': [{'type': 'function', 'name': 'spawn_agent', 'parameters': {'type': 'object', 'properties': {'message': {'type': 'string'}}}}]}]
history = [
    {'role': 'user', 'content': 'Keep the earlier review context.'},
    {'type': 'function_call', 'namespace': 'functions', 'name': 'exec', 'call_id': 'retired-exec', 'arguments': 'Write-Output fixture', 'status': 'completed', 'id': 'private-item-fixture'},
    {'type': 'function_call', 'namespace': 'multi_agent_v1', 'name': 'send_input', 'call_id': 'retired-v1', 'arguments': '{"target":"fixture-old-agent","message":"review"}'},
    {'type': 'function_call_output', 'call_id': 'retired-exec', 'output': [{'type': 'input_text', 'text': 'EARLIER_EXEC_RESULT', 'private_field': 'not-portable'}]},
    {'type': 'function_call_output', 'call_id': 'retired-v1', 'output': '{"error":"agent is closed"}'},
    {'type': 'function_call', 'namespace': 'collaboration', 'name': 'spawn_agent', 'call_id': 'current-call', 'arguments': '{"message":"fixture"}'},
    {'type': 'function_call_output', 'call_id': 'current-call', 'output': 'CURRENT_RESULT'},
]
base = {'model': 'zai/glm-5.3-flash', 'tools': tools, 'input': history, 'instructions': 'ORIGINAL_PROJECT_REQUIREMENTS'}
original = copy.deepcopy(base)
for model in ('zai/glm-5.3-flash', 'nvidia/nemotron-3-ultra-550b-a55b:free', 'space-bunny-free', 'step-5-preview-free'):
    prepared, _, _ = prepare_routed_request(gateway, path, headers, json.dumps({**base, 'model': model}).encode())
    wire = json.loads(prepared.body)
    assert len(wire['tools']) == 1 and wire['tools'][0]['name'] == 'collaboration__spawn_agent'
    assert all(item.get('call_id') not in {'retired-exec', 'retired-v1'} for item in wire['input'])
    transcript = '\n'.join(part['text'] for item in wire['input'] if item.get('type') == 'message' and isinstance(item.get('content'), list) for part in item['content'])
    assert 'EARLIER_EXEC_RESULT' in transcript and 'agent is closed' in transcript
    assert 'multi_agent_v1' in transcript and 'send_input' in transcript and 'not a new tool request' in transcript
    assert 'private-item-fixture' not in prepared.body.decode() and 'not-portable' not in prepared.body.decode()
    active_calls = [i for i in wire['input'] if i.get('type') == 'function_call']
    assert len(active_calls) == 1 and active_calls[0]['name'] == 'collaboration__spawn_agent' and active_calls[0]['call_id'] == 'current-call'
    # The second gateway sees portable messages, not executable retired calls.
    nested = gateway.prepare('POST', path, headers, prepared.body)
    assert json.loads(nested.body)['input'] == wire['input']
    assert 'ORIGINAL_PROJECT_REQUIREMENTS' in wire['instructions']
assert base == original

# No schemas must also work for a history-only request.
empty = gateway.prepare('POST', path, headers, json.dumps({**base, 'tools': []}).encode())
assert json.loads(empty.body)['tools'] == []
assert all(item.get('type', 'message') == 'message' for item in json.loads(empty.body)['input'])
changed = gateway.prepare('POST', path, headers, json.dumps({**base, 'tools': [{'type': 'namespace', 'name': 'functions', 'tools': [{'type': 'custom', 'name': 'exec', 'format': {'type': 'text'}}]}]}).encode())
assert all(item.get('type', 'message') == 'message' for item in json.loads(changed.body)['input'])
assert len(json.loads(changed.body)['tools']) == 1  # Current text-tool declaration retained.

invalid_histories = [
    history[:2],  # Retired call without its actual result.
    [{**history[1], 'status': 'in_progress'}, history[3]],
    [history[1], history[1], history[3]],
    [history[1], history[3], history[3]],
    [history[1], {**history[3], 'status': 'in_progress'}],
    [history[1], {'type': 'custom_tool_call_output', 'call_id': 'retired-exec', 'output': 'wrong result kind'}],
]
for invalid in invalid_histories:
    try: gateway.prepare('POST', path, headers, json.dumps({**base, 'input': invalid}).encode()); raise AssertionError('Incomplete/ambiguous retired call accepted')
    except GatewayError as error: assert error.status == 422
try:
    gateway.prepare('POST', path, headers, json.dumps({**base, 'tool_choice': {'type': 'function', 'namespace': 'multi_agent_v1', 'name': 'send_input'}}).encode())
    raise AssertionError('Forced invocation of a retired tool accepted')
except GatewayError as error: assert error.status == 422
try:
    empty.tools.response_item({'type': 'function_call', 'name': 'multi_agent_v1__send_input', 'arguments': '{}'})
    raise AssertionError('Provider invocation of a retired tool accepted')
except GatewayError as error: assert error.status == 502
native_body = json.dumps({**base, 'model': 'native-fixture'}).encode()
assert gateway.prepare('POST', path, headers, native_body).body == native_body
print('PASS: retired code-mode/V1 tool calls and interleaved results survive all external routes and both gateways as history; active mappings/native input unchanged; incomplete results and new retired-tool invocations rejected. No provider or tool execution.')
