"""NanoGPT SSE translation and incremental delivery through both local hops."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import io
import json
import sys
import threading
import urllib.request

root = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(root / 'src/desktop'), str(root / 'src/gateway')]
from core import GatewayError, ToolNames
from chat_bridge import prepare_chat, stream_response_events, REASONING
import runtime_mixed as mixed

private = 'PRIVATE_STREAM_REASONING_FIXTURE'
def chunk(delta=None, finish=None):
    return {'choices': [{'index': 0, 'delta': delta or {}, 'finish_reason': finish}]}
def wire(value):
    return ('data: ' + (value if isinstance(value, str) else json.dumps(value)) + '\r\n\r\n').encode()
def translated(values, names=None):
    return [event for _, event in stream_response_events(io.BytesIO(b''.join(wire(v) for v in values)), names or ToolNames([])) if event]

request = prepare_chat({'model': 'fixture', 'input': []}, stream=True)
assert request['stream'] is True and request['stream_options'] == {'include_usage': True}
assert prepare_chat({'model': 'fixture', 'input': []})['stream'] is False
usage = {'prompt_tokens': 20, 'completion_tokens': 4, 'total_tokens': 24}
values = [chunk({'role': 'assistant'}), chunk({'reasoning': private}), chunk({'content': 'Hello '}),
          chunk({'content': 'world'}), chunk(finish='stop'), {'choices': [], 'usage': usage}, '[DONE]']
events = translated(values)
assert [e['delta'] for e in events if e['type'] == 'response.output_text.delta'] == ['Hello ', 'world']
assert len([e for e in events if e['type'] == 'response.created']) == 1
item = events[-1]['response']['output'][0]
assert item['content'][0]['text'] == 'Hello world'
assert events[-1]['response']['usage'] == {'input_tokens': 20, 'output_tokens': 4, 'total_tokens': 24}
assert all(e.get('item_id', item['id']) == item['id'] for e in events)
assert private not in json.dumps(events)
assert any(e['type'] == 'response.in_progress' for e in events)

# Parallel tool fragments retain their indices, namespaces, and reasoning context.
tools = [{'type': 'namespace', 'name': 'functions', 'tools': [
    {'type': 'function', 'name': name, 'parameters': {'type': 'object'}} for name in ('one', 'two')]}]
fragments = [chunk({'reasoning_content': private}),
    chunk({'tool_calls': [{'index': 1, 'id': 'call_two', 'type': 'function', 'function': {'name': 'functions__two', 'arguments': '{'}},
                          {'index': 0, 'id': 'call_one', 'type': 'function', 'function': {'name': 'functions__one', 'arguments': '{"x":'}}]}),
    chunk({'tool_calls': [{'index': 0, 'function': {'arguments': '1}'}}, {'index': 1, 'function': {'arguments': '}'}}]}),
    chunk(finish='tool_calls'), '[DONE]']
events = translated(fragments, ToolNames(tools))
calls = events[-1]['response']['output']
assert [(c['call_id'], c['namespace'], c['name'], c['arguments']) for c in calls] == [
    ('call_one', 'functions', 'one', '{"x":1}'), ('call_two', 'functions', 'two', '{}')]
assert REASONING.pop('call_one') == REASONING.pop('call_two') == private
assert private not in json.dumps(events)

for invalid in ([chunk({'content': 'partial'})], [chunk({'content': 'partial'}), '[DONE]'],
                [chunk({'content': 'partial'}, 'length'), '[DONE]'], ['broken JSON'],
                [{'error': {'message': private}}], [chunk({'tool_calls': [{'index': -1}]}), '[DONE]']):
    received = []
    try:
        for _, event in stream_response_events(io.BytesIO(b''.join(wire(v) for v in invalid)), ToolNames([])):
            if event: received.append(event)
    except GatewayError as error:
        assert private not in str(error)
        assert not any(e['type'] == 'response.completed' for e in received)
        assert not any(e['type'] == 'response.output_item.done' and e['item']['type'] == 'function_call' for e in received)
    else:
        raise AssertionError('Incomplete or invalid stream was accepted')

# Hold the upstream response open until private reasoning produces progress.
release = threading.Event()
class GatedReply(io.BytesIO):
    headers = type('Headers', (), {'get_content_type': lambda self: 'text/event-stream'})()
    def __init__(self):
        super().__init__(wire(chunk({'reasoning': private})))
        self.released = False
    def readline(self, size):
        line = super().readline(size)
        if not line and not self.released:
            if not release.wait(5): raise TimeoutError('Fixture consumer buffered the response')
            self.released = True
            self.seek(0)
            self.truncate()
            self.write(wire(chunk({'content': 'Visible before completion'})) + wire(chunk(finish='stop')) + wire({'choices': [], 'usage': usage}) + wire('[DONE]'))
            self.seek(0)
            line = super().readline(size)
        return line

relay = mixed.external_adapter
attempts = []
def provider(prepared, event=None):
    body = json.loads(prepared.body)
    assert body['stream'] is True and body['stream_options']['include_usage'] is True
    assert dict(prepared.headers)['Authorization'] == 'Bearer dummy-owned-provider-fixture'
    attempts.append(True)
    return GatedReply()
relay.key_supplier = lambda provider: 'dummy-owned-provider-fixture'
relay.open_provider = provider
relay.record = lambda event: None
relay.save_diagnostics = lambda: None
mixed.record = lambda event: None
inner = ThreadingHTTPServer(('127.0.0.1', 0), relay.RealGateway)
inner.prefix = '/owned-fixture'
inner.token = mixed.DUMMY
mid = 'z-ai/glm-5.3-flash-uncensored'
inner.catalog = {'models': [{'slug': mid}]}
outer = ThreadingHTTPServer(('127.0.0.1', 0), mixed.MixedGateway)
outer.capability = 'owned_stream_fixture_12345678901234567890'
outer.native_models = set()
outer.external_url = f'http://127.0.0.1:{inner.server_port}{inner.prefix}/backend-api/codex/responses'
for server in (inner, outer):
    threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    body = json.dumps({'model': mid, 'input': [{'role': 'user', 'content': 'fixture'}], 'tools': []}).encode()
    request = urllib.request.Request(f'http://127.0.0.1:{outer.server_port}/g/{outer.capability}/backend-api/codex/responses',
        data=body, headers={'Authorization': 'Bearer dummy-native-fixture', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=4) as reply:
        received = []
        while line := reply.readline():
            if line.startswith(b'data: '):
                event = json.loads(line[6:])
                received.append(event)
                if event['type'] == 'response.in_progress' and not release.is_set():
                    assert not any(e['type'] == 'response.output_text.delta' for e in received)
                    release.set()
                if event['type'] == 'response.output_text.delta':
                    assert release.is_set() and event['delta'] == 'Visible before completion'
        assert release.is_set() and received[-1]['type'] == 'response.completed'
        assert private not in json.dumps(received)
        assert len(attempts) == 1
finally:
    release.set()
    for server in (outer, inner):
        server.shutdown()
        server.server_close()
print('PASS: text arrives through both relays before upstream completion; tool fragments, reasoning privacy, usage and interrupted-stream errors verified offline.')
