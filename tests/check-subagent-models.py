"""All enabled picker models reach native and external delegation tool hints."""
from pathlib import Path
import copy
import gzip
import json
import sys

root = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(root/'src/desktop'), str(root/'src/gateway')]
import runtime_mixed as mixed
from core import GatewayCore, ToolNames
from provider_registry import public_catalog, PROVIDERS

catalog = public_catalog(json.loads((root/'config/models.json').read_text()), PROVIDERS)
visible = [m for m in catalog['models'] if m['visibility'] == 'list']
assert any(m['slug'] == 'glm-5.3-flash-abliterated' for m in visible)
schema = {'type':'object', 'properties':{'model':{'type':'string'}, 'fork_turns':{'type':'string'}},
          'required':['model'], 'additionalProperties':False}
tail = '        Spawns an agent. Full-history forks inherit their model and effort.'
spawn = {'type':'function', 'name':'spawn_agent', 'parameters':schema,
         'description':'\n        Available model overrides (optional):\n- `old/model`: Stale hint.\n'+tail}
other = {**spawn, 'name':'unrelated_tool'}
definitions = [{'type':'namespace', 'name':'collaboration', 'tools':[spawn, other]}]
core = GatewayCore('owned_fixture_capability_12345678901234567890', 12345,
                   {'gpt-6.1-sol'}, lambda provider:'dummy-provider')
headers = [('Host',core.host), ('Authorization','Bearer owned-native-auth-canary'),
           ('Content-Type','application/json'), ('Content-Encoding','gzip')]
for model in ('gpt-6.1-sol', '@preset/glm-flash-latest'):
    for placement in ('tools', 'additional_tools', 'tool_search_output'):
        request = {'model':model, 'input':[], 'instructions':'ORIGINAL_PERMISSIONS',
                   'reasoning':{'effort':'high'}}
        if placement == 'tools': request['tools'] = copy.deepcopy(definitions)
        else: request['input'] = [{'type':placement, 'tools':copy.deepcopy(definitions)}]
        if placement == 'tool_search_output': request['input'][0]['execution'] = 'client'
        original = copy.deepcopy(request)
        prepared, incoming, _ = mixed.prepare_routed_request(core, core.prefix+'/backend-api/codex/responses',
            headers, gzip.compress(json.dumps(request).encode()), catalog=catalog)
        tools = incoming['tools'] if placement == 'tools' else incoming['input'][0]['tools']
        updated, unchanged = tools[0]['tools']
        assert updated['parameters'] == schema and unchanged == other
        assert updated['description'].endswith(tail) and '`old/model`' not in updated['description']
        for m in catalog['models']:
            assert ('`'+m['slug']+'`' in updated['description']) == (m['visibility'] == 'list')
        assert 'low, high, max (default)' in updated['description']
        assert 'Service tiers: priority.' in updated['description']
        assert incoming['reasoning'] == original['reasoning']
        body = json.loads(prepared.body)
        assert body['model'] == model and 'ORIGINAL_PERMISSIONS' in body['instructions']
        assert not any(name.lower() == 'content-encoding' for name, _ in prepared.headers)
        if model != 'gpt-6.1-sol':
            assert b'owned-native-auth-canary' not in prepared.body
            name = next(t for t in prepared.tools.tools if t['name'].endswith('__spawn_agent'))
            assert all('`'+m['slug']+'`' in name['description'] for m in visible)
        before = copy.deepcopy(incoming)
        mixed.expand_subagent_models(incoming, catalog)
        assert incoming == before, 'Repeated requests duplicated the model hint'

# Settings changes use the same public filter as the picker and routing.
providers = copy.deepcopy(PROVIDERS)
providers['experiential']['enabled'] = False
filtered = public_catalog(json.loads((root/'config/models.json').read_text()), providers)
request = {'tools':copy.deepcopy(definitions)}
mixed.expand_subagent_models(request, filtered)
assert '`glm-5.3-flash-abliterated`' not in request['tools'][0]['tools'][0]['description']
v1 = {'type':'namespace', 'name':'multi_agent_v1', 'tools':[{**spawn, 'description':'Original spawn guidance.'}]}
request = {'tools':[v1]}
mixed.expand_subagent_models(request, catalog)
assert v1['tools'][0]['description'].endswith('Original spawn guidance.')
assert len(ToolNames(request['tools']).tools) == 1
print(f'PASS: all {len(visible)} enabled picker models advertised on native/external routes; schemas, guidance, efforts, permissions and credential isolation preserved; disabled models excluded.')
