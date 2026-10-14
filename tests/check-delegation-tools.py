"""Readable tool identities, intact schemas/history and correct nested relay mapping."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src/gateway'))
from core import ToolNames, GatewayError

functions = [
    {'type': 'function', 'name': 'spawn_agent', 'parameters': {'type': 'object', 'properties': {'message': {'type': 'string'}, 'fork_context': {'type': 'boolean'}}, 'required': ['message']}},
    {'type': 'function', 'name': 'send_input', 'parameters': {'type': 'object', 'properties': {'target': {'type': 'string'}, 'message': {'type': 'string'}}, 'required': ['target','message']}},
    {'type': 'function', 'name': 'wait_agent', 'parameters': {'type': 'object', 'properties': {'targets': {'type': 'array'}, 'timeout_ms': {'type': 'integer'}}, 'required': ['targets']}},
    {'type': 'function', 'name': 'close_agent', 'parameters': {'type': 'object', 'properties': {'target': {'type': 'string'}}, 'required': ['target']}},
]
outer = ToolNames([{'type': 'namespace', 'name': 'multi_agent_v1', 'tools': functions}])
assert [tool['name'] for tool in outer.tools] == ['multi_agent_v1__' + tool['name'] for tool in functions]
assert [tool['parameters'] for tool in outer.tools] == [tool['parameters'] for tool in functions]
inner = ToolNames(outer.tools)
for definition in functions:
    original = {'type': 'function_call', 'namespace': 'multi_agent_v1', 'name': definition['name'], 'call_id': 'fixture-' + definition['name'], 'arguments': '{"fixture":true}'}
    wire = outer.request_item(original)
    assert inner.request_item(wire) == wire
    assert outer.response_item(inner.response_item(wire)) == original
guide = outer.delegation_guidance()
assert 'multi_agent_v1__spawn_agent' in guide and 'does not create or reopen' in guide
assert 'do not message that ID again' in guide and 'display nickname' in guide
assert inner.delegation_guidance() == ''  # The outer gateway has already supplied it.
assert ToolNames([{'type':'function','name':'exec_command'}]).tools[0]['name'] == 'exec_command'
long_names = ToolNames([{'type':'namespace','name':'namespace.with.long-punctuation-' * 3,'tools':[{'type':'function','name':'spawn_agent'}]}])
assert all(len(tool['name']) <= 64 for tool in long_names.tools)
try:
    ToolNames([{'type':'function','name':'multi_agent_v1__spawn_agent'},{'type':'namespace','name':'multi_agent_v1','tools':[functions[0]]}])
    raise AssertionError('Ambiguous tool aliases accepted')
except GatewayError: pass
print('PASS: readable delegation names; schemas and historical call IDs unchanged; nested response mapping exact; creation/message/closed-agent contracts supplied; collisions rejected.')
