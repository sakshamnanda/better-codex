"""External delegation text must never reach native models as ciphertext."""
from pathlib import Path
import copy
import json
import sys

root = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(root/'src/desktop'), str(root/'src/gateway')]
import runtime_mixed as mixed
from core import GatewayCore

message = 'Owned delegation task. Reply HANDOFF_FIXTURE_OK; no tools or file access.'
call = {'type':'function_call', 'namespace':'collaboration', 'name':'spawn_agent',
        'arguments':json.dumps({'task_name':'owned_child', 'fork_turns':'none',
                                'model':'gpt-6.1-sol', 'reasoning_effort':'high', 'message':message})}
handoff = {'type':'agent_message', 'id':'owned-agent-record', 'author':'owned-parent', 'recipient':'owned-child',
           'content':[{'type':'input_text', 'text':'A message from the parent follows.'},
                      {'type':'encrypted_content', 'encrypted_content':message}]}
original = copy.deepcopy(handoff)
mixed.PLAINTEXT_HANDOFFS.clear()
assert mixed.normalize_agent_handoffs([handoff]) == [handoff], 'Unknown opaque content was reinterpreted'
for invalid in ({**call, 'namespace':'unrelated'}, {**call, 'name':'exec_command'},
                {**call, 'encrypted_function_args':'owned-native-ciphertext'},
                {**call, 'arguments':'[]'}, {**call, 'arguments':'malformed'},
                {**call, 'arguments':json.dumps({'message':None})}):
    mixed.remember_external_handoffs({'type':'response.output_item.done', 'item':invalid})
    assert not mixed.PLAINTEXT_HANDOFFS
mixed.remember_external_handoffs({'type':'response.output_item.added', 'item':call})
mixed.remember_external_handoffs({'type':'response.completed', 'response':None})
mixed.remember_external_handoffs({'type':'response.completed', 'response':{'output':None}})
assert not mixed.PLAINTEXT_HANDOFFS
mixed.remember_external_handoffs({'type':'response.output_item.done', 'item':call})
normalized = mixed.normalize_agent_handoffs([handoff])[0]
assert normalized['content'][-1] == {'type':'input_text', 'text':message}
assert {k:v for k,v in normalized.items() if k != 'content'} == {k:v for k,v in handoff.items() if k != 'content'}
assert handoff == original

core = GatewayCore('owned_fixture_capability_12345678901234567890', 12345, {'gpt-6.1-sol'}, lambda provider:'dummy-provider')
headers = [('Host',core.host), ('Authorization','Bearer owned-native-auth-canary'), ('Content-Type','application/json')]
for model in ('gpt-6.1-sol', '@preset/glm-flash-latest', 'zai/glm-5.3-flash'):
    request = {'model':model, 'instructions':'ORIGINAL_PERMISSIONS', 'input':[handoff], 'tools':[], 'reasoning':{'effort':'high'}}
    prepared, _, _ = mixed.prepare_routed_request(core, core.prefix+'/backend-api/codex/responses', headers, json.dumps(request).encode())
    body = json.loads(prepared.body)
    assert message in json.dumps(body['input']) and 'ORIGINAL_PERMISSIONS' in body['instructions']
    assert message not in [part.get('encrypted_content') for item in body['input'] for part in item.get('content',[])]
    if model == 'gpt-6.1-sol':
        assert body['input'][0] == normalized and body['reasoning']['effort'] == 'high'
    else: assert b'owned-native-auth-canary' not in prepared.body

opaque = copy.deepcopy(handoff)
opaque['content'][-1]['encrypted_content'] = 'gAAAA_owned_real_native_ciphertext'
assert mixed.normalize_agent_handoffs([opaque]) == [opaque]
# Messages, reasoning and compaction items retain genuine native opaque state.
for kind in ('message','reasoning','compaction'):
    item = {**handoff, 'type':kind, 'encrypted_content':'owned-native-state'}
    assert mixed.normalize_agent_handoffs([item]) == [item]
for name in ('spawn_agent','followup_task','send_message','send_input'):
    mixed.PLAINTEXT_HANDOFFS.clear()
    mixed.remember_external_handoffs({'type':'response.completed', 'response':{'output':[{**call,'name':name}]}})
    assert mixed.normalize_agent_handoffs([handoff])[0] == normalized
mixed.PLAINTEXT_HANDOFFS.clear()
saved_call = {**call, 'call_id':'owned-saved-call'}
saved = {'model':'@preset/glm-flash-latest', 'input':[saved_call,
    {'type':'function_call_output', 'call_id':'owned-saved-call', 'output':'Owned worker created.'}],
    'tools':[], 'instructions':'ORIGINAL_PERMISSIONS'}
mixed.prepare_routed_request(core, core.prefix+'/backend-api/codex/responses', headers, json.dumps(saved).encode())
assert mixed.normalize_agent_handoffs([handoff])[0] == normalized, 'Saved parent task provenance was lost after restart'
assert mixed.normalize_agent_handoffs([opaque]) == [opaque], 'Saved history changed unrelated opaque content'
mixed.PLAINTEXT_HANDOFFS.clear()
saved['model'] = 'gpt-6.1-sol'
mixed.prepare_routed_request(core, core.prefix+'/backend-api/codex/responses', headers, json.dumps(saved).encode())
assert not mixed.PLAINTEXT_HANDOFFS, 'Native history was treated as external provenance'
for index in range(1025):
    mixed.remember_external_handoffs({'type':'response.output_item.done', 'item':{**call,'arguments':json.dumps({'message':str(index)})}})
assert len(mixed.PLAINTEXT_HANDOFFS) == 1024
mixed.PLAINTEXT_HANDOFFS.clear()
print('PASS: only observed external delegation arguments become plaintext; native opaque state, model/effort, permissions and credential isolation remain intact; provenance is bounded and contains hashes only.')
