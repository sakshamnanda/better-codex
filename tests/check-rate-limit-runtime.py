"""Verify the installed client's raw 429 behavior with an isolated local fixture."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
import queue
import time
import subprocess
import threading
import uuid

root = Path(__file__).resolve().parent.parent
selected = root / (root / '.local/deployment-path.txt').read_text().strip()
manifest = json.loads((selected / 'Deployment.json').read_text())
installed = Path(manifest['source_app'])
for name, expected in manifest['installed_file_hashes'].items():
    with (installed / name).open('rb') as handle:
        assert hashlib.file_digest(handle, 'sha256').hexdigest() == expected
scratch = root / '.local/test-work' / ('rate-limit-runtime-' + uuid.uuid4().hex[:8])
home = scratch / 'home'
home.mkdir(parents=True)
(home / 'models.json').write_bytes((root / 'config/models.json').read_bytes())
attempts = []
retry_after = False
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        attempts.append(True)
        body = b'{"error":{"message":"Owned local rate-limit fixture"}}'
        self.send_response(429)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        if retry_after:
            self.send_header('Retry-After', '1')
        self.end_headers()
        self.wfile.write(body)
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
(home / 'config.toml').write_text('\n'.join([
    'model = "z-ai/glm-5.3-flash-uncensored"', 'model_provider = "fixture"',
    'model_catalog_json = ' + json.dumps(str(home / 'models.json')),
    'approval_policy = "never"', 'sandbox_mode = "read-only"',
    '[model_providers.fixture]', 'name = "Owned rate-limit fixture"',
    'base_url = ' + json.dumps(f'http://127.0.0.1:{server.server_port}'),
    'wire_api = "responses"', 'env_key = "CODEX_LOCAL_FIXTURE_KEY"',
]), encoding='utf-8')
environment = dict(os.environ, CODEX_HOME=str(home))
for key in list(environment):
    if any(part in key.upper() for part in ('API_KEY', 'ACCESS_TOKEN', 'AUTH_TOKEN')):
        environment.pop(key)
environment['CODEX_LOCAL_FIXTURE_KEY'] = 'dummy-owned-rate-limit-fixture'
process = subprocess.Popen([str(installed / 'resources/codex.exe'), 'app-server', '--listen', 'stdio://'],
    cwd=scratch, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL, text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
mail = queue.Queue()
pending = []
identifier = 0
def read():
    for line in process.stdout:
        try: mail.put(json.loads(line))
        except ValueError: pass
threading.Thread(target=read, daemon=True).start()
def call(method, params):
    global identifier
    identifier += 1
    process.stdin.write(json.dumps({'id': identifier, 'method': method, 'params': params}) + '\n')
    process.stdin.flush()
    while True:
        value = mail.get(timeout=30)
        if value.get('id') == identifier:
            assert 'error' not in value, method
            return value.get('result', {})
        pending.append(value)
try:
    call('initialize', {'clientInfo': {'name': 'owned-rate-limit-fixture', 'version': '1'},
        'capabilities': {'experimentalApi': True}})
    process.stdin.write('{"method":"initialized"}\n'); process.stdin.flush()
    for retry_after in (False, True):
        attempts.clear()
        thread = call('thread/start', {'model': 'z-ai/glm-5.3-flash-uncensored', 'modelProvider': 'fixture',
            'ephemeral': True, 'cwd': str(scratch), 'approvalPolicy': 'never', 'sandbox': 'read-only'})['thread']['id']
        call('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': 'Owned local rate-limit fixture.'}]})
        events = []
        deadline = time.monotonic() + 45
        while True:
            remaining = deadline - time.monotonic()
            assert remaining > 0, ('Fixture timed out', retry_after, len(attempts))
            value = pending.pop(0) if pending else mail.get(timeout=remaining)
            events.append(value)
            if value.get('method') == 'turn/completed':
                assert value['params']['turn']['status'] == 'failed'
                break
        (scratch / f'runtime-output-{retry_after}.json').write_text(json.dumps(events, indent=2))
        print('RAW 429:', 'Retry-After present' if retry_after else 'no Retry-After', 'attempts', len(attempts), flush=True)
        assert len(attempts) == (6 if retry_after else 1), (retry_after, len(attempts))
        assert 'exceeded retry limit' in json.dumps(events)
finally:
    process.terminate()
    try: process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill(); process.wait(timeout=10)
    server.shutdown()
    server.server_close()
print('PASS: installed app-server raw 429 behavior captured with isolated loopback fixtures.')
