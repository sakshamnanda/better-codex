"""Provider-only metadata discovery, presets, missing limits and routing defaults."""
from pathlib import Path
import copy
import io
import json
import sys
import threading
import uuid
from urllib.parse import parse_qs,urlsplit

root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'src/gateway'));sys.path.insert(0,str(root/'src/desktop'))
import model_metadata as meta
import core
from api_settings import Settings,prepare_configuration
from provider_registry import load_registry
from chat_bridge import prepare_chat
from provider_relay import limit_output

key='dummy-provider-metadata-only'
calls=[]
entries={
 'vendor/one':{'id':'vendor/one','context_length':200000,'top_provider':{'max_completion_tokens':32768},'supported_parameters':['tools','reasoning'],
   'reasoning':{'effort_values':['low','high']}},
 'vendor/two':{'id':'vendor/two','context_length':100000,'top_provider':{'max_completion_tokens':8192},'supported_parameters':['tools']},
 '~vendor/latest':{'id':'~vendor/latest','context_length':300000,'top_provider':{'max_completion_tokens':250000},'supported_parameters':['tools']},
}
def read(url,credential):
 assert credential==key;calls.append(url)
 p=urlsplit(url)
 if '/presets/' in p.path:
  slug=p.path.rsplit('/',1)[-1]
  config={'model':'~vendor/latest'} if slug=='latest' else {'models':['vendor/one','vendor/two'],'max_tokens':5000}
  if slug=='dynamic':config={'model':'openrouter/auto'}
  return {'data':{'status':'active','creator_user_id':'PRIVATE_CANARY','designated_version':{'config':config,'system_prompt':'PRIVATE_CANARY'}}}
 if p.hostname=='api-gateway.merge.dev':
  return {'model':'vendor/one','vendors':{'a':{'availability_status':'available','context_window':128000,'max_output_tokens':16000,'capabilities':{'supports_tool_calling':True}},
    'b':{'availability_status':'available','context_window':64000,'max_output_tokens':8000,'capabilities':{'supports_tool_calling':True}},
    'down':{'availability_status':'unavailable','context_window':1,'max_output_tokens':1}}}
 if p.hostname=='opencode.ai':return {'provider':{'opencode':{'models':{'vendor/one':{'limit':{'context':256000,'output':64000},'reasoning':True,'tool_call':True}}}}}
 mid=parse_qs(p.query)['q'][0]
 return {'data':[{'id':'unrelated','context_length':1},entries[mid]]}

definition={'endpoint':'https://openrouter.ai/api/v1/responses'}
a=meta.discover('openrouter',definition,'@preset/fixed',key,read)
assert (a['context'],a['output'],a['efforts'],a['tools'])==(100000,5000,None,True)
assert 'PRIVATE_CANARY' not in json.dumps(a) and key not in json.dumps(a)
b=meta.discover('openrouter',definition,'@preset/latest',key,read)
assert b['context']==300000 and b['output']==250000
c=meta.discover('merge',{'endpoint':'https://api-gateway.merge.dev/v1/openai/responses'},'vendor/one',key,read)
assert c['context']==64000 and c['output']==8000 and c['efforts'] is None
d=meta.discover('opencode',{'endpoint':'https://opencode.ai/zen/v1/chat/completions'},'vendor/one',key,read)
assert d['context']==256000 and d['efforts'] is None and not d['send_variant']
assert meta.entry_metadata({'reasoning':True})=={'context':None,'output':None,'efforts':None,'tools':None,'default_effort':None}
assert meta.entry_metadata({'context_length':True,'max_output_tokens':'4096'})['context'] is None
for pid,url,mid in [('openrouter','https://chatgpt.com/backend-api/codex/responses','vendor/one'),
 ('merge',definition['endpoint'],'@preset/fixed'),('openrouter',definition['endpoint'],'@preset/dynamic'),
 ('openrouter','https://proxy.example/v1/responses','@preset/fixed')]:
 try:meta.discover(pid,{'endpoint':url},mid,key,read);raise AssertionError('Unsafe/dynamic lookup accepted')
 except ValueError:pass
assert all(urlsplit(url).scheme=='https' and key not in url for url in calls)

providers=json.loads((root/'config/providers.json').read_text());catalog=json.loads((root/'config/models.json').read_text())
metadata={m['slug']:m for m in catalog['models']}
rows=[{'id':mid,'provider':pid,'label':metadata[mid]['display_name'],'context':metadata[mid]['context_window'],
 'output':route['output_limit'],'efforts':[e['effort'] for e in metadata[mid]['supported_reasoning_levels']],
 'default_effort':metadata[mid]['default_reasoning_level']} for pid,p in providers.items() for mid,route in p['models'].items()]
