"""Real loopback streams span a settings swap; no real provider or account."""
from pathlib import Path
from http.server import ThreadingHTTPServer
from email.message import Message
from types import SimpleNamespace
import copy
import io
import json
import sys
import threading
import urllib.error
import urllib.request
import uuid

root=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(root/'src/desktop'),str(root/'src/gateway')]
import runtime_mixed as mixed
from live_settings import RequestSettings,SettingsGenerations

relay=mixed.external_adapter
scratch=root/'.local/test-work'/('request-settings-'+uuid.uuid4().hex[:8]);scratch.mkdir(parents=True)
mixed.SUPPORT=scratch/'outer';mixed.SUPPORT.mkdir();relay.SUPPORT=scratch/'inner';relay.SUPPORT.mkdir()
catalog=json.loads((root/'config/models.json').read_text(encoding='utf8'))
template=copy.deepcopy(catalog['models'][0])
stopped=[]
old_engine=SimpleNamespace(stop=lambda:stopped.append('old'))
new_engine=SimpleNamespace(stop=lambda:stopped.append('new'))

def settings(version,ids,engine):
    models={};routes={};entries=[]
    for mid in ids:
        metadata={**template,'slug':mid,'display_name':mid,'default_reasoning_level':'none',
            'supported_reasoning_levels':[{'effort':'none','description':'Provider default'}]}
        entries.append(metadata)
        models[mid]={'provider':'fixture','metadata':metadata,'output_limit':128 if version=='old' else 64,'reasoning_mode':'provider_default'}
        routes[mid]=('fixture','https://fixture.example/'+version+'/responses','none',{'none'})
    providers={'fixture':{'label':'Fixture '+version,'adapter':'responses','endpoint':'https://fixture.example/'+version+'/responses','default_model':ids[0],'models':{mid:{'output_limit':128} for mid in ids}}}
    return RequestSettings((providers,models,routes),{'default':'default.md','models':{}},{'default.md':'PROFILE_'+version},
        {'models':entries},scratch/version,engine)

old=settings('old',['fixture/keep','fixture/remove'],old_engine)
new=settings('new',['fixture/keep'],new_engine)
generations=SettingsGenerations(old,lambda engine:engine.stop());old_token=generations.current
inner=ThreadingHTTPServer(('127.0.0.1',0),relay.RealGateway);inner.daemon_threads=True
inner.prefix='/owned_relay';inner.token=mixed.DUMMY;inner.settings_generations=generations
outer=ThreadingHTTPServer(('127.0.0.1',0),mixed.MixedGateway);outer.daemon_threads=True
outer.capability='owned_fixture_capability_12345678901234567890';outer.native_models={'gpt-native-fixture'}
outer.settings_generations=generations;outer.model_catalog=old.catalog
outer.external_url=f'http://127.0.0.1:{inner.server_port}{inner.prefix}/backend-api/codex/responses'
before_relay=threading.Event();allow_relay=threading.Event();stream_started=threading.Event();finish_stream=threading.Event()
errors=[];sent=[];keys=[];old_response=[];native_response=[]
native_started=threading.Event();finish_native=threading.Event()
original_open=mixed.open_upstream

def fake_key(provider,storage=None):
    assert provider=='fixture' and storage in {old.key_storage,new.key_storage}
    version=storage.name;keys.append(version);return 'owned-dummy-'+version+'-key'
relay.key_supplier=fake_key

class Stream:
    status=200
    def __init__(self,mid,wait=False,native=False):
        self.headers=Message();self.headers['Content-Type']='text/event-stream'
        self.mid=mid;self.wait=wait;self.native=native;self.lines=iter([
            ('data: '+json.dumps({'type':'response.created','response':{'model':mid}})+'\n').encode(),b'\n',
            ('data: '+json.dumps({'type':'response.completed','response':{'model':mid,'output':[]}})+'\n').encode(),b'\n'])
        self.count=0
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def readline(self,limit):
        if self.count==2 and self.wait:
            (native_started if self.native else stream_started).set()
            assert (finish_native if self.native else finish_stream).wait(10),'Fixture stream timed out'
        self.count+=1;return next(self.lines,b'')
    def read1(self,limit):return self.readline(limit)

