"""Compare comments and progress events against the guarded native SSE reader."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/gateway'))
from chat_bridge import response_events
from core import ToolNames

selected = root / (root / '.local/deployment-path.txt').read_text().strip()
manifest = json.loads((selected / 'Deployment.json').read_text())
installed = Path(manifest['source_app'])
for name, expected in manifest['installed_file_hashes'].items():
    with (installed / name).open('rb') as handle:
        assert hashlib.file_digest(handle, 'sha256').hexdigest() == expected

progress = False
class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Connection', 'close')
        self.end_headers()
        def send(event):
            self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
            self.wfile.flush()
        response = {'id': 'resp_owned_idle_fixture', 'status': 'in_progress', 'output': []}
        try:
            send({'type': 'response.created', 'response': response})
            for _ in range(10):
                time.sleep(0.2)
                if progress:
                    send({'type': 'response.in_progress', 'response': response})
                else:
                    self.wfile.write(b': provider progress\n\n'); self.wfile.flush()
            reply = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'IDLE_FIXTURE_OK'}}]}
            for frame, _ in response_events(reply, ToolNames([]), response_id=response['id'], text_streamed=True):
                self.wfile.write(frame); self.wfile.flush()
        except OSError:
            pass

server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
server.daemon_threads = True
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with tempfile.TemporaryDirectory(dir=root / '.local/test-work', prefix='sse-idle-') as directory:
        scratch = Path(directory); home = scratch / 'home'; home.mkdir()
        (home / 'models.json').write_bytes((root / 'config/models.json').read_bytes())
        (home / 'config.toml').write_text('\n'.join([
            'model = "z-ai/glm-5.3-flash-uncensored"', 'model_provider = "fixture"',
            'model_catalog_json = ' + json.dumps(str(home / 'models.json')),
            'approval_policy = "never"', 'sandbox_mode = "read-only"',
            '[model_providers.fixture]', 'name = "Owned SSE idle fixture"',
            'base_url = ' + json.dumps(f'http://127.0.0.1:{server.server_port}'),
            'wire_api = "responses"', 'env_key = "CODEX_LOCAL_FIXTURE_KEY"',
            'request_max_retries = 0', 'stream_max_retries = 0', 'stream_idle_timeout_ms = 500',
        ]), encoding='utf-8')
        environment = {key: value for key, value in os.environ.items()
                       if not any(part in key.upper() for part in ('API_KEY', 'ACCESS_TOKEN', 'AUTH_TOKEN'))}
        environment.update(CODEX_HOME=str(home), CODEX_LOCAL_FIXTURE_KEY='dummy-owned-idle-fixture')
        for progress in (False, True):
            result = subprocess.run([str(installed / 'resources/codex.exe'), 'exec', '--ephemeral',
                '--skip-git-repo-check', '--color', 'never', '-C', str(scratch),
                'Reply to the owned fixture. Do not use tools.'], env=environment,
                capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            output = result.stdout + result.stderr
            if progress:
                assert result.returncode == 0 and b'IDLE_FIXTURE_OK' in output, 'Progress events did not prevent native idle timeout'
            else:
                assert result.returncode != 0 and b'idle timeout' in output.lower(), 'Comments did not reproduce native idle timeout'
        print('PASS: native reader times out on SSE comments but stays active on progress events; dummy localhost only, no provider credentials or inference.')
finally:
    server.shutdown(); server.server_close()
