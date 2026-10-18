"""Bound external chat waits without running tools or touching native requests."""
from pathlib import Path
import copy
import io
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src/gateway'))
from core import CHAT_WAIT_MAX_MS, GatewayCore, GatewayError, ToolNames
from chat_bridge import response_events
from provider_relay import translated_events

definition = {'type': 'function', 'name': 'wait_threads', 'parameters': {
    'type': 'object', 'properties': {
        'targets': {'type': 'array', 'minItems': 1, 'maxItems': 8},
        'timeoutMs': {'type': 'integer', 'minimum': 0, 'maximum': 120000},
    }, 'required': ['targets'], 'additionalProperties': False}}
declarations = [{'type': 'namespace', 'name': 'codex_app', 'tools': [definition]}]
original = copy.deepcopy(declarations)
wire = 'codex_app__wait_threads'
targets = [{'threadId': 'synthetic-thread', 'hostId': 'local', 'afterCursor': 'synthetic-cursor'}]

for timeout in (None, 0, 60000, 120000, 300000, 10**30, '300000', True, -1):
    outer = ToolNames(declarations)
    inner = ToolNames(outer.tools)
    arguments = {'targets': targets}
    if timeout is not None:
        arguments['timeoutMs'] = timeout
    expected = {**arguments}
    if type(timeout) is int and timeout > CHAT_WAIT_MAX_MS:
        expected['timeoutMs'] = CHAT_WAIT_MAX_MS
    call = {'type': 'function_call', 'name': wire, 'id': 'fc_fixture',
            'call_id': 'call_fixture', 'arguments': json.dumps(arguments)}
    result = outer.response_item(call)
    assert json.loads(result['arguments']) == expected
    assert result['namespace'] == 'codex_app' and result['name'] == 'wait_threads'
    assert result['call_id'] == call['call_id'] and call['arguments'] == json.dumps(arguments)
    # Exercise both provider response formats, including fragmented SSE JSON.
    source = [
        {'type': 'response.output_item.added', 'output_index': 0, 'item': {**call, 'arguments': ''}},
        *[{'type': 'response.function_call_arguments.delta', 'output_index': 0,
           'item_id': call['id'], 'delta': chunk}
          for chunk in (call['arguments'][:30], call['arguments'][30:])],
        {'type': 'response.function_call_arguments.done', 'item_id': call['id'], 'arguments': call['arguments']},
        {'type': 'response.output_item.done', 'output_index': 0, 'item': call},
        {'type': 'response.completed', 'response': {'output': [call]}},
    ]
    raw = b''.join(('data: ' + json.dumps(event) + '\n\n').encode() for event in source)
    reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
        {'id': call['call_id'], 'type': 'function', 'function': {'name': wire, 'arguments': call['arguments']}}]}}]}
    chat = b''.join(frame for frame, _ in response_events(reply, inner))
    for stream in (raw, chat):
        outer = ToolNames(declarations)
        events = [event for _, event in translated_events(io.BytesIO(stream), outer) if event]
        delta = ''.join(e['delta'] for e in events if e['type'] == 'response.function_call_arguments.delta')
        assert json.loads(delta) == expected
        assert all(json.loads(e['arguments']) == expected for e in events if e['type'] == 'response.function_call_arguments.done')
        assert json.loads(events[-1]['response']['output'][0]['arguments']) == expected

assert declarations == original, 'Caller schemas were mutated'
strict = copy.deepcopy(declarations)
strict[0]['tools'][0]['parameters']['properties']['timeoutMs']['maximum'] = 60000
names = ToolNames(strict)
assert json.loads(names.response_item({**call, 'arguments': '{"timeoutMs":300000}'})['arguments'])['timeoutMs'] == 60000
discovered = ToolNames([], [declarations])
assert discovered.chat_wait_limits == {wire: 120000}
for namespace in (None, 'unrelated'):
    names = ToolNames([definition] if namespace is None else [{'type': 'namespace', 'name': namespace, 'tools': [definition]}])
    result = names.response_item({**call, 'name': names.tools[0]['name'], 'arguments': '{"timeoutMs":300000}'})
    assert json.loads(result['arguments'])['timeoutMs'] == 300000
for malformed in ('{bad', '[]'):
    try:
        ToolNames(declarations).response_item({**call, 'arguments': malformed})
        raise AssertionError('Malformed wait arguments accepted')
    except GatewayError:
        pass

core = GatewayCore('fixture_capability_12345678901234567890', 12345, {'native-fixture'}, lambda _: 'provider-fixture')
headers = [('Host', core.host), ('Authorization', 'Bearer native-fixture'), ('Content-Type', 'application/json')]
for model in ('zai/glm-5.3-flash', '@preset/deepseek-flash-latest', 'space-bunny-free', 'step-5-preview-free', 'native-fixture'):
    payload = {'model': model, 'instructions': 'Keep project permissions.', 'input': [], 'tools': declarations}
    body = json.dumps(payload).encode()
    prepared = core.prepare('POST', core.prefix + '/backend-api/codex/responses', headers, body)
    if model == 'native-fixture':
        assert prepared.body == body and prepared.tools is None
    else:
        forwarded = json.loads(prepared.body)
        assert '0 to 120000 milliseconds' in forwarded['instructions']
        assert 'do not repeat the same rejected call' in forwarded['instructions']
        assert 'Keep project permissions.' in forwarded['instructions']
        assert forwarded['tools'][0]['parameters']['properties']['timeoutMs']['maximum'] == 120000
        assert forwarded['tools'][0]['parameters']['required'] == ['targets']
print('PASS: external waits capped at two minutes; SSE fragments, completed calls and both relays agree; cursors, stricter limits, discovery, unrelated tools and native requests preserved. Offline only.')