added={'id':'@preset/fixed','provider':'openrouter','label':'Owned fixture','context':a['context'],'output':a['output'],
 'efforts':['none'],'default_effort':'none','metadata_mode':'provider','reasoning_mode':'provider_default'}
request={'providers':{pid:{'endpoint':p['endpoint'],'default_model':p['default_model']} for pid,p in providers.items()},'models':rows+[added]}
p,m=prepare_configuration(request,providers,catalog)
scratch=root/'.local/test-work'/('metadata-'+uuid.uuid4().hex[:8]);scratch.mkdir(parents=True)
(scratch/'providers.json').write_text(json.dumps(p));(scratch/'models.json').write_text(json.dumps(m))
_,models,routes=load_registry(scratch)
previous_models,previous_routes=core.MODELS,core.EXTERNAL
try:
 core.MODELS=models;core.EXTERNAL=routes
 gateway=core.GatewayCore('metadata_fixture_capability_1234567890',12345,set(),lambda pid:key)
 prepared=gateway.prepare('POST',gateway.prefix+'/backend-api/codex/responses',
  [('Host','127.0.0.1:12345'),('Authorization','Bearer dummy-native-key'),('Content-Type','application/json')],
  json.dumps({'model':added['id'],'input':[{'role':'user','content':'Owned metadata fixture.'}],
   'tools':[],'stream':True,'reasoning':{'effort':'high'}}).encode())
 assert 'reasoning' not in json.loads(prepared.body)
 assert json.loads(prepared.body)['model']=='@preset/fixed'
 assert dict(prepared.headers)['Authorization']=='Bearer '+key
finally:core.MODELS,core.EXTERNAL=previous_models,previous_routes
assert 'max_tokens' not in prepare_chat({'model':'fixture','input':[]})
auto={'metadata_mode':'provider','output_limit':943718}
out={};limit_output(out,auto);assert 'max_output_tokens' not in out
out={'max_output_tokens':1200000};limit_output(out,auto);assert out['max_output_tokens']==943718
out={};limit_output(out,{'output_limit':4096});assert out['max_output_tokens']==4096
assert meta.entry_metadata({'reasoning':{'effort_values':['low','high'],'default_effort':'high'}})['default_effort']=='high'

# Settings saves must re-fetch automatic values, reject missing metadata before
# writes and retain the original source/next launch when staging fails.
project=scratch/'project';folder=project/'config';folder.mkdir(parents=True)
import shutil
for name in ('providers.json','models.json','instructions.json'):shutil.copyfile(root/'config'/name,folder/name)
shutil.copytree(root/'config/instructions',folder/'instructions')
old=project/'.local/deployment-old';(old/'gateway/keys').mkdir(parents=True)
(project/'.local/deployment-path.txt').write_text('.local/deployment-old')
settings=object.__new__(Settings);settings.project=project;settings.deployment=old;settings.lock=threading.Lock()
settings.fetch_metadata=lambda *args:a
snapshot=settings.snapshot();originals={name:(folder/name).read_bytes() for name in ('providers.json','models.json')}
assert settings.handle({'action':'metadata','revision':snapshot['revision'],'provider':'openrouter','model':'@preset/fixed'})==a
def stage(keys):
 actual=json.loads((folder/'providers.json').read_text())['openrouter']['models']['@preset/fixed']
 assert actual['output_limit']==5000 and actual['reasoning_mode']=='provider_default'
 raise ValueError('owned staging failure')
settings.stage=stage
spoof=copy.deepcopy(request);spoof['models'][-1].update(context=1000000,output=4096)
try:settings.handle({'action':'save','revision':snapshot['revision'],**spoof,'keys':{}});raise AssertionError('Failure not returned')
except ValueError as error:assert str(error)=='owned staging failure'
assert all((folder/name).read_bytes()==value for name,value in originals.items())
settings.fetch_metadata=lambda *args:{**a,'context':None}
try:settings.handle({'action':'save','revision':snapshot['revision'],**request,'keys':{}});raise AssertionError('Unknown limit guessed')
except ValueError as error:assert 'incomplete' in str(error)
assert all((folder/name).read_bytes()==value for name,value in originals.items())
print('PASS: provider-only metadata, designated presets/aliases, conservative limits, unknown reasoning/default omission, no private configuration exposure, authoritative save validation and rollback. No network or inference used.')
