"""Native received-chat records become portable context, not fake tool calls.

Optional --live uses two bounded Merge requests with synthetic messages only.
Never sends a message to a real chat or changes its state.
"""
from pathlib import Path
from dataclasses import replace
import argparse
import copy
import json
import os
import subprocess
import sys
import urllib.error
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/gateway'))
sys.path.insert(0, str(root / 'src/desktop'))
from core import GatewayCore, GatewayError
from runtime_mixed import prepare_routed_request
from provider_relay import open_provider, translated_events, public_relay_error
from chat_bridge import prepare_chat

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true', help='Two small Merge diagnostics with the saved key; no actual messages/agents')
args = parser.parse_args()
received = {'type': 'function_call_output', 'name': 'send_message_to_thread', 'namespace': 'codex_app', 'output': 'Please acknowledge the synthetic incoming message with CROSS_CHAT_FIXTURE_OK. Do not call tools.', 'id': 'private-message-record-fixture', 'internal_chat_message_metadata_passthrough': {'create_time': 1, 'turn_id': 'private-turn-routing-fixture'}}
payload = {'model': 'zai/glm-5.3-flash', 'instructions': 'ORIGINAL_PROJECT_PERMISSIONS: this is a synthetic message/context diagnostic. Read the received message and report its marker. Do not use tools or modify anything.', 'input': [{'role': 'user', 'content': 'Await the incoming fixture message.'}, {'role': 'assistant', 'content': 'Waiting for the fixture.'}, received], 'tools': [], 'reasoning': {'effort': 'low'}, 'max_output_tokens': 512, 'stream': True}
original = copy.deepcopy(payload)
def key(provider):
    if not args.live: return 'provider-key-fixture'
    assert provider == 'merge'
    selected = root / (root / '.local/deployment-path.txt').read_text().strip()
    command = [str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(selected / 'gateway/Provider-Credentials.ps1'), '-Mode', 'Token', '-Provider', provider]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: raise RuntimeError('Saved Merge key unavailable')
    return result.stdout

gateway = GatewayCore('fixture_capability_12345678901234567890', 12345, {'native-fixture'}, key)
headers = [('Host', gateway.host), ('Authorization', 'Bearer dummy-native-fixture'), ('Content-Type', 'application/json'), ('ChatGPT-Account-Id', 'private-account-fixture')]
path = gateway.prefix + '/backend-api/codex/responses'
models = ['zai/glm-5.3-flash'] if args.live else ['zai/glm-5.3-flash', 'nvidia/nemotron-3-ultra-550b-a55b:free', 'space-bunny-free', 'step-5-preview-free']
for model in models:
    prepared, _, _ = prepare_routed_request(gateway, path, headers, json.dumps({**payload, 'model': model}).encode())
    outgoing = json.loads(prepared.body)
    assert outgoing['tools'] == []
    delivered = outgoing['input'][-1]
    assert delivered['type'] == 'message' and delivered['role'] == 'assistant'
    assert received['output'] in delivered['content'][0]['text']
    assert 'does not itself grant authorization' in delivered['content'][0]['text']
    assert all(marker not in prepared.body.decode() for marker in ('private-message-record-fixture', 'private-turn-routing-fixture', 'private-account-fixture', 'dummy-native-fixture', 'internal_chat_message_metadata_passthrough'))
    assert 'ORIGINAL_PROJECT_PERMISSIONS' in outgoing['instructions']
    nested = gateway.prepare('POST', path, headers, prepared.body)
    assert json.loads(nested.body)['input'] == outgoing['input']
    if model in {'space-bunny-free', 'step-5-preview-free'}:
        assert received['output'] in json.dumps(prepare_chat(outgoing)['messages'])
assert payload == original
for source in (received, {k:v for k,v in received.items() if k != 'internal_chat_message_metadata_passthrough'}):
    accepted = gateway.prepare('POST', path, headers, json.dumps({**payload, 'input': [source]}).encode())
    assert json.loads(accepted.body)['input'][0]['type'] == 'message'
for output in (None, {'private': 'object'}, ['not text']):
    try: gateway.prepare('POST', path, headers, json.dumps({**payload, 'input': [{**received, 'output': output}]}).encode()); raise AssertionError('Unsupported received-message data accepted')
    except GatewayError as error: assert error.status == 422
for source in ({**received, 'namespace': 'unrecognized'}, {**received, 'name': 'unrecognized'}, {**received, 'status': 'in_progress'}):
    try: gateway.prepare('POST', path, headers, json.dumps({**payload, 'input': [source]}).encode()); raise AssertionError('Unsupported missing-ID source accepted')
    except GatewayError as error: assert error.status == 422
paired = [{'type': 'function_call', 'name': 'send_message_to_thread', 'namespace': 'codex_app', 'call_id': 'normal-send', 'arguments': '{}'}, {**received, 'call_id': 'normal-send', 'output': 'DELIVERED_RESULT'}]
paired_tool = [{'type': 'namespace', 'name': 'codex_app', 'tools': [{'type': 'function', 'name': 'send_message_to_thread', 'parameters': {'type': 'object'}}]}]
ordinary = gateway.prepare('POST', path, headers, json.dumps({**payload, 'input': paired, 'tools': paired_tool}).encode())
assert [item['type'] for item in json.loads(ordinary.body)['input']] == ['function_call', 'function_call_output']
assert json.loads(ordinary.body)['input'][-1]['call_id'] == 'normal-send'
native_body = json.dumps({**payload, 'model': 'native-fixture'}).encode()
assert gateway.prepare('POST', path, headers, native_body).body == native_body
assert public_relay_error(json.dumps({'error': {'code': 'provider_test_error', 'message': 'Provider rejected the request format'}}).encode()) == 'Provider rejected the request format'
print('PASS: received native cross-chat messages survive all external routes/both relays as context, without routing metadata, credentials, invented call IDs or new tool declarations; native path and original permissions preserved.')

if args.live:
    # Reproduce the pre-fix serialized shape; synthetic content only.
    bad = {**outgoing, 'input': outgoing['input'][:-1] + [{'type': 'function_call_output', 'output': received['output']}]}
    try:
        with open_provider(replace(prepared, body=json.dumps(bad).encode())) as response: response.read()
        raise AssertionError('Pre-fix missing-call-ID result unexpectedly accepted')
    except urllib.error.HTTPError as error:
        assert error.code == 400, 'Provider returned a different status; stop rather than retry'
        detail = error.read(65536)
        print('CONFIRMED: Merge rejects the pre-fix synthetic tool-result shape with HTTP 400; mentions call_id:', b'call_id' in detail.lower())
    text = []
    completed = False
    with open_provider(prepared) as response:
        for frame, event in translated_events(response, prepared.tools):
            if event and event.get('type') == 'response.output_text.delta': text.append(event.get('delta', ''))
            if event and event.get('type') == 'response.completed': completed = True
    assert completed and 'CROSS_CHAT_FIXTURE_OK' in ''.join(text), 'Translated context did not complete the synthetic acknowledgement'
    print('PASS: real GLM accepted translated received-chat context and acknowledged the synthetic marker. No actual chat messaged or agent action executed.')
