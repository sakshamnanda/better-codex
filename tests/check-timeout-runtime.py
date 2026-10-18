"""Installed Codex must stop on one failed external request; local mocks only."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import uuid

root = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(root / 'src/desktop'), str(root / 'src/gateway')]
import runtime_mixed as mixed

selected = root / os.environ.get('BETTER_CODEX_TEST_DEPLOYMENT', (root / '.local/deployment-path.txt').read_text().strip())
manifest = json.loads((selected / 'Deployment.json').read_text())
installed = Path(manifest['source_app'])
for name, expected in manifest['installed_file_hashes'].items():
    with (installed / name).open('rb') as handle:
        assert hashlib.file_digest(handle, 'sha256').hexdigest() == expected

scratch = root / '.local/test-work' / ('timeout-runtime-' + uuid.uuid4().hex[:8])
home = scratch / 'home'
home.mkdir(parents=True)
(home / 'models.json').write_bytes((root / 'config/models.json').read_bytes())
message = 'Provider response timed out; no automatic retry was made'
attempts = []
streaming_failure = False

class FailedStream(io.BytesIO):
    status = 200
    headers = type('Headers', (), {'get_content_type': lambda self: 'text/event-stream'})()

def timeout(*args, **kwargs):
    attempts.append(True)
    if streaming_failure:
        events = [{'type': 'response.created', 'response': {'output': []}},
                  {'type': 'error', 'code': 'provider_test_error', 'message': message}]
        return FailedStream(b''.join(('data: ' + json.dumps(event) + '\n\n').encode() for event in events))
    body = json.dumps({'error': {'code': 'provider_test_error', 'message': message}}).encode()
    raise urllib.error.HTTPError('http://fixture.invalid/responses', 504, 'fixture', {}, io.BytesIO(body))

mixed.open_upstream = timeout
mixed.record = lambda event: None
server = ThreadingHTTPServer(('127.0.0.1', 0), mixed.MixedGateway)
server.capability = 'owned_timeout_fixture_12345678901234567890'
server.native_models = set()
server.external_url = 'http://fixture.invalid/responses'
threading.Thread(target=server.serve_forever, daemon=True).start()
config = '\n'.join([
    'model = "z-ai/glm-5.3-flash-uncensored"', 'model_provider = "fixture"',
    'model_catalog_json = ' + json.dumps(str(home / 'models.json')),
    'approval_policy = "never"', 'sandbox_mode = "read-only"',
    '[model_providers.fixture]', 'name = "Owned timeout fixture"',
    'base_url = ' + json.dumps(f'http://127.0.0.1:{server.server_port}/g/{server.capability}/backend-api/codex'),
    'wire_api = "responses"', 'env_key = "CODEX_LOCAL_FIXTURE_KEY"',
    # Keep default retry settings to verify the desktop-facing HTTP response.
])
(home / 'config.toml').write_text(config, encoding='utf-8')
environment = dict(os.environ, CODEX_HOME=str(home))
for key in list(environment):
    if any(part in key.upper() for part in ('API_KEY', 'ACCESS_TOKEN', 'AUTH_TOKEN')):
        environment.pop(key)
environment['CODEX_LOCAL_FIXTURE_KEY'] = 'dummy-owned-timeout-fixture'
try:
    for streaming_failure in (False, True):
        attempts.clear()
        started = time.monotonic()
        result = subprocess.run([str(installed / 'resources/codex.exe'), 'exec', '--ephemeral',
            '--skip-git-repo-check', '--color', 'never', '-C', str(scratch),
            'Reply to this owned timeout fixture. Do not execute tools.'],
            env=environment, capture_output=True, timeout=45)
        (scratch / f'runtime-output-{streaming_failure}.txt').write_bytes(result.stdout + result.stderr)
        assert result.returncode != 0, 'Timeout was reported as success'
        assert len(attempts) == 1, f'Expected one request; received {len(attempts)} (streaming={streaming_failure})'
        assert message.encode() in result.stdout + result.stderr, 'Runtime hid the timeout message'
        assert time.monotonic() - started < 30, 'Runtime kept waiting after the error'
    print('PASS: installed Codex shows HTTP and streamed timeouts without repeating the provider attempt; default retries stop locally. No provider, real profile, credentials, tools or app restart used.')
finally:
    server.shutdown()
    server.server_close()
