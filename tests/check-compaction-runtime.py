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
from core import ToolNames, GatewayError
from chat_bridge import response_events
from api_settings import prepare_configuration
from provider_registry import PROVIDERS, public_catalog

selected=root/os.environ.get('BETTER_CODEX_TEST_DEPLOYMENT',(root/'.local/deployment-path.txt').read_text().strip())
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
added={**next(r for r in rows if r['provider']=='openrouter'),'id':'@preset/runtime-fixture','label':'Owned preset fixture',
    'metadata_mode':'provider','reasoning_mode':'provider_default','efforts':['none'],'default_effort':'none'}
_,catalog=prepare_configuration({'providers':{pid:{'endpoint':p['endpoint'],'default_model':p['default_model']} for pid,p in PROVIDERS.items()},
    'models':rows+[added]},PROVIDERS,catalog)
(home/'models.json').write_text(json.dumps(public_catalog(catalog,PROVIDERS)))
opaque='owned-native-checkpoint-runtime-fixture'
summary='Owned fixture summary: earlier task requested a harmless terminal echo; previous lengthy assistant data was synthetic.'
observed=[];failures=[];external_count=0;native_count=0;echo_received=False;gateway_events=[];runtime_errors=[]
native_scenario=False;native_requests=[];native_long_reply=False;native_wire=[];external_auto=False

class Headers:
    def get_content_type(self):return 'text/event-stream'
    def items(self):return [('Content-Type','text/event-stream')]
    def get(self,*args):return None
class Reply(io.BytesIO):
    status=200;headers=Headers()
    def read1(self,size=-1):return self.read(size)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

def events(output,usage=None):
    values=[{'type':'response.created','response':{'id':'resp_fixture','status':'in_progress','output':[]}}]
    for index,item in enumerate(output):values.extend([
        {'type':'response.output_item.added','output_index':index,'item':item},
        {'type':'response.output_item.done','output_index':index,'item':item}])
    values.append({'type':'response.completed','response':{'id':'resp_fixture','status':'completed','output':output,**({'usage':usage} if usage else {})}})
    return b''.join(('data: '+json.dumps(v)+'\n\n').encode() for v in values)

