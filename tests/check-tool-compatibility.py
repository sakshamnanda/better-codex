"""Client tools round-trip through both relays without executing any tool."""
from pathlib import Path
import copy
import io
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src/gateway'))
from core import GatewayCore, GatewayError, ToolNames, portable_history
from provider_relay import translated_events
from chat_bridge import response_events

declarations = [
    {'type': 'namespace', 'name': 'functions', 'tools': [
        {'type': 'function', 'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}},
        {'type': 'function', 'name': 'write_stdin', 'parameters': {'type': 'object', 'properties': {'session_id': {'type': 'integer'}, 'chars': {'type': 'string'}}}},
        {'type': 'custom', 'name': 'apply_patch', 'description': 'Apply an authorized patch.', 'format': {'type': 'grammar', 'syntax': 'lark', 'definition': 'start: /[\\s\\S]+/'}},
    ]},
    {'type': 'namespace', 'name': 'mcp__fixture_tunnel', 'tools': [
        {'type': 'function', 'name': 'read_status', 'defer_loading': True, 'parameters': {'type': 'object', 'properties': {'reference': {'type': 'string'}}, 'required': ['reference']}},
    ]},
    {'type': 'tool_search', 'execution': 'client', 'description': 'Discover permitted client tools.', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}},
]
outer = ToolNames(declarations)
inner = ToolNames(outer.tools)
assert all(t['type'] == 'function' and 'defer_loading' not in t for t in outer.tools)
assert outer.tools[3]['parameters'] == declarations[1]['tools'][0]['parameters']

patch = '*** Begin Patch\n*** Add File: fixture.txt\n+fixture\n*** End Patch'
for wire, args, expected in [
    ('functions__write_stdin', {'session_id': 13579, 'chars': 'fixture'}, {'type': 'function_call', 'namespace': 'functions', 'name': 'write_stdin', 'arguments': json.dumps({'session_id': 13579, 'chars': 'fixture'})}),
    ('mcp__fixture_tunnel__read_status', {'reference': 'fixture'}, {'type': 'function_call', 'namespace': 'mcp__fixture_tunnel', 'name': 'read_status', 'arguments': json.dumps({'reference': 'fixture'})}),
    ('functions__apply_patch', {'input': patch}, {'type': 'custom_tool_call', 'namespace': 'functions', 'name': 'apply_patch', 'input': patch}),
    ('tool_search', {'query': 'fixture status'}, {'type': 'tool_search_call', 'execution': 'client', 'arguments': {'query': 'fixture status'}}),
]:
    reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [{'id': 'call_fixture', 'type': 'function', 'function': {'name': wire, 'arguments': json.dumps(args)}}]}}]}
    upstream = io.BytesIO(b''.join(frame for frame, event in response_events(reply, inner)))
    events = [event for frame, event in translated_events(upstream, outer) if event]
    item = events[-1]['response']['output'][0]
    for key, value in expected.items(): assert item[key] == value, (key, item)
    assert item['call_id'] == 'call_fixture'
    if item['type'] == 'custom_tool_call':
        assert ''.join(e['delta'] for e in events if e['type'] == 'response.custom_tool_call_input.delta') == patch
        assert not any(e['type'].startswith('response.function_call_arguments') for e in events)
    outer = ToolNames(declarations)  # Stream state is per request.

history = [
    {'type': 'custom_tool_call', 'call_id': 'old-patch', 'namespace': 'functions', 'name': 'apply_patch', 'input': patch, 'status': 'completed'},
    {'type': 'custom_tool_call_output', 'call_id': 'old-patch', 'output': 'Success'},
    {'type': 'tool_search_call', 'execution': 'client', 'status': 'completed', 'call_id': 'old-search', 'arguments': {'query': 'status'}},
    {'type': 'tool_search_output', 'execution': 'client', 'status': 'completed', 'call_id': 'old-search', 'tools': [declarations[1]]},
]
portable = portable_history(history)
assert all(item['type'] == 'message' for item in portable)
assert 'Success' in json.dumps(portable) and 'mcp__fixture_tunnel__read_status' in json.dumps(portable)

core = GatewayCore('fixture_capability_12345678901234567890', 12345, {'native-fixture'}, lambda p: 'provider-fixture')
headers = [('Host', core.host), ('Authorization', 'Bearer native-secret-fixture'), ('Content-Type', 'application/json'), ('ChatGPT-Account-Id', 'private-account-fixture')]
payload = {'model': 'zai/glm-5.3-flash', 'input': history, 'tools': declarations, 'tool_choice': {'type': 'custom', 'namespace': 'functions', 'name': 'apply_patch'}}
prepared = core.prepare('POST', core.prefix + '/backend-api/codex/responses', headers, json.dumps(payload).encode())
assert json.loads(prepared.body)['tool_choice'] == {'type': 'function', 'name': 'functions__apply_patch'}
assert b'native-secret-fixture' not in prepared.body and dict(prepared.headers)['Authorization'] == 'Bearer provider-fixture'
discovered_payload = {**payload, 'tools': [declarations[-1]], 'tool_choice': 'auto'}
loaded = core.prepare('POST', core.prefix + '/backend-api/codex/responses', headers, json.dumps(discovered_payload).encode())
assert ('mcp__fixture_tunnel', 'read_status') in loaded.tools.to_wire, 'Schemas returned only in discovery history were lost'
payload['model'] = 'native-fixture'
original = json.dumps(payload).encode()
assert core.prepare('POST', core.prefix + '/backend-api/codex/responses', headers, original).body == original

for tool in ({'type': 'mcp', 'server_url': 'https://private.invalid', 'headers': {'Authorization': 'private'}}, {'type': 'tool_search', 'execution': 'server'}, {'type': 'function', 'name': 'fixture', 'headers': {'Authorization': 'private'}}):
    try: ToolNames([tool]); raise AssertionError('Hosted tool or undeclared credential metadata accepted')
    except GatewayError: pass
for arguments in ('{"wrong":"field"}', '{"input":42}', '{bad json'):
    try: ToolNames(declarations).response_item({'type': 'function_call', 'name': 'functions__apply_patch', 'arguments': arguments}); raise AssertionError('Malformed wrapper accepted')
    except GatewayError: pass
try:
    ToolNames(declarations).response_item({'type': 'custom_tool_call', 'name': 'unadvertised', 'input': 'fixture'}); raise AssertionError('Provider bypassed wrapper allowlist')
except GatewayError: pass
print('PASS: terminal session IDs, deferred MCP/tunnel function schemas, native patch text/streams, client discovery, cross-model history and forced choices round-trip; native requests untouched; hosted credentials and malformed calls rejected. No tools executed.')