def fake_provider(prepared):
    assert prepared.url in {'https://fixture.example/old/responses','https://fixture.example/new/responses'}
    value=json.loads(prepared.body);version=prepared.url.split('/')[-2]
    assert dict(prepared.headers)['Authorization']=='Bearer owned-dummy-'+version+'-key'
    assert 'PROFILE_'+version in value['instructions'] and 'Fixture '+version in value['instructions']
    assert value['max_output_tokens']==(128 if version=='old' else 64)
    assert not any(n.lower() in {'chatgpt-account-id','x-better-codex-generation'} for n,v in prepared.headers)
    assert b'owned-native-secret' not in prepared.body
    sent.append((version,value['model']))
    return Stream(value['model'],wait=version=='old')
relay.open_provider=fake_provider

def open_outer(url,headers,body=None):
    if url.startswith('https://chatgpt.com/'):
        assert dict((k.lower(),v) for k,v in headers)['authorization']=='Bearer owned-native-secret'
        return Stream('gpt-native-fixture',wait=True,native=True)
    assert url==outer.external_url
    if not before_relay.is_set():
        before_relay.set();assert allow_relay.wait(10),'Fixture relay timed out'
    assert set(headers)=={'Authorization','Content-Type','Accept','X-Better-Codex-Generation'}
    assert headers['Authorization']=='Bearer '+mixed.DUMMY
    return original_open(url,headers,body)
mixed.open_upstream=open_outer
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
url=f'http://127.0.0.1:{outer.server_port}/g/{outer.capability}/backend-api/codex/responses'

def request(mid):
    payload={'model':mid,'instructions':'Owned synthetic task','input':[{'role':'user','content':'fixture'}],'tools':[]}
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer owned-native-secret','Content-Type':'application/json','ChatGPT-Account-Id':'owned-account-canary'})
    with opener.open(req,timeout=15) as response:return response.read()

def run(mid,result):
    try:result.append(request(mid))
    except Exception as error:errors.append(type(error).__name__)

for server in (inner,outer):threading.Thread(target=server.serve_forever,daemon=True).start()
native=threading.Thread(target=run,args=('gpt-native-fixture',native_response))
worker=threading.Thread(target=run,args=('fixture/remove',old_response))
try:
    native.start();assert native_started.wait(5)
    worker.start();assert before_relay.wait(5)
    # Neither the native response nor the outer-to-inner handoff may block this.
    published=threading.Event()
    publisher=threading.Thread(target=lambda:(generations.publish(new),published.set()))
    publisher.start();assert published.wait(2),'Settings waited for an active response';publisher.join(2)
    assert not stopped and not finish_stream.is_set() and not finish_native.is_set()
    allow_relay.set();assert stream_started.wait(5)
    assert b'response.completed' in request('fixture/keep')
    try:request('fixture/remove');raise AssertionError('Deleted route still accepted new requests')
    except urllib.error.HTTPError as error:assert error.code==422
    assert sent==[('old','fixture/remove'),('new','fixture/keep')] and keys==['old','new']
    finish_stream.set();worker.join(5);assert old_response and not errors and not stopped
    # The old engine also remains pinned by the old native response. Its last
    # lease ends naturally; no response or terminal is cancelled to apply settings.
    finish_native.set();native.join(5);assert native_response and not errors
    for thread in (worker,native):assert not thread.is_alive()
    assert stopped==['old'] and old_token not in generations.entries
    req=urllib.request.Request(outer.external_url,data=b'{}',headers={'Authorization':'Bearer '+mixed.DUMMY,'Content-Type':'application/json','X-Better-Codex-Generation':old_token})
    try:opener.open(req,timeout=5);raise AssertionError('Expired generation accepted')
    except urllib.error.HTTPError as error:assert error.code==403
    assert keys==['old','new']
    # A failed publication leaves the previous current generation intact.
    token=generations.current
    try:generations.publish(old,lambda:(_ for _ in ()).throw(ValueError('Owned failure')));raise AssertionError('Failure ignored')
    except ValueError:pass
    assert generations.current==token
finally:
    allow_relay.set();finish_stream.set();finish_native.set()
    for thread in (worker,native):
        if thread.ident:thread.join(5)
    for server in (outer,inner):server.shutdown();server.server_close()
    generations.close()
assert stopped==['old','new']
print('PASS: native and external streams stay active across publication; old relay handoff, credentials and instructions stay pinned; new requests use new settings, deleted routes/expired generations are rejected, engines retire after their last lease. Loopback fixtures only.')
