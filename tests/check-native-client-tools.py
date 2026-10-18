"""Use the installed Codex runtime with local mock inference and an owned MCP.

No provider calls, real account/profile, tunnels, agents or app restarts.
Only a scratch patch and a read-only MCP fixture are executed by Codex.
"""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import uuid

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/gateway'))
sys.path.insert(0, str(root / 'src/desktop'))
from core import GatewayCore, ToolNames
from chat_bridge import stream_response_events
from runtime_mixed import prepare_routed_request

selected = root / os.environ.get('BETTER_CODEX_TEST_DEPLOYMENT', (root / '.local/deployment-path.txt').read_text().strip())
manifest = json.loads((selected / 'Deployment.json').read_text())
installed = Path(manifest['source_app'])
for name, expected in manifest['installed_file_hashes'].items():
    with (installed / name).open('rb') as f: assert hashlib.file_digest(f, 'sha256').hexdigest() == expected
scratch = root / '.local/test-work' / ('native-tools-' + uuid.uuid4().hex[:8])
scratch.mkdir(parents=True)
home = scratch / 'home'
home.mkdir()
(home / 'models.json').write_bytes((root / 'config/models.json').read_bytes())
# This MCP exposes one read-only tool and no credentials.
mcp = scratch / 'fixture-mcp.py'
mcp.write_text('''import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request: continue
    method = request['method']
    if method == 'initialize': result = {'protocolVersion': request['params']['protocolVersion'], 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'owned-fixture', 'version': '1'}}
    elif method == 'tools/list': result = {'tools': [{'name': 'status', 'description': 'Read-only owned local fixture status.', 'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}, 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}]}
    elif method == 'tools/call': result = {'content': [{'type': 'text', 'text': 'MCP_LOCAL_FIXTURE_OK'}]}
    else: result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
''', encoding='utf-8')
observed, failures, results = [], [], []
phase = 0