def upstream(url,headers,body=None, *, timeout=120):
    global external_count,native_count,echo_received,native_long_reply
    try:
        payload=json.loads(body)
        native=url=='https://chatgpt.com/backend-api/codex/responses'
        observed.append({'model':payload['model'],'native':native,'bytes':len(body),
            'opaque_received':opaque in json.dumps(payload),'portable_summary_received':summary in json.dumps(payload)})
        if native:
            native_count+=1
            assert dict(headers).get('authorization')=='Bearer dummy-native-fixture'
            assert payload['model']=='gpt-6.1-sol'
            if native_scenario:
                native_requests.append(payload)
                if any(v.get('type')=='compaction_trigger' for v in payload['input']):
                    wire=events([{'type':'compaction','id':'cmp_native_fixture','encrypted_content':'owned-native-only-checkpoint'}])
                    native_wire.append(wire)
                    return Reply(wire)
                assert payload.get('tool_choice')!='none','Native compaction attempted a portable summary'
                usage={'input_tokens':100,'input_tokens_details':{'cached_tokens':0},'output_tokens':30000 if native_long_reply else 10,
                    'output_tokens_details':{'reasoning_tokens':0},'total_tokens':30100 if native_long_reply else 110}
                content='Owned lengthy native fixture. '*4000 if native_long_reply else 'Owned native continuation complete.'
                native_long_reply=False
                return Reply(events([{'type':'message','id':'msg_native_fixture','role':'assistant','content':[{'type':'output_text','text':content,'annotations':[]}]}],usage))
            if any(v.get('type')=='compaction_trigger' for v in payload['input']):
                assert payload['reasoning']['effort']=='low', 'External reasoning effort leaked into the native checkpoint request'
                return Reply(events([{'type':'compaction','id':'cmp_runtime_fixture','encrypted_content':opaque}]))
            assert payload['input'][0]['type']=='compaction' and payload['tools']==[] and payload['tool_choice']=='none'
            output=[{'type':'message','id':'msg_summary_runtime_fixture','role':'assistant','content':[{'type':'output_text','text':summary,'annotations':[]}]}]
            return Reply(events(output))
        assert url=='http://owned-fixture.invalid/responses' and dict(headers)['Authorization']==mixed.DUMMY.join(['Bearer ',''])
        assert payload['model']=='zai/glm-5.3-flash' and opaque not in json.dumps(payload)
        names=ToolNames(payload.get('tools',[]))
        if external_count==0:
            content='Owned lengthy fixture data. '*4000
            reply={'choices':[{'finish_reason':'stop','message':{'content':content}}],
                'usage':{'prompt_tokens':130000 if external_auto else 70000,'completion_tokens':10,'total_tokens':130010 if external_auto else 70010}}
        elif external_count==1:
            assert summary in json.dumps(payload)
            tool=next(t for t in names.tools if t['name'].endswith('exec_command'))
            properties=tool['parameters']['properties']
            assert 'cmd' in properties
            arguments={'cmd':"Write-Output 'COMPACTION_NATIVE_TOOL_ECHO_OK'"}
            if external_auto:
                assert tool['parameters']['properties']['max_output_tokens'].get('default')==2000,tool['parameters']['properties']['max_output_tokens']
                arguments['cmd'] = "Write-Output 'COMPACTION_NATIVE_TOOL_ECHO_OK " + 'fixture ' * 3000 + "'"
                if 'shell' in properties:arguments['shell']=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
            reply={'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':'owned_echo_call','type':'function','function':{'name':tool['name'],'arguments':json.dumps(arguments)}}]}}]}
        else:
            echo_received=any('COMPACTION_NATIVE_TOOL_ECHO_OK' in str(v.get('output','')) for v in payload['input'] if v.get('type')=='function_call_output')
            assert echo_received
            if external_auto:
                result=next(v['output'] for v in payload['input'] if v.get('type')=='function_call_output' and v.get('call_id')=='owned_echo_call')
                assert len(str(result))<20000 and 'truncat' in str(result).lower(),{'output_bytes':len(str(result)), 'fixture_tail':str(result)[-200:]}
            reply={'choices':[{'finish_reason':'stop','message':{'content':'Owned fixture complete; native terminal echo received.'}}]}
        if external_auto and external_count:
            # Match the observed 41k baseline, then grow across later turns.
            reply['usage']={'prompt_tokens':41000+4000*(external_count-1),'completion_tokens':10,'total_tokens':41010+4000*(external_count-1)}
        external_count+=1
        return Reply(b''.join(frame for frame,event in response_events(reply,names)))
    except Exception as error:
        failures.append({'type':type(error).__name__, 'detail':str(error)[:250] if isinstance(error,AssertionError) else ''})
        raise GatewayError('Owned runtime fixture failed',422) from error

