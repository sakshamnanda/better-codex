"""Exercise the installed engine against local fixtures, never a real provider."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
import sys
import threading
import uuid

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/gateway'))
import opencode_engine

deployment = root / (root / '.local/deployment-path.txt').read_text().strip()
scratch = root / '.local/test-work' / ('opencode-engine-' + uuid.uuid4().hex[:8])
dependency_source = deployment / 'support/opencode-runtime/config/opencode/node_modules'
shutil.copytree(dependency_source, scratch / 'config/opencode/node_modules')
offered = []


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        names = {tool['function']['name'] for tool in value.get('tools', [])}
        offered.append(names)
        assert names == {'codex_request', 'bash'}, 'Native tool exposed to inference model'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Connection', 'close')
        self.end_headers()
        if len(offered) == 1:
            relay = {'name': 'exec_command', 'arguments_json': '{"cmd":"Write-Output LOCAL_RELAY_FIXTURE"}'}
            delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call_fixture', 'type': 'function', 'function': {'name': 'codex_request', 'arguments': json.dumps(relay)}}]}
            finish = 'tool_calls'
        else:
            delta = {'role': 'assistant', 'content': 'Local fixture completed'}
            finish = 'stop'
        for partial, reason in ((delta, None), ({}, finish)):
            event = {'id': 'chat_fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'space-bunny-free', 'choices': [{'index': 0, 'delta': partial, 'finish_reason': reason}]}
            self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()


server = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
threading.Thread(target=server.serve_forever, daemon=True).start()
# Read existing verified executable/plugin; all generated engine data is isolated.
opencode_engine.ROOT = deployment
engine = opencode_engine.OpenCodeEngine(lambda provider: 'local-fixture-key-no-real-access')
engine.directory = scratch
try:
    engine.start(mock_url='http://127.0.0.1:' + str(server.server_port), caller_tools=True)
    assert engine.call('GET', '/config')['permission']['*'] == 'deny'
    payload = {'model': 'space-bunny-free', 'instructions': 'Use the caller relay for the fixture command.', 'input': [{'role': 'user', 'content': 'Request exec_command with the fixture command.'}], 'tools': [{'name': 'exec_command', 'description': 'functions.exec_command: fixture command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}], 'reasoning': {'effort': 'high'}}
    reply = engine.complete(payload)
    function = reply['choices'][0]['message']['tool_calls'][0]['function']
    assert function['name'] == 'exec_command'
    assert json.loads(function['arguments'])['cmd'] == 'Write-Output LOCAL_RELAY_FIXTURE'
    assert offered and all(names == {'codex_request', 'bash'} for names in offered)
    print('PASS: actual OpenCode engine hides native tools, preserves deny policy, and returns a Codex tool request without executing it; only local fixture requests used.')
finally:
    engine.stop()
    server.shutdown(); server.server_close()