def streamed_reply(reply, names):
    choice = reply['choices'][0]
    message = choice['message']
    deltas = []
    if message.get('content'):
        text = message['content']
        deltas.extend({'content': part} for part in (text[:len(text)//2], text[len(text)//2:]))
    for index, call in enumerate(message.get('tool_calls', [])):
        arguments = call['function']['arguments']
        deltas.append({'tool_calls': [{'index': index, 'id': call['id'], 'type': 'function',
            'function': {'name': call['function']['name'], 'arguments': arguments[:len(arguments)//2]}}]})
        deltas.append({'tool_calls': [{'index': index, 'function': {'arguments': arguments[len(arguments)//2:]}}]})
    chunks = [{'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]} for delta in deltas]
    chunks.append({'choices': [{'index': 0, 'delta': {}, 'finish_reason': choice['finish_reason']}]})
    wire = b''.join(('data: ' + json.dumps(chunk) + '\n\n').encode() for chunk in chunks) + b'data: [DONE]\n\n'
    return stream_response_events(io.BytesIO(wire), names)

class Backend(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        global phase
        try:
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            results.extend(item.get('output', '') for item in payload.get('input', []) if item.get('type') in {'function_call_output', 'custom_tool_call_output'})
            gateway = GatewayCore('fixture_capability_12345678901234567890', server.server_port, set(), lambda p: 'dummy-provider-fixture')
            prepared, _, _ = prepare_routed_request(gateway, gateway.prefix + '/backend-api/codex/responses', [('Host', gateway.host), ('Authorization', 'Bearer dummy-native-fixture'), ('Content-Type', 'application/json')], json.dumps(payload).encode())
            forwarded = json.loads(prepared.body)['input']
            for call in payload.get('input', []):
                if call.get('type') == 'custom_tool_call':
                    wire_call = next(item for item in forwarded if item.get('type') == 'function_call' and item.get('call_id') == call['call_id'])
                    assert json.loads(wire_call['arguments']) == {'input': call['input']}
                    assert any(item.get('type') == 'function_call_output' and item.get('call_id') == call['call_id'] for item in forwarded)
            names = prepared.tools
            inventory = {(ns, name): wire for wire, (ns, name) in names.from_wire.items()}
            observed.append(inventory)
            (scratch / 'tool-inventory.json').write_text(json.dumps([{'namespace': ns, 'name': name} for ns, name in inventory], indent=2))
            # New threads must use the same V2 contracts as current ChatGPT.
            spawn = next(t for t in names.tools if names.from_wire[t['name']][1] == 'spawn_agent')
            assert {'task_name', 'message'} <= set(spawn['parameters']['properties'])
            if phase == 0:
                wire = next(w for (ns, name), w in inventory.items() if name == 'apply_patch')
                args = {'input': '*** Begin Patch\n*** Add File: parity-fixture.txt\n+NATIVE_PATCH_FIXTURE_OK\n*** End Patch'}
            elif phase in {1, 2}:
                wire = next((w for (ns, name), w in inventory.items() if name == 'status' or name.endswith('__status')), None)
                if wire is None and phase == 1:
                    wire = next(w for (ns, name), w in inventory.items() if name == 'tool_search')
                    args = {'query': 'owned fixture status'}
                elif wire is None: raise AssertionError('Owned MCP discovery returned no callable schema')
                else: args = {}
            else:
                reply = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'NATIVE_CLIENT_FIXTURE_COMPLETE'}}]}
                wire = None
            if wire:
                reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [{'id': 'fixture_call_' + str(phase), 'type': 'function', 'function': {'name': wire, 'arguments': json.dumps(args)}}]}}]}
            phase += 1
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            for frame, _ in streamed_reply(reply, names):
                self.wfile.write(frame)
                self.wfile.flush()
            self.wfile.flush()
        except Exception as error:
            failures.append(type(error).__name__ + ': ' + str(error))
            self.send_error(500)

server = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
threading.Thread(target=server.serve_forever, daemon=True).start()
config = '\n'.join([
    'model = "zai/glm-5.3-flash"', 'model_provider = "fixture"',
    'model_catalog_json = ' + json.dumps(str(home / 'models.json')),
    'approval_policy = "never"', 'sandbox_mode = "workspace-write"',
    '[features]', 'multi_agent = true',
    '[model_providers.fixture]', 'name = "Owned local fixture"',
    'base_url = "http://127.0.0.1:' + str(server.server_port) + '/v1"',
    'wire_api = "responses"', 'env_key = "CODEX_LOCAL_FIXTURE_KEY"',
    'request_max_retries = 0', 'stream_max_retries = 0',
    '[mcp_servers.fixture]', 'command = ' + json.dumps(sys.executable),
    'args = ' + json.dumps([str(mcp)]),
])
(home / 'config.toml').write_text(config, encoding='utf-8')
environment = dict(os.environ, CODEX_HOME=str(home), CODEX_LOCAL_FIXTURE_KEY='dummy-owned-local-fixture-only')
# No inherited native/provider API key or token is needed by this subprocess.
for key in list(environment):
    if any(part in key.upper() for part in ('API_KEY', 'ACCESS_TOKEN', 'AUTH_TOKEN')): environment.pop(key)
try:
    result = subprocess.run([str(installed / 'resources/codex.exe'), 'exec', '--ephemeral', '--skip-git-repo-check', '--color', 'never', '-C', str(scratch), 'Run the owned local parity fixture using the advertised patch and read-only fixture MCP tools. Do not create or message any subagent.'], env=environment, capture_output=True, timeout=90)
    # Raw runtime output remains private in the ignored scratch directory.
    (scratch / 'runtime-output.txt').write_bytes(result.stdout + result.stderr)
    assert not failures, failures[:1]
    assert result.returncode == 0, 'Native fixture failed; inspect ignored scratch runtime-output.txt locally'
    patch_file = scratch / 'parity-fixture.txt'
    patch_worked = patch_file.exists() and patch_file.read_text().strip() == 'NATIVE_PATCH_FIXTURE_OK'
    patch_blocked = b'patch rejected: writing is blocked by read-only sandbox' in result.stderr
    assert patch_worked or patch_blocked, 'Native patch neither ran nor returned the native permission rejection'
    (scratch / 'tool-result-metadata.json').write_text(json.dumps({'result_types': [type(r).__name__ for r in results], 'results': results}, indent=2), encoding='utf-8')
    assert any(name == 'status' or name.endswith('__status') for inventory in observed for ns, name in inventory), 'MCP fixture was not advertised'
    assert 'MCP_LOCAL_FIXTURE_OK' in json.dumps(results), 'MCP fixture was not executed; inspect ignored scratch tool-result-metadata.json locally'
    print('PASS: installed Codex consumes streamed Chat Completions text and fragmented native patch/MCP calls with its own sandbox policy. No real provider, tunnel or subagent used.')
finally:
    server.shutdown(); server.server_close()
