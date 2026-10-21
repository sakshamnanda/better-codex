"""Installed runtime GLM -> native/external delegation, isolated profile.

Default: localhost mocks only. --unfixed reproduces the ciphertext failure.
--live uses synthetic tasks, saved provider credentials and native sign-in;
no existing sessions, profile/config copies, project tools or desktop restart.
"""
from pathlib import Path
from http.server import ThreadingHTTPServer
from email.message import Message
import argparse
import hashlib
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('--unfixed', action='store_true')
parser.add_argument('--live', action='store_true')
parser.add_argument('--child-model', default='gpt-6.1-sol', help='Offline child route to verify')
args = parser.parse_args()
assert not (args.live and args.unfixed), 'The broken-path reproduction is offline only'
assert not args.live or args.child_model == 'gpt-6.1-sol', 'Alternate child routes are offline only'
root = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(root/'src/desktop'), str(root/'src/gateway')]
import runtime_mixed as mixed
from core import GatewayCore, ToolNames, GatewayError
from chat_bridge import response_events
from subagent_lifecycle import manage, LifecycleServer

selected = root/os.environ.get('BETTER_CODEX_TEST_DEPLOYMENT', (root/'.local/deployment-path.txt').read_text().strip())
manifest = json.loads((selected/'Deployment.json').read_text())
installed = Path(manifest['source_app'])
for name, expected in manifest['installed_file_hashes'].items():
    with (installed/name).open('rb') as handle:
        assert hashlib.file_digest(handle,'sha256').hexdigest() == expected
scratch = root/'.local/test-work'/('delegation-runtime-'+uuid.uuid4().hex[:8])
home = scratch/'home'
home.mkdir(parents=True)
(home/'models.json').write_bytes((root/'config/models.json').read_bytes())
parent_model = '@preset/glm-flash-latest'
child_model = args.child_model
message = 'Synthetic delegation diagnostic only. Do not use tools, read files or take actions. Reply exactly GLM_NATIVE_CHILD_OK.'
followup = 'Synthetic follow-up diagnostic only. Reply exactly GLM_NATIVE_CHILD_OK without tools.'
native_headers = None
if args.live:
    auth = json.loads((Path(os.environ['USERPROFILE'])/'.codex/auth.json').read_text())['tokens']
    native_headers = [('Authorization','Bearer '+auth['access_token']), ('ChatGPT-Account-Id',auth['account_id'])]
    auth = None
    mixed.external_adapter.KEY_STORAGE = selected/'gateway'

class Reply(io.BytesIO):
    status = 200
    headers = Message()
    headers['Content-Type'] = 'text/event-stream'
    def read1(self, size=-1): return self.read(size)

external_requests = 0
shell_environment_verified = False
tree_cleaned = threading.Event()
child_requests = []
old_open = mixed.open_upstream

