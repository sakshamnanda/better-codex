"""Installed backend keeps its PID, chat/model state and PTY while models refresh."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import base64
import copy
import datetime
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import uuid
from urllib.parse import urlsplit,parse_qs

root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'src/desktop'));sys.path.insert(0,str(root/'src/gateway'))
from catalog_refresh import CatalogCache
from core import ToolNames
selected=root/os.environ.get('BETTER_CODEX_TEST_DEPLOYMENT',(root/'.local/deployment-path.txt').read_text().strip())
manifest=json.loads((selected/'Deployment.json').read_text());installed=Path(manifest['source_app'])
for name,expected in manifest['installed_file_hashes'].items():
 with (installed/name).open('rb') as handle:assert hashlib.file_digest(handle,'sha256').hexdigest()==expected
scratch=root/'.local/test-work'/('catalog-runtime-'+uuid.uuid4().hex[:8]);home=scratch/'home';home.mkdir(parents=True)
# Use real wire metadata but only dummy auth, a localhost provider and scratch state.
catalog=json.loads((root/'config/models.json').read_text());new=copy.deepcopy(catalog)
old_id='nvidia/nemotron-3-ultra-550b-a55b:free'
model=copy.deepcopy(next(x for x in new['models'] if x['slug']==old_id))
model.update(slug='owned/catalog-fixture',display_name='Owned catalog fixture',context_window=65536,max_context_window=65536,
 model_messages={'instructions_template':'Owned fixture instructions; obey project instructions and native permissions.','persistent_instructions':''})
new['models'].append(model)
def encode(value):return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
token=encode({'alg':'none'})+'.'+encode({'exp':4102444800,'email':'owned@example.invalid','https://api.openai.com/auth':{'chatgpt_account_id':'owned-account','chatgpt_plan_type':'pro'}})+'.owned-signature'
(home/'auth.json').write_text(json.dumps({'OPENAI_API_KEY':None,'tokens':{'access_token':token,'id_token':token,'refresh_token':'owned-unused','account_id':'owned-account'},'last_refresh':datetime.datetime.now(datetime.timezone.utc).isoformat()}))
auth_before=(home/'auth.json').read_bytes()
cache=CatalogCache(home/'models_cache.json',scratch/'catalog-backups')
observed=[];session=[];polls=[];failures=[]

class Backend(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,value,etag=None):
  raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
  if etag:self.send_header('ETag',etag)
  self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  path=urlsplit(self.path).path
  if path.endswith('/models'):
   version=parse_qs(urlsplit(self.path).query)['client_version'][0];_,etag=cache.describe(catalog,version);self.reply(catalog,etag)
  elif path.endswith('/accounts/check'):self.reply({'accounts':[{'id':'owned-account','workspace_backend_origin':'http://127.0.0.1:'+str(server.server_port),'account_routing_override':'NO_CONSTRAINT'}]})
  else:self.reply({})
 def do_POST(self):
  try:
   payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
   if not urlsplit(self.path).path.endswith('/responses'):self.reply({});return
   assert self.headers['Authorization']=='Bearer owned-provider-key'
   observed.append(payload['model'])
   names=ToolNames([tool for tool in payload.get('tools',[]) if tool.get('type') in {'namespace','function','custom'}])
   history=payload['input'];text=json.dumps(history)
   outputs={item.get('call_id'):item.get('output','') for item in history if item.get('type')=='function_call_output'}
   terminal=outputs.get('owned_terminal_call')
   if terminal is not None and not session:
    match=re.search(r'Process running with session ID (\d+)',str(terminal))
    if not match:
     (scratch/'terminal-fixture-output.txt').write_text(str(terminal),encoding='utf8')
     failures.append('terminal fixture failed');self.reply({});return
    session.append(int(match[1]))
   if 'owned_poll_call' in outputs:polls.append(str(outputs['owned_poll_call']))
   if 'OWNED_START_TERMINAL' in text and 'owned_terminal_call' not in outputs:
    tool=next(t['name'] for t in names.tools if t['name'].endswith('exec_command'))
    output=[{'type':'function_call','id':'fc_owned_terminal','name':tool,'call_id':'owned_terminal_call',
      'arguments':json.dumps({'cmd':"Write-Output 'OWNED_SESSION_STARTED'; Start-Sleep -Seconds 12; Write-Output 'OWNED_SESSION_FINISHED'",'yield_time_ms':1000})}]
   elif 'OWNED_POLL_TERMINAL' in text and 'owned_poll_call' not in outputs:
    tool=next(t['name'] for t in names.tools if t['name'].endswith('write_stdin'))
    output=[{'type':'function_call','id':'fc_owned_poll','name':tool,'call_id':'owned_poll_call',
      'arguments':json.dumps({'session_id':session[0],'chars':'','yield_time_ms':1000})}]
   else:output=[{'type':'message','id':'msg_owned','role':'assistant','status':'completed','content':[{'type':'output_text','text':'Owned runtime fixture completed.','annotations':[]}]}]
   wire=[{'type':'response.created','response':{'id':'resp_owned','status':'in_progress','output':[]}}]
   for i,item in enumerate(output):wire.extend([{'type':'response.output_item.added','output_index':i,'item':item},{'type':'response.output_item.done','output_index':i,'item':item}])
   wire.append({'type':'response.completed','response':{'id':'resp_owned','status':'completed','output':output,'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}}})
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
   for event in wire:
    for value in names.response_events(event):self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode());self.wfile.flush()
  except Exception as error:failures.append(type(error).__name__);raise

class FixtureServer(ThreadingHTTPServer):
 def handle_error(self,*args):
  # HTTP keep-alive sockets may reset while the owned backend exits; every
  # actual request-handler failure is retained in failures above.
  pass
server=FixtureServer(('127.0.0.1',0),Backend);threading.Thread(target=server.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(server.server_port)+'/backend-api'
(home/'config.toml').write_text('openai_base_url='+json.dumps(base+'/codex')+'\nchatgpt_base_url='+json.dumps(base)+
 '\n[features]\napps=false\nplugins=false\nmulti_agent=true\n[model_providers.fixture]\nname="Owned inference fixture"\nwire_api="responses"\nrequires_openai_auth=false\nenv_key="CODEX_OWNED_PROVIDER_KEY"\nbase_url='+json.dumps(base+'/codex'))
env={k:os.environ[k] for k in ('SystemRoot','WINDIR','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC') if k in os.environ}
env.update(CODEX_HOME=str(home),CODEX_OWNED_PROVIDER_KEY='owned-provider-key')
process=subprocess.Popen([str(installed/'resources/codex.exe'),'app-server','--listen','stdio://'],cwd=scratch,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',creationflags=subprocess.CREATE_NO_WINDOW)
mail=queue.Queue();pending=[];identifier=0
def read():
 for line in process.stdout:
  try:
   value=json.loads(line)
   if value.get('method')=='item/commandExecution/requestApproval' and 'id' in value:
    params=value.get('params',{});command=str(params.get('command',''))
    allowed='OWNED_SESSION_STARTED' in command and 'Start-Sleep' in command and 'OWNED_SESSION_FINISHED' in command
    process.stdin.write(json.dumps({'id':value['id'],'result':{'decision':'accept' if allowed else 'decline'}})+'\n');process.stdin.flush()
    if not allowed:failures.append('Unexpected command approval')
   else:mail.put(value)
  except ValueError:pass
threading.Thread(target=read,daemon=True).start()
def call(method,params):
 global identifier
 identifier+=1;process.stdin.write(json.dumps({'id':identifier,'method':method,'params':params})+'\n');process.stdin.flush()
 while True:
  value=mail.get(timeout=30)
  if value.get('id')==identifier:
   assert 'error' not in value,'Owned RPC failed: '+method
   return value.get('result',{})
  pending.append(value)
def completed():
 events=[]
 while True:
  value=pending.pop(0) if pending else mail.get(timeout=30);events.append(value)
  if value.get('method')=='turn/completed':
   assert value['params']['turn']['status']=='completed','Owned inference fixture failed'
   return events
def start(mid):return call('thread/start',{'model':mid,'modelProvider':'fixture','ephemeral':True,'cwd':str(scratch),'approvalPolicy':'on-request','sandbox':'workspace-write'})['thread']['id']
def turn(tid,text):call('turn/start',{'threadId':tid,'input':[{'type':'text','text':text}]});return completed()
try:
 call('initialize',{'clientInfo':{'name':'owned-catalog-runtime','version':'1'},'capabilities':{'experimentalApi':True}})
 process.stdin.write('{"method":"initialized"}\n');process.stdin.flush()
 before=call('model/list',{'includeHidden':True,'limit':100});old=start(old_id)
 turn(old,'OWNED_START_TERMINAL');assert session
 pid=process.pid;catalog=new;cache.publish(new)
 after=call('model/list',{'includeHidden':True,'limit':100})
 assert any(m.get('model')==model['slug'] for m in after['data'])
 added=start(model['slug']);events=turn(added,'Owned new model context check.')
 limits=[v['params']['tokenUsage']['modelContextWindow'] for v in events if v.get('method')=='thread/tokenUsage/updated']
 assert limits and limits[-1]==int(65536*0.95),limits
 loaded=call('thread/loaded/list',{})['data'];assert old in loaded and added in loaded
 count=len(observed);turn(old,'OWNED_POLL_TERMINAL');assert observed[count:]==[old_id,old_id]
 assert polls and not any('Unknown process' in out or 'not found' in out for out in polls)
 assert process.pid==pid and process.poll() is None and not failures
 assert (home/'auth.json').read_bytes()==auth_before
 print('PASS: same installed backend discovers a new model with its reported context, retains both chats and the old model, and polls the pre-refresh native PTY session. Dummy metadata/inference only; no real account or provider used.')
finally:
 process.terminate();process.wait(timeout=10);server.shutdown();server.server_close();cache.restore_initial()
