"""Native tools hidden; caller-tool relay and completed-response recovery work."""
from pathlib import Path
import json
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/gateway'))
from opencode_engine import OpenCodeEngine
from core import GatewayError
from provider_relay import public_relay_error


class FixtureEngine(OpenCodeEngine):
    def __init__(self, mode='relay'):
        self.mode = mode
        self.caller_tools = mode != 'disabled'
        self.tool_ids = ['codex_request', 'bash', 'read', 'write', 'edit', 'task', 'question', 'webfetch', 'glob', 'grep', 'skill']
        self.prompt = None

    def call(self, method, path, value=None, timeout=120):
        if path == '/session': return {'id': 'fixture-session'}
        if path == '/permission': return []
        if path.endswith('/abort'): return {}
        if method == 'POST':
            self.prompt = value
            enabled = {name for name, enabled in value['tools'].items() if enabled}
            assert enabled == ({'codex_request', 'bash'} if self.caller_tools else set())
            if self.mode == 'denied': return {'info': {'id': 'fixture-assistant', 'error': {'name': 'APIError', 'data': {'statusCode': 403, 'message': 'private upstream error fixture'}}}, 'parts': []}
            return {'info': {'id': 'fixture-assistant'}, 'parts': []}
        info = {'id': 'fixture-assistant', 'role': 'assistant', 'time': {'completed': 1}}
        if self.mode == 'relay':
            data = {'codex_request': True, 'name': 'exec_command', 'arguments_json': '{"cmd":"Write-Output fixture"}'}
            parts = [{'type': 'tool', 'tool': 'codex_request', 'state': {'status': 'completed', 'output': json.dumps(data)}}]
        elif self.mode == 'native':
            parts = [{'type': 'tool', 'tool': 'read', 'state': {'status': 'error'}}]
        else:
            parts = [{'type': 'text', 'text': 'Completed fixture reply'}]
            if self.mode == 'old': info['id'] = 'different-assistant'
            if self.mode == 'pending': info['time'] = {}
        return [{'info': info, 'parts': parts}]


payload = {'model': 'space-bunny-free', 'input': [{'role': 'user', 'content': 'fixture'}], 'instructions': 'Fixture requirements', 'tools': [{'name': 'exec_command', 'description': 'functions.exec_command: fixture'}], 'reasoning': {'effort': 'high'}}
engine = FixtureEngine()
reply = engine.complete(payload)
assert reply['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'exec_command'
assert engine.prompt['variant'] == 'high'
assert FixtureEngine('text').complete(payload)['choices'][0]['message']['content'] == 'Completed fixture reply'
assert FixtureEngine('disabled').complete(payload)['choices'][0]['message']['content'] == 'Completed fixture reply'
for mode in ('native', 'old', 'pending'):
    try: FixtureEngine(mode).complete(payload); raise AssertionError('Unsafe/stale response accepted')
    except GatewayError as error:
        assert error.status == (422 if mode == 'native' else 502)
try:
    FixtureEngine('denied').complete(payload); raise AssertionError('Provider denial hidden')
except GatewayError as error:
    assert error.status == 403 and str(error) == 'OpenCode Zen denied access to this model or client'
    assert public_relay_error(json.dumps({'error': {'code': 'provider_test_error', 'message': str(error)}}).encode()) == str(error)
message = 'OpenCode requested its own native tool; the request was aborted without approval'
assert public_relay_error(json.dumps({'error': {'code': 'provider_test_error', 'message': message}}).encode()) == message
assert public_relay_error(json.dumps({'error': {'code': 'provider_test_error', 'message': 'private-fixture-secret'}}).encode()) is None
assert public_relay_error(json.dumps({'error': {'code': 'arbitrary_upstream_error', 'message': message}}).encode()) is None
print('PASS: native tools hidden/blocked, data-only relay preserved, matching completed reply recovered, stale/pending output rejected, and error forwarding restricted to fixed public strings.')
