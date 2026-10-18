"""Reasoning content parts stay private; answers and real tool calls survive."""
from pathlib import Path
import copy
import io
import json
import sys

root = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(root / 'src/desktop'), str(root / 'src/gateway')]
from runtime_mixed import desktop_external_event
from core import ToolNames
from provider_relay import translated_events

private = 'PRIVATE_REASONING_FIXTURE <｜begin▁of▁sentence｜> ="unknown"> </message>'
reasoning = {'type': 'reasoning', 'id': 'rs_fixture', 'content': [{'type': 'reasoning_text', 'text': private}]}
answer = {'type': 'message', 'id': 'msg_fixture', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Answer fixture'}]}
call = {'type': 'function_call', 'id': 'fc_fixture', 'call_id': 'call_fixture', 'name': 'functions__fixture_echo', 'arguments': '{"text":"OK"}'}
events = [
    {'type': 'response.created', 'response': {'output': []}},
    {'type': 'response.output_item.added', 'output_index': 0, 'item': {**reasoning, 'content': []}},
    {'type': 'response.content_part.added', 'item_id': reasoning['id'], 'output_index': 0, 'content_index': 0, 'part': {'type': 'reasoning_text', 'text': ''}},
    {'type': 'response.reasoning_text.delta', 'item_id': reasoning['id'], 'delta': private},
    {'type': 'response.reasoning_text.done', 'item_id': reasoning['id'], 'text': private},
    {'type': 'response.content_part.done', 'item_id': reasoning['id'], 'output_index': 0, 'content_index': 0, 'part': reasoning['content'][0]},
    {'type': 'response.output_item.done', 'output_index': 0, 'item': reasoning},
    {'type': 'response.output_item.added', 'output_index': 1, 'item': {**answer, 'content': []}},
    {'type': 'response.content_part.added', 'item_id': answer['id'], 'part': {'type': 'output_text', 'text': ''}},
    {'type': 'response.output_text.delta', 'item_id': answer['id'], 'delta': 'Answer fixture'},
    {'type': 'response.output_text.done', 'item_id': answer['id'], 'text': 'Answer fixture'},
    {'type': 'response.content_part.done', 'item_id': answer['id'], 'part': answer['content'][0]},
    {'type': 'response.output_item.done', 'output_index': 1, 'item': answer},
    {'type': 'response.output_item.added', 'output_index': 2, 'item': {**call, 'arguments': ''}},
    {'type': 'response.function_call_arguments.delta', 'output_index': 2, 'item_id': call['id'], 'delta': call['arguments']},
    {'type': 'response.function_call_arguments.done', 'output_index': 2, 'item_id': call['id'], 'arguments': call['arguments']},
    {'type': 'response.output_item.done', 'output_index': 2, 'item': call},
    {'type': 'response.completed', 'response': {'status': 'completed', 'output': [reasoning, answer, call]}},
]
original = copy.deepcopy(events)
names = ToolNames([{'type': 'namespace', 'name': 'functions', 'tools': [{'type': 'function', 'name': 'fixture_echo', 'parameters': {'type': 'object'}}]}])
stream = io.BytesIO(''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode())
visible = [filtered for _, event in translated_events(stream, names) if event and (filtered := desktop_external_event(event)) is not None]
assert private not in json.dumps(visible)
assert len(visible) == len(events) - 6
assert visible[-1]['response']['output'][0] == answer
assert visible[-1]['response']['output'][1] == {**call, 'name': 'fixture_echo', 'namespace': 'functions'}
assert any(event['type'] == 'response.function_call_arguments.delta' and event['delta'] == call['arguments'] for event in visible)
assert any(event['type'] == 'response.content_part.done' and event['part'] == answer['content'][0] for event in visible)
assert desktop_external_event({'type': 'response.content_part.done', 'part': {'type': 'summary_text', 'text': private}}) is None
assert events == original
print('PASS: DeepSeek reasoning parts/deltas/completions hidden; answers, tool arguments, namespace mapping and completion preserved without mutating input.')