old_open,old_record,old_cache,old_save=mixed.open_upstream,mixed.record,portable.CACHE,portable.save_summary
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
    assert native_count==0,'External model compacted at the old 64k threshold'
    call('thread/compact/start',{'threadId':thread})
    assert completed()=='completed','Installed backend did not commit the genuine checkpoint fixture'
    call('turn/start',{'threadId':thread,'input':[{'type':'text','text':'Run the owned harmless terminal echo fixture.'}]})
    assert completed()=='completed','Post-compaction tool fixture failed'
    assert not failures and external_count==3 and native_count==2 and echo_received
    external=[v for v in observed if not v['native']]
    assert external[-1]['portable_summary_received'] and not external[-1]['opaque_received']
    assert external[-1]['bytes'] < observed[1]['bytes']
    # The advertised per-model threshold must trigger a genuine checkpoint
    # without a manual compact command or a global/native config override.
    external_auto=True;external_count=0
    auto_external=call('thread/start',{'model':'zai/glm-5.3-flash','ephemeral':True,'cwd':str(scratch),
        'approvalPolicy':'never','sandbox':'read-only','baseInstructions':'Owned external automatic compaction fixture.'})['thread']['id']
    count=native_count
    call('turn/start',{'threadId':auto_external,'input':[{'type':'text','text':'Produce the owned long external fixture.'}]})
    assert completed()=='completed'
    call('turn/start',{'threadId':auto_external,'input':[{'type':'text','text':'Run the owned harmless terminal echo fixture.'}]})
    assert completed()=='completed',{'stage':'external auto','gateway_events':gateway_events,'runtime_errors':runtime_errors,'failures':failures}
    assert native_count==count+2,'128k compaction did not trigger once or repeated after the checkpoint'
    assert external_count==3 and echo_received and not failures
    assert observed[-1]['portable_summary_received'] and observed[-1]['bytes']<observed[-4]['bytes']
    for _ in range(3):
        call('turn/start',{'threadId':auto_external,'input':[{'type':'text','text':'Continue the owned context fixture.'}]})
        assert completed()=='completed'
    assert native_count==count+2 and external_count==6,'Post-compaction baseline and bounded tool output caused repeated compaction'
    # Native compaction must relay the actual checkpoint without another model
    # request or a dependency on portable-summary generation/DPAPI storage.
    native_scenario=True
    def forbidden_summary(*args):raise AssertionError('Native compaction accessed the portable cache')
    portable.save_summary=forbidden_summary
    native_thread=call('thread/start',{'model':'gpt-6.1-sol','ephemeral':True,'cwd':str(scratch),
        'approvalPolicy':'never','sandbox':'read-only','baseInstructions':'Owned native compaction fixture.'})['thread']['id']
    call('turn/start',{'threadId':native_thread,'input':[{'type':'text','text':'Owned native conversation fixture.'}]})
    assert completed()=='completed'
    count=len(native_requests)
    call('thread/compact/start',{'threadId':native_thread})
    assert completed()=='completed',{'stage':'native manual','gateway_events':gateway_events,'runtime_errors':runtime_errors}
    assert len(native_requests)==count+1 and len(native_wire)==1
    call('turn/start',{'threadId':native_thread,'input':[{'type':'text','text':'Continue the native fixture.'}]})
    assert completed()=='completed'
    assert any(v.get('encrypted_content')=='owned-native-only-checkpoint' for v in native_requests[-1]['input'])
    auto_thread=call('thread/start',{'model':'gpt-6.1-sol','ephemeral':True,'cwd':str(scratch),
        'approvalPolicy':'never','sandbox':'read-only','baseInstructions':'Owned native auto-compaction fixture.',
        'config':{'model_auto_compact_token_limit':4096}})['thread']['id']
    native_long_reply=True
    count=len(native_wire)
    call('turn/start',{'threadId':auto_thread,'input':[{'type':'text','text':'Produce the owned long fixture.'}]})
    assert completed()=='completed'
    call('turn/start',{'threadId':auto_thread,'input':[{'type':'text','text':'Continue after the owned long fixture.'}]})
    assert completed()=='completed',{'stage':'native auto','gateway_events':gateway_events,'runtime_errors':runtime_errors}
    assert len(native_wire)>count,'Installed backend did not trigger native auto-compaction'
    assert not failures
    portable.save_summary=old_save
    print('PASS: 128k automatic and manual checkpoints retain GLM context; verbose native output uses the 2000-token default; three later turns do not recompact. Native checkpoint paths remain independent. Mocked inference only; no real account/app used.')
finally:
    process.terminate();process.wait(timeout=15);server.shutdown();server.server_close()
    mixed.open_upstream,mixed.record,portable.CACHE=old_open,old_record,old_cache
    portable.save_summary=old_save
