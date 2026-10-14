"""Opt-in GLM recovery test using fictitious agents; never executes agent calls.

Uses the saved Merge key only with its fixed endpoint. Two short paid provider
requests. Never prints credentials, prompts, returned agent IDs or replies.
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/gateway'))
from core import GatewayCore, GatewayError
from model_profiles import load_profiles, apply_profile
from provider_relay import open_provider, translated_events

parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true', help='Make two bounded paid Merge requests; no real agents')
if not parser.parse_args().live: parser.error('--live is required; this check uses the saved Merge key')
deployment = root / (root / '.local/deployment-path.txt').read_text().strip()
settings, profiles = load_profiles(root / 'config')
def key(provider):
    assert provider == 'merge'
    command = [str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(deployment / 'gateway/Provider-Credentials.ps1'), '-Mode', 'Token', '-Provider', provider]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: raise RuntimeError('Merge key unavailable')
    return result.stdout

for version in ('v1', 'v2'):
    definitions = []
    fields = {'message': {'type': 'string'}}
    if version == 'v2': fields['task_name'] = {'type': 'string'}
    definitions.append({'type': 'function', 'name': 'spawn_agent', 'description': 'Create a new worker. Returns its exact ID/task name.', 'parameters': {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}})
    messaging = 'send_input' if version == 'v1' else 'send_message'
    for name in (messaging, 'close_agent'):
        fields = {'target': {'type': 'string'}}
        if name == messaging: fields['message'] = {'type': 'string'}
        definitions.append({'type': 'function', 'name': name, 'description': 'Message an existing live worker.' if name == messaging else 'Close an existing worker.', 'parameters': {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}})
    namespace = 'multi_agent_v1' if version == 'v1' else 'collaboration'
    history = [
        {'role': 'user', 'content': 'Use a new worker to review the next fixture. The earlier worker Nash was closed.'},
        {'type': 'function_call', 'namespace': namespace, 'name': 'close_agent', 'call_id': 'fixture-close', 'arguments': '{"target":"fixture-nash-id"}'},
        {'type': 'function_call_output', 'call_id': 'fixture-close', 'output': '{"status":"closed"}'},
        {'type': 'function_call', 'namespace': namespace, 'name': messaging, 'call_id': 'fixture-mistake', 'arguments': '{"target":"fixture-nash-id","message":"review next fixture"}'},
        {'type': 'function_call_output', 'call_id': 'fixture-mistake', 'output': '{"error":"agent not found: it was closed"}'},
        {'role': 'user', 'content': 'Recover by creating a new worker now. Do not message or reopen the closed worker. Only choose the appropriate advertised tool; no tools will actually be executed in this diagnostic.'},
    ]
    gateway = GatewayCore('fixture_capability_12345678901234567890', 12345, set(), key)
    payload = apply_profile({'model': 'zai/glm-5.3-flash', 'instructions': 'This is a tool-selection diagnostic with synthetic conversation/agent results. Follow the last user request and the declared tool schemas.', 'input': history, 'tools': [{'type': 'namespace', 'name': namespace, 'tools': definitions}], 'reasoning': {'effort': 'low'}, 'max_output_tokens': 2048, 'stream': True}, settings, profiles)
    prepared = gateway.prepare('POST', gateway.prefix + '/backend-api/codex/responses', [('Host', gateway.host), ('Authorization', 'Bearer dummy-native-fixture'), ('Content-Type', 'application/json')], json.dumps(payload).encode())
    calls = []
    with open_provider(prepared) as upstream:
        for frame, event in translated_events(upstream, prepared.tools):
            if event and event.get('type') == 'response.output_item.done' and event.get('item', {}).get('type') == 'function_call': calls.append(event['item'])
    assert len(calls) == 1 and calls[0]['name'] == 'spawn_agent', 'GLM did not choose a single new-worker call; no agent action executed'
    arguments = json.loads(calls[0]['arguments'])
    required = ['message'] + (['task_name'] if version == 'v2' else [])
    assert set(arguments) == set(required) and all(isinstance(arguments[field], str) and arguments[field] for field in required), 'GLM creation arguments do not match the fixture contract'
    print('PASS: real GLM ' + version + ' recovered from the closed-worker error by requesting a new agent with matching arguments. No real agent created or messaged.')
