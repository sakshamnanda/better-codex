"""Disabled providers retain configuration, never route new requests or credentials."""
from pathlib import Path
import copy
import json
import sys
import uuid

root=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(root/'src/gateway'),str(root/'src/desktop')]
from provider_registry import load_registry,public_catalog
from api_settings import prepare_configuration
from provider_service import needs_opencode
from core import GatewayCore,GatewayError

folder=root/'.local/test-work'/('provider-toggle-'+uuid.uuid4().hex[:8]);(folder/'gateway/keys').mkdir(parents=True)
def model(mid):return {'slug':mid,'display_name':mid,'context_window':4096,'default_reasoning_level':'none','supported_reasoning_levels':[{'effort':'none','description':'Provider default'}]}
catalog={'models':[model('gpt-native-fixture'),model('fixture/model'),model('fixture/zen')]}
providers={
 'fixture':{'label':'Fixture','adapter':'responses','endpoint':'https://fixture.example/v1/responses','default_model':'fixture/model','models':{'fixture/model':{'output_limit':256}}},
 'opencode':{'label':'Zen fixture','adapter':'opencode','endpoint':'https://opencode.ai/zen/v1/chat/completions','default_model':'fixture/zen','models':{'fixture/zen':{'output_limit':256}}}}
(folder/'models.json').write_text(json.dumps(catalog));original_catalog=(folder/'models.json').read_bytes()
(folder/'gateway/keys/fixture.dpapi').write_bytes(b'owned-ciphertext-fixture')
(folder/'gateway/keys/opencode.dpapi').write_bytes(b'owned-ciphertext-zen')
def store(value): (folder/'providers.json').write_text(json.dumps(value))
store(providers);before=load_registry(folder);assert needs_opencode(folder,providers)
reads=[]
def key(pid):reads.append(pid);return 'owned-external-dummy-key'
old=GatewayCore('owned_provider_toggle_12345678901234567890',12345,{'gpt-native-fixture'},key,registry=before)
providers['fixture']['enabled']=False;providers['opencode']['enabled']=False;store(providers)
after=load_registry(folder);assert after[1]=={} and after[2]=={} and not needs_opencode(folder,providers)
assert {m['slug'] for m in public_catalog(catalog,after[0])['models']}=={'gpt-native-fixture'}
headers=[('Host',old.host),('Authorization','Bearer owned-native-canary'),('Content-Type','application/json')]
payload={'model':'fixture/model','input':[{'role':'user','content':'Owned fixture'}],'tools':[]}
body=json.dumps(payload).encode();path=old.prefix+'/backend-api/codex/responses'
assert old.prepare('POST',path,headers,body).provider=='fixture' and reads==['fixture']
new=GatewayCore('owned_provider_toggle_12345678901234567890',12345,{'gpt-native-fixture'},key,registry=after)
try:new.prepare('POST',path,headers,body);raise AssertionError('Disabled provider routed')
except GatewayError as e:assert e.status==422 and 'provider is disabled' in str(e)
assert reads==['fixture']
stale=GatewayCore('owned_provider_toggle_12345678901234567890',12345,{'gpt-native-fixture'},key,registry=(after[0],before[1],before[2]))
try:stale.prepare('POST',path,headers,body);raise AssertionError('Stale route bypassed provider disable')
except GatewayError as e:assert e.status==422 and 'provider is disabled' in str(e)
assert reads==['fixture']
native=new.prepare('POST',path,headers,json.dumps({**payload,'model':'gpt-native-fixture'}).encode())
assert native.url.startswith('https://chatgpt.com/') and reads==['fixture']
rows=[{'id':mid,'provider':pid,'label':mid,'context':4096,'output':256,'efforts':['none'],'default_effort':'none'} for pid,p in providers.items() for mid in p['models']]
request={'providers':{pid:{'endpoint':p['endpoint'],'default_model':p['default_model'],'enabled':False} for pid,p in providers.items()},'models':rows}
p,c=prepare_configuration(request,before[0],catalog)
assert all(v['enabled'] is False and v['models'] for v in p.values())
for value in ('false',0,None):
 bad=copy.deepcopy(providers);bad['fixture']['enabled']=value;store(bad)
 try:load_registry(folder);raise AssertionError('Invalid enabled flag accepted')
 except ValueError:pass
bad=copy.deepcopy(providers);bad['fixture']['endpoint']='http://fixture.example/responses';store(bad)
try:load_registry(folder);raise AssertionError('Disabled provider bypassed endpoint validation')
except ValueError:pass
for p in providers.values():p['enabled']=True
store(providers);enabled=load_registry(folder)
assert set(enabled[2])=={'fixture/model','fixture/zen'} and needs_opencode(folder,providers)
assert len(public_catalog(catalog,enabled[0])['models'])==3
assert (folder/'models.json').read_bytes()==original_catalog
assert (folder/'gateway/keys/fixture.dpapi').read_bytes()==b'owned-ciphertext-fixture'
catalog['models'].append(model('fixture/second'))
providers['fixture']['models']['fixture/second']={'output_limit':256}
(folder/'models.json').write_text(json.dumps(catalog))
for pid,mid in [('fixture','fixture/model'),('opencode','fixture/zen')]:providers[pid]['models'][mid]['enabled']=False
store(providers);disabled_models=load_registry(folder)
assert set(disabled_models[2])=={'fixture/second'} and not needs_opencode(folder,providers)
assert disabled_models[0]['fixture']['default_model']=='fixture/second'
assert {m['slug'] for m in public_catalog(catalog,disabled_models[0])['models']}=={'gpt-native-fixture','fixture/second'}
for registry in (disabled_models,(disabled_models[0],before[1],before[2])):
    gate=GatewayCore('owned_provider_toggle_12345678901234567890',12345,{'gpt-native-fixture'},key,registry=registry)
    try:gate.prepare('POST',path,headers,body);raise AssertionError('Disabled model routed')
    except GatewayError as e:assert e.status==422 and 'model is disabled' in str(e)
assert reads==['fixture']
rows=[{'id':mid,'provider':pid,'label':mid,'context':4096,'output':256,'efforts':['none'],'default_effort':'none','enabled':route.get('enabled',True)} for pid,p in providers.items() for mid,route in p['models'].items()]
request={'providers':{pid:{'endpoint':p['endpoint'],'default_model':p['default_model']} for pid,p in providers.items()},'models':rows}
prepared,_=prepare_configuration(request,providers,catalog)
assert prepared['fixture']['default_model']=='fixture/second' and prepared['fixture']['models']['fixture/model']['enabled'] is False
for value in ('false',0,None):
    bad=copy.deepcopy(providers);bad['fixture']['models']['fixture/model']['enabled']=value;store(bad)
    try:load_registry(folder);raise AssertionError('Invalid model enabled flag accepted')
    except ValueError:pass
    bad_request=copy.deepcopy(request);bad_request['models'][0]['enabled']=value
    try:prepare_configuration(bad_request,providers,catalog);raise AssertionError('Invalid model enabled change accepted')
    except ValueError:pass
for p in providers.values():
    for route in p['models'].values():route['enabled']=True
store(providers);restored=load_registry(folder)
assert set(restored[2])=={'fixture/model','fixture/second','fixture/zen'} and needs_opencode(folder,providers)
print('PASS: enabled defaults retained, strict flags/URLs validated while disabled, old request settings preserved, new disabled requests reject before key reads, native routing unaffected, models/keys restored on re-enable. No inference used.')