def upstream(url, headers, body=None, *, timeout=120):
    global external_requests, shell_environment_verified
    payload = json.loads(body)
    if url == 'https://chatgpt.com/backend-api/codex/responses' or payload['model'] == child_model:
        assert payload['model'] == child_model and payload['reasoning']['effort'] == 'high'
        mislabeled = any(part.get('encrypted_content') == message
                         for item in payload['input'] for part in item.get('content',[]))
        has_task = any(part.get('type') == 'input_text' and message in part.get('text','')
                       for item in payload['input'] for part in item.get('content',[]))
        child_requests.append({'model':payload['model'], 'effort':payload['reasoning']['effort'],
                                'mislabeled_task':mislabeled, 'has_task':has_task})
        if args.live:
            assert not mislabeled and has_task, 'Unsafe synthetic handoff reached the native probe'
            trusted_headers = [(k,v) for k,v in headers if k.lower() not in {'authorization','chatgpt-account-id'}]
            return old_open(url, trusted_headers+native_headers, body)
        if mislabeled:
            return Reply(b'')  # Reproduce the real native EOF for plaintext in an opaque field.
        assert has_task
        reply = {'choices':[{'finish_reason':'stop','message':{'content':'GLM_NATIVE_CHILD_OK'}}]}
        return Reply(b''.join(frame for frame,_ in response_events(reply,ToolNames([]))))
    assert url == 'http://owned-fixture.invalid/responses'
    assert dict(headers)['Authorization'] == 'Bearer '+mixed.DUMMY
    external_requests += 1
    if external_requests > 12:
        raise GatewayError('Synthetic delegation request budget exceeded',502)
    if args.live:
        core = GatewayCore('owned_fixture_capability_12345678901234567890',12345,set(),mixed.external_adapter.key_supplier)
        prepared = core.prepare('POST',core.prefix+'/backend-api/codex/responses',
            [('Host',core.host),('Authorization','Bearer owned-local-fixture'),('Content-Type','application/json')],body)
        return mixed.external_adapter.open_provider(prepared)
    names = ToolNames(payload['tools'])
    if external_requests == 1:
        tool = next(t for t in names.tools if t['name'].endswith('__spawn_agent') or t['name'] == 'spawn_agent')
        from provider_registry import public_catalog, PROVIDERS
        visible = public_catalog(json.loads((root/'config/models.json').read_text()), PROVIDERS)['models']
        assert all('`'+m['slug']+'`' in tool['description'] for m in visible if m['visibility'] == 'list')
        arguments = {'task_name':'native_child_probe','fork_turns':'none','model':child_model,
                     'reasoning_effort':'high','message':message}
        reply = {'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{
            'id':'owned_delegation_call','type':'function',
            'function':{'name':tool['name'],'arguments':json.dumps(arguments)}}]}}]}
    elif external_requests == 2:
        tool = next(t for t in names.tools if t['name'].endswith('__exec_command') or t['name'] == 'exec_command')
        command = "if ($env:CODEX_THREAD_ID -eq '" + parent + "' -and (Test-Path -LiteralPath $env:BETTER_CODEX_SUBAGENTS)) { python \"$env:BETTER_CODEX_SUBAGENTS\" list; if ($LASTEXITCODE -eq 0) { Write-Output OWNED_SUBAGENT_ENV_OK } } else { Write-Error 'Cleanup environment unavailable'; exit 1 }"
        reply = {'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{
            'id':'owned_environment_call','type':'function',
            'function':{'name':tool['name'],'arguments':json.dumps({'cmd':command, 'max_output_tokens':200})}}]}}]}
    elif external_requests == 4:
        tool = next(t for t in names.tools if t['name'].endswith('__followup_task'))
        reply = {'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{
            'id':'owned_restart_call','type':'function',
            'function':{'name':tool['name'],'arguments':json.dumps({
                'target':'native_child_probe','message':followup})}}]}}]}
    elif external_requests == 6:
        tool = next(t for t in names.tools if t['name'].endswith('__list_agents'))
        reply = {'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{
            'id':'owned_tree_probe','type':'function',
            'function':{'name':tool['name'],'arguments':'{}'}}]}}]}
    else:
        if external_requests == 3:
            shell_environment_verified = any(item.get('type') == 'function_call_output'
                and 'OWNED_SUBAGENT_ENV_OK' in str(item.get('output', '')) for item in payload['input'])
        elif external_requests == 7:
            output = next(item['output'] for item in payload['input'] if item.get('call_id') == 'owned_tree_probe'
                          and item.get('type') == 'function_call_output')
            agents = json.loads(output)['agents']
            assert [agent['agent_name'] for agent in agents] == ['/root'], 'Deleted worker remained in the native agent tree'
            tree_cleaned.set()
        reply = {'choices':[{'finish_reason':'stop','message':{'content':'Owned parent fixture finished.'}}]}
    return Reply(b''.join(frame for frame,_ in response_events(reply,names)))

