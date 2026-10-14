"""Installed backend + both routing paths, using mocked inference and one echo."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import hashlib
import io
import json
import os
import queue
import re
import subprocess
import sys
import threading
import uuid

root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'src/gateway'));sys.path.insert(0,str(root/'src/desktop'))
import runtime_mixed as mixed
import portable_compaction as portable
from core import ToolNames
from chat_bridge import response_events
from api_settings import prepare_configuration
from provider_registry import PROVIDERS

selected=root/(root/'.local/deployment-path.txt').read_text().strip()
manifest=json.loads((selected/'Deployment.json').read_text())
installed=Path(manifest['source_app'])
for name,expected in manifest['installed_file_hashes'].items():
    with (installed/name).open('rb') as handle:assert hashlib.file_digest(handle,'sha256').hexdigest()==expected
scratch=root/'.local/test-work'/('compact-runtime-'+uuid.uuid4().hex[:8])
home=scratch/'home';home.mkdir(parents=True)
catalog=json.loads((root/'config/models.json').read_text())
metadata={m['slug']:m for m in catalog['models']}
rows=[{'id':mid,'provider':pid,'label':metadata[mid]['display_name'],'context':metadata[mid]['context_window'],
    'output':route.get('output_limit',4096),'efforts':[e['effort'] for e in metadata[mid]['supported_reasoning_levels']],
    'default_effort':metadata[mid]['default_reasoning_level']} for pid,p in PROVIDERS.items() for mid,route in p['models'].items()]
added={**next(r for r in rows if r['provider']=='merge'),'id':'fixture/new-model','label':'Owned new-model fixture'}
_,catalog=prepare_configuration({'providers':{pid:{'endpoint':p['endpoint'],'default_model':p['default_model']} for pid,p in PROVIDERS.items()},
    'models':rows+[added]},PROVIDERS,catalog)
(home/'models.json').write_text(json.dumps(catalog))
opaque='owned-native-checkpoint-runtime-fixture'
summary='Owned fixture summary: earlier task requested a harmless terminal echo; previous lengthy assistant data was synthetic.'
observed=[];failures=[];external_count=0;native_count=0;echo_received=False;gateway_events=[];runtime_errors=[]

class Headers:
    def get_content_type(self):return 'text/event-stream'
    def items(self):return [('Content-Type','text/event-stream')]
    def get(self,*args):return None
class Reply(io.BytesIO):
    status=200;headers=Headers()
    def read1(self,size=-1):return self.read(size)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

def events(output):
    values=[{'type':'response.created','response':{'id':'resp_fixture','status':'in_progress','output':[]}}]
    for index,item in enumerate(output):values.extend([
        {'type':'response.output_item.added','output_index':index,'item':item},
        {'type':'response.output_item.done','output_index':index,'item':item}])
    values.append({'type':'response.completed','response':{'id':'resp_fixture','status':'completed','output':output}})
    return b''.join(('data: '+json.dumps(v)+'\n\n').encode() for v in values)

def upstream(url,headers,body=None):
    global external_count,native_count,echo_received
    try:
        payload=json.loads(body)
        native=url=='https://chatgpt.com/backend-api/codex/responses'
        observed.append({'model':payload['model'],'native':native,'bytes':len(body),
            'opaque_received':opaque in json.dumps(payload),'portable_summary_received':summary in json.dumps(payload)})
        if native:
            native_count+=1
            assert dict(headers).get('authorization')=='Bearer dummy-native-fixture'
            assert payload['model']=='gpt-6.1-sol'
            if any(v.get('type')=='compaction_trigger' for v in payload['input']):
                return Reply(events([{'type':'compaction','id':'cmp_runtime_fixture','encrypted_content':opaque}]))
            assert payload['input'][0]['type']=='compaction' and payload['tools']==[] and payload['tool_choice']=='none'
            output=[{'type':'message','id':'msg_summary_runtime_fixture','role':'assistant','content':[{'type':'output_text','text':summary,'annotations':[]}]}]
            return Reply(events(output))
        assert url=='http://owned-fixture.invalid/responses' and dict(headers)['Authorization']==mixed.DUMMY.join(['Bearer ',''])
        assert payload['model']=='zai/glm-5.3-flash' and opaque not in json.dumps(payload)
        names=ToolNames(payload.get('tools',[]))
        if external_count==0:
            content='Owned lengthy fixture data. '*4000
            reply={'choices':[{'finish_reason':'stop','message':{'content':content}}]}
        elif external_count==1:
            assert summary in json.dumps(payload)
            tool=next(t for t in names.tools if t['name'].endswith('exec_command'))
            properties=tool['parameters']['properties']
            assert 'cmd' in properties
            arguments={'cmd':"Write-Output 'COMPACTION_NATIVE_TOOL_ECHO_OK'"}
            reply={'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':'owned_echo_call','type':'function','function':{'name':tool['name'],'arguments':json.dumps(arguments)}}]}}]}
        else:
            echo_received=any('COMPACTION_NATIVE_TOOL_ECHO_OK' in str(v.get('output','')) for v in payload['input'] if v.get('type')=='function_call_output')
            assert echo_received
            reply={'choices':[{'finish_reason':'stop','message':{'content':'Owned fixture complete; native terminal echo received.'}}]}
        external_count+=1
        return Reply(b''.join(frame for frame,event in response_events(reply,names)))
    except Exception as error:
        failures.append(type(error).__name__)
        raise

old_open,old_record,old_cache=mixed.open_upstream,mixed.record,portable.CACHE
mixed.open_upstream=upstream;mixed.record=lambda event:gateway_events.append({k:v for k,v in event.items() if k in {'gateway_error','kind','model'}});portable.CACHE=scratch/'context-cache'
server=ThreadingHTTPServer(('127.0.0.1',0),mixed.MixedGateway);server.daemon_threads=True
server.capability='owned_fixture_capability_12345678901234567890'
server.native_models={'gpt-6.1-sol'};server.external_url='http://owned-fixture.invalid/responses'
threading.Thread(target=server.serve_forever,daemon=True).start()
(home/'config.toml').write_text('\n'.join(['model="zai/glm-5.3-flash"',
    'model_catalog_json='+json.dumps(str(home/'models.json')),
    'openai_base_url='+json.dumps('http://127.0.0.1:'+str(server.server_port)+'/g/'+server.capability+'/backend-api/codex')]))
environment={k:os.environ[k] for k in ('SystemRoot','WINDIR','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC') if k in os.environ}
environment.update(CODEX_HOME=str(home),OPENAI_API_KEY='dummy-native-fixture')
process=subprocess.Popen([str(installed/'resources/codex.exe'),'app-server','--listen','stdio://'],cwd=scratch,env=environment,
    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',creationflags=subprocess.CREATE_NO_WINDOW)
mailbox=queue.Queue()
def read():
    for line in process.stdout:
        try:
            value=json.loads(line)
            if value.get('method')=='error':runtime_errors.append(re.sub(r'https?://\S+','<owned fixture URL>',str(value.get('params',{}).get('error',{}).get('message','')))[:350])
            mailbox.put(value)
        except ValueError:pass
threading.Thread(target=read,daemon=True).start()
identifier=0
def call(method,params):
    global identifier
    identifier+=1;process.stdin.write(json.dumps({'id':identifier,'method':method,'params':params})+'\n');process.stdin.flush()
    while True:
        value=mailbox.get(timeout=30)
        if value.get('id')==identifier:
            if 'error' in value:raise AssertionError('Owned fixture RPC failed: '+method)
            return value.get('result',{})
def completed():
    while True:
        value=mailbox.get(timeout=30)
        if value.get('method')=='turn/completed':return value.get('params',{}).get('turn',{}).get('status')
try:
    call('initialize',{'clientInfo':{'name':'owned-compaction-fixture','title':'Offline checkpoint check','version':'1'},'capabilities':{'experimentalApi':True}})
    process.stdin.write('{"method":"initialized"}\n');process.stdin.flush()
    call('account/login/start',{'type':'apiKey','apiKey':'dummy-native-fixture'})
    call('thread/start',{'model':added['id'],'ephemeral':True,'cwd':str(scratch),
        'approvalPolicy':'never','sandbox':'read-only','baseInstructions':'Owned new-model catalogue validation; no inference.'})
    thread=call('thread/start',{'model':'zai/glm-5.3-flash','ephemeral':True,'cwd':str(scratch),
        'approvalPolicy':'never','sandbox':'read-only','baseInstructions':'Owned offline compaction fixture. Only a harmless terminal echo is permitted.'})['thread']['id']
    call('turn/start',{'threadId':thread,'input':[{'type':'text','text':'Owned synthetic conversation fixture.'}]})
    assert completed()=='completed',{'stage':'initial','gateway_events':gateway_events,'runtime_errors':runtime_errors,'failures':failures}
    call('thread/compact/start',{'threadId':thread})
    assert completed()=='completed','Installed backend did not commit the genuine checkpoint fixture'
    call('turn/start',{'threadId':thread,'input':[{'type':'text','text':'Run the owned harmless terminal echo fixture.'}]})
    assert completed()=='completed','Post-compaction tool fixture failed'
    assert not failures and external_count==3 and native_count==2 and echo_received
    external=[v for v in observed if not v['native']]
    assert external[-1]['portable_summary_received'] and not external[-1]['opaque_received']
    assert external[-1]['bytes'] < observed[1]['bytes']
    print('PASS: installed backend accepted a settings-added model, compacted the same GLM thread, retained its model and ran a native terminal echo. Native auth/checkpoint stayed on the mocked trusted origin. No real provider/account/app used.')
finally:
    process.terminate();process.wait(timeout=15);server.shutdown();server.server_close()
    mixed.open_upstream,mixed.record,portable.CACHE=old_open,old_record,old_cache
