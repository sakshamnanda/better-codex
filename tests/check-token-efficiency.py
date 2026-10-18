"""Bound future terminal output without rewriting commands or saved evidence."""
from pathlib import Path
import copy
import io
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src/gateway'))
from core import GatewayCore, GatewayError, ToolNames, TOKEN_EFFICIENCY, PROJECT_WORKFLOW, current_route_instructions
from chat_bridge import response_events
from provider_relay import translated_events

terminal = {'type':'function', 'name':'exec_command', 'parameters':{'type':'object',
    'properties':{'cmd':{'type':'string'}, 'max_output_tokens':{'type':'number'}}, 'required':['cmd']}}
poll = {**terminal, 'name':'write_stdin'}
declarations = [{'type':'namespace', 'name':'functions', 'tools':[terminal, poll]}]
original = copy.deepcopy(declarations)
for name in ('exec_command', 'write_stdin'):
    for cap in ('omitted', 8000, 0, None):
        outer = ToolNames(declarations)
        inner = ToolNames(outer.tools)
        args = {'cmd':'OWNED_COMMAND_UNCHANGED'}
        if cap != 'omitted':args['max_output_tokens'] = cap
        reply = {'choices':[{'finish_reason':'tool_calls', 'message':{'tool_calls':[{
            'id':'owned_call', 'type':'function', 'function':{'name':'functions__'+name, 'arguments':json.dumps(args)}}]}}]}
        frames = b''.join(frame for frame,event in response_events(reply, inner))
        events = [event for frame,event in translated_events(io.BytesIO(frames), outer) if event]
        output = events[-1]['response']['output'][0]
        converted = json.loads(output['arguments'])
        assert converted == {**args, 'max_output_tokens':2000 if cap == 'omitted' else cap}
        assert converted['cmd'] == args['cmd'] and output['call_id'] == 'owned_call'
        deltas = [event['delta'] for event in events if event['type'] == 'response.function_call_arguments.delta']
        done = [event['arguments'] for event in events if event['type'] == 'response.function_call_arguments.done']
        assert json.loads(''.join(deltas)) == converted and len(done) == 1 and json.loads(done[0]) == converted
        assert outer.response_item({'type':'function_call', 'name':'functions__'+name, 'arguments':output['arguments']})['arguments'] == output['arguments']
assert declarations == original

# The unnamespaced native terminal uses the same default at both hops.
names = ToolNames([terminal])
assert names.tools[0]['parameters']['properties']['max_output_tokens']['default'] == 2000
assert json.loads(names.response_item({'type':'function_call', 'name':'exec_command', 'arguments':'{"cmd":"fixture"}'})['arguments'])['max_output_tokens'] == 2000
for args in ('[]', 'null', 'invalid'):
    try:names.response_item({'type':'function_call', 'name':'exec_command', 'arguments':args});raise AssertionError('Malformed terminal arguments accepted')
    except GatewayError as error:assert error.status == 502

# Do not add unsupported fields or affect a similarly named third-party tool.
for declarations in ([{**terminal, 'parameters':{'type':'object','properties':{'cmd':{'type':'string'}}}}],
                     [{'type':'namespace','name':'mcp_fixture','tools':[terminal]}],
                     [{**terminal,'parameters':{**terminal['parameters'],'required':['cmd','max_output_tokens']}}],
                     [{**terminal,'parameters':{**terminal['parameters'],'properties':{'max_output_tokens':{'type':['integer','null']}}}}],
                     [{**terminal,'parameters':{**terminal['parameters'],'properties':{'max_output_tokens':{'type':'integer','maximum':100}}}}]):
    names=ToolNames(declarations);wire=names.tools[0]['name']
    assert json.loads(names.response_item({'type':'function_call','name':wire,'arguments':'{"cmd":"fixture"}'})['arguments']) == {'cmd':'fixture'}

# Two gateway passes deliver shared guidance once and preserve every tool result.
core=GatewayCore('fixture_capability_12345678901234567890',12345,{'native-fixture'},lambda p:'owned-provider-key')
headers=[('Host',core.host),('Authorization','Bearer owned-native-key'),('Content-Type','application/json')]
path=core.prefix+'/backend-api/codex/responses'
history=[{'role':'user','content':'OWNED_REQUIRED_TASK_AND_INSTRUCTIONS'},
         {'type':'function_call','call_id':'old','name':'exec_command','arguments':'{"cmd":"prior command"}'},
         {'type':'function_call_output','call_id':'old','output':'IMPORTANT_EVIDENCE\n' * 10000}]
payload={'model':'z-ai/glm-5.3-flash-uncensored','instructions':'OWNED_PROJECT_INSTRUCTIONS','input':history,'tools':[terminal]}
source=copy.deepcopy(payload)
first=core.prepare('POST',path,headers,json.dumps(payload).encode())
second=core.prepare('POST',path,headers,first.body)
forwarded=json.loads(second.body)
assert forwarded['input'] == json.loads(first.body)['input']
assert forwarded['input'][-1]['output'] == history[-1]['output']
assert payload == source
for text in (TOKEN_EFFICIENCY, PROJECT_WORKFLOW, current_route_instructions(payload['model'],'nanogpt')):
    assert forwarded['instructions'].count(text) == 1
assert 'OWNED_PROJECT_INSTRUCTIONS' in forwarded['instructions']
native=json.dumps({**payload,'model':'native-fixture'}).encode()
assert core.prepare('POST',path,headers,native).body == native
print('PASS: bounded terminal defaults across both streamed hops, explicit limits/schema constraints/native routing preserved, complete saved evidence and single shared guidance.')