mixed.open_upstream = upstream
mixed.SUPPORT = scratch
if args.unfixed: mixed.normalize_agent_handoffs = lambda history: history
server = ThreadingHTTPServer(('127.0.0.1',0),mixed.MixedGateway)
server.daemon_threads = True
server.capability = 'owned_fixture_capability_12345678901234567890'
server.native_models = {'gpt-6.1-sol'}
from provider_registry import public_catalog, PROVIDERS
server.model_catalog = public_catalog(json.loads((root/'config/models.json').read_text()), PROVIDERS)
server.external_url = 'http://owned-fixture.invalid/responses'
threading.Thread(target=server.serve_forever,daemon=True).start()
(home/'config.toml').write_text('\n'.join([
    'model = '+json.dumps(parent_model),
    'model_catalog_json = '+json.dumps(str(home/'models.json')),
    'openai_base_url = '+json.dumps(f'http://127.0.0.1:{server.server_port}/g/{server.capability}/backend-api/codex'),
    '[features]', 'multi_agent = true',
]),encoding='utf8')
environment = {k:os.environ[k] for k in ('SystemRoot','WINDIR','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC') if k in os.environ}
(scratch/'subagent_lifecycle.py').write_bytes((root/'src/desktop/subagent_lifecycle.py').read_bytes())
environment.update(CODEX_HOME=str(home),OPENAI_API_KEY='dummy-native-fixture',
                   BETTER_CODEX_SUBAGENTS=str(scratch/'subagent_lifecycle.py'))
process = subprocess.Popen([str(installed/'resources/codex.exe'),'app-server','--listen','stdio://'],
    cwd=scratch,env=environment,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
    text=True,encoding='utf8',creationflags=subprocess.CREATE_NO_WINDOW)
mailbox = queue.Queue()
notifications = []

def read():
    for line in process.stdout:
        try: mailbox.put(json.loads(line))
        except ValueError: pass
    mailbox.put({'closed':True})
threading.Thread(target=read,daemon=True).start()
identifier = 0
rpc_lock = threading.RLock()

def call(method, params):
    with rpc_lock: return rpc_call(method, params)


def rpc_call(method, params):
    global identifier
    identifier += 1
    process.stdin.write(json.dumps({'id':identifier,'method':method,'params':params})+'\n')
    process.stdin.flush()
    while True:
        value = mailbox.get(timeout=45)
        if value.get('closed'): raise RuntimeError('Synthetic runtime closed')
        if value.get('id') == identifier:
            if 'error' in value:
                (scratch/'rpc-error.json').write_text(json.dumps(value['error']))
            assert 'error' not in value, 'Synthetic RPC failed: '+method
            return value.get('result',{})
        if value.get('method'): notifications.append(value)

