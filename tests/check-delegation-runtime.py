"""Installed runtime GLM -> native high-reasoning delegation, isolated profile.

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
args = parser.parse_args()
assert not (args.live and args.unfixed), 'The broken-path reproduction is offline only'
root = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(root/'src/desktop'), str(root/'src/gateway')]
import runtime_mixed as mixed
from core import GatewayCore, ToolNames, GatewayError
from chat_bridge import response_events

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
message = 'Synthetic delegation diagnostic only. Do not use tools, read files or take actions. Reply exactly GLM_NATIVE_CHILD_OK.'
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
native_requests = []
old_open = mixed.open_upstream

def upstream(url, headers, body=None, *, timeout=120):
    global external_requests
    payload = json.loads(body)
    if url == 'https://chatgpt.com/backend-api/codex/responses':
        assert payload['model'] == 'gpt-6.1-sol' and payload['reasoning']['effort'] == 'high'
        mislabeled = any(part.get('encrypted_content') == message
                         for item in payload['input'] for part in item.get('content',[]))
        has_task = any(part.get('type') == 'input_text' and message in part.get('text','')
                       for item in payload['input'] for part in item.get('content',[]))
        native_requests.append({'model':payload['model'], 'effort':payload['reasoning']['effort'],
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
        arguments = {'task_name':'native_child_probe','fork_turns':'none','model':'gpt-6.1-sol',
                     'reasoning_effort':'high','message':message}
        reply = {'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{
            'id':'owned_delegation_call','type':'function',
            'function':{'name':tool['name'],'arguments':json.dumps(arguments)}}]}}]}
    else:
        reply = {'choices':[{'finish_reason':'stop','message':{'content':'Owned parent fixture finished.'}}]}
    return Reply(b''.join(frame for frame,_ in response_events(reply,names)))

mixed.open_upstream = upstream
mixed.SUPPORT = scratch
if args.unfixed: mixed.normalize_agent_handoffs = lambda history: history
server = ThreadingHTTPServer(('127.0.0.1',0),mixed.MixedGateway)
server.daemon_threads = True
server.capability = 'owned_fixture_capability_12345678901234567890'
server.native_models = {'gpt-6.1-sol'}
server.external_url = 'http://owned-fixture.invalid/responses'
threading.Thread(target=server.serve_forever,daemon=True).start()
(home/'config.toml').write_text('\n'.join([
    'model = '+json.dumps(parent_model),
    'model_catalog_json = '+json.dumps(str(home/'models.json')),
    'openai_base_url = '+json.dumps(f'http://127.0.0.1:{server.server_port}/g/{server.capability}/backend-api/codex'),
    '[features]', 'multi_agent = true',
]),encoding='utf8')
environment = {k:os.environ[k] for k in ('SystemRoot','WINDIR','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC') if k in os.environ}
environment.update(CODEX_HOME=str(home),OPENAI_API_KEY='dummy-native-fixture')
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

def call(method, params):
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
try:
    call('initialize',{'clientInfo':{'name':'owned-delegation-fixture','title':'Synthetic delegation check','version':'1'},'capabilities':{'experimentalApi':True}})
    process.stdin.write('{"method":"initialized"}\n');process.stdin.flush()
    call('account/login/start',{'type':'apiKey','apiKey':'dummy-native-fixture'})
    parent = call('thread/start',{'model':parent_model,'cwd':str(scratch),
        'approvalPolicy':'never','sandbox':'read-only',
        'baseInstructions':'Synthetic delegation test authorized by the user. Only create the requested child, wait for it and report its marker. Do not use any other tools or access files.'})['thread']['id']
    prompt = ('Call collaboration.spawn_agent once with task_name native_child_probe, fork_turns none, '
              'model gpt-6.1-sol, reasoning_effort high and this exact message: '+message+
              '\nWait for its actual result and report GLM_NATIVE_CHILD_OK. Do not treat a spawn acknowledgement as completion. Do not use other tools or create additional agents.')
    call('turn/start',{'threadId':parent,'input':[{'type':'text','text':prompt}]})
    deadline = time.monotonic()+90
    child = None
    while time.monotonic() < deadline:
        loaded = call('thread/loaded/list',{})
        ids = loaded.get('data',[])
        children = [tid for tid in ids if tid != parent]
        if children and native_requests:
            assert len(children) == 1, 'More than one synthetic child was created'
            child = call('thread/read',{'threadId':children[0],'includeTurns':True})['thread']
            turns = child.get('turns',[])
            if turns and turns[-1].get('status') in {'completed','failed','interrupted'}: break
        time.sleep(0.2)
    assert child is not None and native_requests, 'GLM did not create the requested native child'
    status = child['turns'][-1]['status']
    report.update(child_status=status,native_requests=native_requests,external_requests=external_requests)
    if args.unfixed:
        assert status == 'failed' and all(v['mislabeled_task'] for v in native_requests)
        assert 'stream closed before response.completed' in json.dumps(child['turns'][-1].get('error'))
        print('CONFIRMED: installed runtime labels the GLM plaintext handoff as ciphertext; native child fails with the reported stream error.')
    else:
        assert status == 'completed' and 'GLM_NATIVE_CHILD_OK' in json.dumps(child['turns'][-1])
        assert all(v['has_task'] and not v['mislabeled_task'] for v in native_requests)
        if args.live:
            while time.monotonic() < deadline:
                parent_state = call('thread/read',{'threadId':parent,'includeTurns':True})['thread']
                parent_turn = parent_state['turns'][-1]
                if parent_turn['status'] in {'completed','failed','interrupted'}: break
                time.sleep(0.2)
            final_text = '\n'.join(item.get('text','') for item in parent_turn.get('items',[]) if item.get('type') == 'agentMessage')
            report['parent_received_result'] = parent_turn['status'] == 'completed' and 'GLM_NATIVE_CHILD_OK' in final_text
            assert report['parent_received_result'], 'GLM did not finish with the actual child result'
        print('PASS: installed runtime delegated GLM -> gpt-6.1-sol high; child completed with GLM_NATIVE_CHILD_OK. '+('Real providers, synthetic task only.' if args.live else 'Localhost mocks only.'))
finally:
    (scratch/'result.json').write_text(json.dumps(report,indent=2))
    (scratch/'notification-methods.json').write_text(json.dumps([v['method'] for v in notifications]))
    process.terminate();process.wait(timeout=15)
    server.shutdown();server.server_close()