report = {'live':args.live, 'unfixed':args.unfixed}
lifecycle_fixture = None
try:
    call('initialize',{'clientInfo':{'name':'owned-delegation-fixture','title':'Synthetic delegation check','version':'1'},'capabilities':{'experimentalApi':True}})
    process.stdin.write('{"method":"initialized"}\n');process.stdin.flush()
    call('account/login/start',{'type':'apiKey','apiKey':'dummy-native-fixture'})
    parent = call('thread/start',{'model':parent_model,'cwd':str(scratch),
        'approvalPolicy':'never','sandbox':'read-only',
        'baseInstructions':'Synthetic delegation test authorized by the user. Only create the requested child, wait for it and report its marker. Do not use any other tools or access files.'})['thread']['id']
    if not args.live:
        (scratch/'support').mkdir()
        lifecycle_fixture = LifecycleServer(call, scratch/'support')
    prompt = ('Call collaboration.spawn_agent once with task_name native_child_probe, fork_turns none, '
              'model '+child_model+', reasoning_effort high and this exact message: '+message+
              '\nWait for its actual result and report GLM_NATIVE_CHILD_OK. Do not treat a spawn acknowledgement as completion. Do not use other tools or create additional agents.')
    call('turn/start',{'threadId':parent,'input':[{'type':'text','text':prompt}]})
    deadline = time.monotonic()+90
    child = None
    while time.monotonic() < deadline:
        loaded = call('thread/loaded/list',{})
        ids = loaded.get('data',[])
        children = [tid for tid in ids if tid != parent]
        if children and child_requests:
            assert len(children) == 1, 'More than one synthetic child was created'
            child = call('thread/read',{'threadId':children[0],'includeTurns':True})['thread']
            turns = child.get('turns',[])
            if turns and turns[-1].get('status') in {'completed','failed','interrupted'}: break
        time.sleep(0.2)
    assert child is not None and child_requests, 'GLM did not create the requested child'
    status = child['turns'][-1]['status']
    report.update(child_status=status,child_requests=child_requests,external_requests=external_requests)
    if args.unfixed:
        assert status == 'failed' and all(v['mislabeled_task'] for v in child_requests)
        assert 'stream closed before response.completed' in json.dumps(child['turns'][-1].get('error'))
        print('CONFIRMED: installed runtime labels the GLM plaintext handoff as ciphertext; native child fails with the reported stream error.')
    else:
        assert status == 'completed' and 'GLM_NATIVE_CHILD_OK' in json.dumps(child['turns'][-1])
        assert all(v['has_task'] and not v['mislabeled_task'] for v in child_requests)
        while time.monotonic() < deadline:
            parent_state = call('thread/read',{'threadId':parent,'includeTurns':True})['thread']
            parent_turn = parent_state['turns'][-1]
            if parent_turn['status'] in {'completed','failed','interrupted'}: break
            time.sleep(0.2)
        if args.live:
            final_text = '\n'.join(item.get('text','') for item in parent_turn.get('items',[]) if item.get('type') == 'agentMessage')
            report['parent_received_result'] = parent_turn['status'] == 'completed' and 'GLM_NATIVE_CHILD_OK' in final_text
            assert report['parent_received_result'], 'GLM did not finish with the actual child result'
        else:
            assert shell_environment_verified, 'Native shell did not retain the helper path and calling thread identity'
        target = child['id']
        if not args.live:
            # A desktop restart loses process-local provenance for the saved first task.
            mixed.PLAINTEXT_HANDOFFS.clear()
            call('turn/start', {'threadId': parent, 'input': [{'type': 'text', 'text': 'Owned synthetic fixture: assign another turn to the finished native_child_probe worker.'}]})
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                restarted = call('thread/read', {'threadId': target, 'includeTurns': True})['thread']
                turns = restarted.get('turns', [])
                if len(turns) == 2 and turns[-1]['status'] == 'completed': break
                time.sleep(0.2)
            assert len(turns) == 2 and turns[-1]['status'] == 'completed', 'Finished worker did not restart'
            assert 'GLM_NATIVE_CHILD_OK' in json.dumps(turns[-1]) and len(child_requests) == 2
            while time.monotonic() < deadline:
                parent_turn = call('thread/read', {'threadId': parent, 'includeTurns': True})['thread']['turns'][-1]
                if parent_turn['status'] == 'completed': break
                time.sleep(0.2)
            assert parent_turn['status'] == 'completed', 'Restart fixture parent did not finish'
            report['finished_worker_restarted'] = True
        cleanup = {'parent': parent, 'target': target}
        assert target in {row['id'] for row in manage({**cleanup, 'action': 'list', 'target': None}, call)['agents']}
        assert manage({**cleanup, 'action': 'close'}, call)['history_retained']
        assert target not in call('thread/loaded/list', {}).get('data', [])
        assert target in {row['id'] for row in manage({**cleanup, 'action': 'list', 'target': None}, call)['agents']}
        assert manage({**cleanup, 'action': 'delete'}, call)['status'] == 'deleted'
        assert target not in {row['id'] for row in manage({**cleanup, 'action': 'list', 'target': None}, call)['agents']}
        if not args.live:
            call('turn/start', {'threadId': parent, 'input': [{'type': 'text', 'text': 'Owned synthetic fixture: verify the deleted worker is absent from list_agents.'}]})
            assert tree_cleaned.wait(20), 'Native agent tree cleanup was not verified'
        print('PASS: installed runtime delegated GLM -> '+child_model+' high; child completed, closed with history retained, then deleted. '+('Real providers, synthetic task only.' if args.live else 'Finished worker restarted through followup_task; native tree cleanup and shell environment verified; localhost mocks only.'))
finally:
    if lifecycle_fixture: lifecycle_fixture.close()
    (scratch/'result.json').write_text(json.dumps(report,indent=2))
    (scratch/'notification-methods.json').write_text(json.dumps([v['method'] for v in notifications]))
    process.terminate();process.wait(timeout=15)
    server.shutdown();server.server_close()
