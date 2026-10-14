"""Offline settings validation, rollback, DPAPI and private renderer boundary checks."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

root = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root / 'src/desktop'))
sys.path.insert(0,str(root / 'src/gateway'))
from api_settings import Settings, prepare_configuration, credential_profiles, prepare_credentials
from provider_registry import load_registry
from signed_overlay import PrivatePipe

providers = json.loads((root / 'config/providers.json').read_text())
catalog = json.loads((root / 'config/models.json').read_text())
metadata = {m['slug']:m for m in catalog['models']}
rows = [{'id':mid,'provider':pid,'label':metadata[mid]['display_name'],'context':metadata[mid]['context_window'],
    'output':route.get('output_limit',4096),'efforts':[e['effort'] for e in metadata[mid]['supported_reasoning_levels']],
    'default_effort':metadata[mid]['default_reasoning_level']} for pid,p in providers.items() for mid,route in p['models'].items()]
request = {'providers':{pid:{'endpoint':p['endpoint'],'default_model':p['default_model']} for pid,p in providers.items()},'models':rows}
added = {**rows[0], 'id':'fixture/new-model','label':'New fixture model'}
p,m = prepare_configuration({**request,'models':rows + [added]},providers,catalog)
assert p['openrouter']['models'][added['id']]['output_limit'] == added['output']
new_messages=next(x for x in m['models'] if x['slug']==added['id'])['model_messages']
assert new_messages['instructions_template'] and new_messages['persistent_instructions']==''
assert added['id'] not in new_messages['instructions_template']
external = {mid for provider in providers.values() for mid in provider['models']}
assert [x for x in m['models'] if x['slug'] not in external and x['slug']!=added['id']] == [x for x in catalog['models'] if x['slug'] not in external]
assert 'fixture/new-model' not in providers['openrouter']['models']
for changes in ({'models':rows[:-1]}, {'models':[dict(rows[0],id='gpt-6.1-sol')] + rows[1:]},
    {'models':[dict(rows[0],output=rows[0]['context'])] + rows[1:]},
    {'models':[dict(rows[0],efforts=['invented'])] + rows[1:]}):
    try: prepare_configuration({**request,**changes},providers,catalog); raise AssertionError('Invalid edit accepted')
    except ValueError: pass

with tempfile.TemporaryDirectory(dir=root / '.local',prefix='settings-check-') as directory:
    project = Path(directory)
    config = project / 'config'; config.mkdir()
    for name in ('providers.json','models.json','instructions.json'): shutil.copyfile(root / 'config' / name,config / name)
    shutil.copytree(root / 'config/instructions',config / 'instructions')
    local = project / '.local'; local.mkdir()
    old = local / 'deployment-old'; (old / 'gateway/keys').mkdir(parents=True)
    selection = local / 'deployment-path.txt'; selection.write_text('.local/deployment-old')
    # The fixture object cannot call a real launcher.
    settings = object.__new__(Settings); settings.project = project; settings.deployment = old; settings.lock = threading.Lock()
    settings.stage = lambda keys: (_ for _ in ()).throw(ValueError('fixture staging failure'))
    current = settings.snapshot()
    originals = {name:(config / name).read_bytes() for name in ('providers.json','models.json')}
    changed = copy.deepcopy(request); changed['models'][0]['label'] = 'Edited fixture label'
    try: settings.handle({'action':'save','revision':current['revision'],**changed,'keys':{}}); raise AssertionError('Failure not returned')
    except ValueError as error: assert str(error) == 'fixture staging failure'
    assert all((config / name).read_bytes()==data for name,data in originals.items())
    assert selection.read_text() == '.local/deployment-old'
    assert not any('key' in key and key != 'saved_key' for p in current['providers'].values() for key in p)
    for url in ('http://api.example/v1/responses','https://secret@api.example/v1/responses','https://chatgpt.com/backend-api/codex/responses'):
        edited = copy.deepcopy(providers); edited['openrouter']['endpoint'] = url
        (config / 'providers.json').write_text(json.dumps(edited))
        try: load_registry(config); raise AssertionError('Unsafe destination accepted')
        except ValueError: pass
    (config / 'providers.json').write_bytes(originals['providers.json'])
    # Real Windows encryption, using fixture keys only and an isolated key folder.
    gateway = project / 'gateway'; gateway.mkdir()
    shutil.copyfile(root / 'src/gateway/Provider-Credentials.ps1',gateway / 'Provider-Credentials.ps1')
    shutil.copyfile(config / 'providers.json',project / 'providers.json')
    ps = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    cmd = [ps,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(gateway / 'Provider-Credentials.ps1')]
    fixture = 'dummy-local-settings-key-only'
    result = subprocess.run(cmd+['-Mode','SaveJson'],input=json.dumps({'openrouter':fixture}),capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and fixture not in result.stdout + result.stderr
    encrypted = (gateway / 'keys/openrouter.dpapi').read_bytes()
    assert fixture.encode() not in encrypted
    result = subprocess.run(cmd+['-Mode','SaveJson'],input=json.dumps({'openrouter':'','merge':'dummy-merge-only'}),capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and (gateway / 'keys/openrouter.dpapi').read_bytes() == encrypted
    result = subprocess.run(cmd+['-Mode','Token','-Provider','openrouter'],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and result.stdout == fixture
    result = subprocess.run(cmd+['-Mode','SaveJson'],input=json.dumps({'openrouter':'bad\nkey'}),capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode != 0 and (gateway / 'keys/openrouter.dpapi').read_bytes() == encrypted
    default_merge = (gateway / 'keys/merge.dpapi').read_bytes()
    second = 'dummy-second-merge-profile-only'
    profile_edit = {'merge':{'active':'secondary','profiles':[
        {'id':'default','label':'Personal','key':''},
        {'id':'secondary','label':'Work','key':second}]}}
    metadata = credential_profiles(gateway / 'keys',providers)
    current_providers = {pid:{'credential_profiles':entry} for pid,entry in metadata.items()}
    normalized = prepare_credentials(profile_edit,current_providers)
    result = subprocess.run(cmd+['-Mode','SaveProfiles'],input=json.dumps(normalized),capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and second not in result.stdout + result.stderr
    assert (gateway / 'keys/merge.dpapi').read_bytes() == default_merge
    assert second.encode() not in (gateway / 'keys/merge--secondary.dpapi').read_bytes()
    assert second not in (gateway / 'keys/Profiles.json').read_text(encoding='utf-8')
    result = subprocess.run(cmd+['-Mode','Token','-Provider','merge'],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and result.stdout == second
    metadata = credential_profiles(gateway / 'keys',providers)
    assert metadata['merge']['active'] == 'secondary' and len(metadata['merge']['profiles']) == 2
    assert all(p['saved'] for p in metadata['merge']['profiles'])
    assert second not in json.dumps(metadata)
    profile_edit['merge']['active'] = 'default'
    profile_edit['merge']['profiles'][1]['key'] = ''
    current_providers = {pid:{'credential_profiles':entry} for pid,entry in metadata.items()}
    normalized = prepare_credentials(profile_edit,current_providers)
    result = subprocess.run(cmd+['-Mode','SaveProfiles'],input=json.dumps(normalized),capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and (gateway / 'keys/merge.dpapi').read_bytes() == default_merge
    result = subprocess.run(cmd+['-Mode','Token','-Provider','merge'],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and result.stdout == 'dummy-merge-only'
    # Selection is provider-scoped, never a fallback to another provider's key.
    result = subprocess.run(cmd+['-Mode','Token','-Provider','openrouter'],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0 and result.stdout == fixture
    for changed in (
        {'active':'missing','profiles':profile_edit['merge']['profiles']},
        {'active':'default','profiles':profile_edit['merge']['profiles'][:1]},
        {'active':'default','profiles':[profile_edit['merge']['profiles'][0],{'id':'../unsafe','label':'Unsafe','key':'dummy'}]},
        {'active':'default','profiles':[profile_edit['merge']['profiles'][0],{'id':'secondary','label':'Personal','key':''}]},
    ):
        try: prepare_credentials({'merge':changed},current_providers); raise AssertionError('Unsafe key-profile edit accepted')
        except ValueError: pass

class Boundary(PrivatePipe):
    def __init__(self):
        self.settings_session = 'owned'; self.trusted_contexts = set(); self.calls=[]; self.requests=[]
        self.settings_handler = lambda request: self.requests.append(request) or {'saved':True}
        self.settings_assets = {'settings.js':(hashlib.sha256(b'known-source').hexdigest(),'new-source')}
    def call(self,method,params=None,session=None,timeout=20):
        self.calls.append((method,params))
        if method == 'Fetch.getResponseBody': return {'body':'unknown-source','base64Encoded':False}
        return {}
pipe=Boundary()
def context(cid, origin, default=True):
    pipe.settings_event({'method':'Runtime.executionContextCreated','sessionId':'owned','params':{'context':{'id':cid,'origin':origin,'auxData':{'isDefault':default}}}})
context(1,'https://untrusted.example');context(2,'app://-',False);context(3,'app://-')
for cid in (1,2,3):
    event={'method':'Runtime.bindingCalled','sessionId':'owned','params':{'name':'betterCodexSettings','executionContextId':cid,'payload':json.dumps({'id':cid,'request':{'action':'get'}})}}
    pipe.settings_event(event)
    if cid==3: assert event['params']['payload'] is None
assert pipe.requests == [{'action':'get'}]
assert len(pipe.calls)==1 and pipe.calls[0][0]=='Runtime.evaluate'
pipe.settings_event({'method':'Fetch.requestPaused','sessionId':'owned','params':{'requestId':'fixture','request':{'url':'app://-/assets/settings.js'}}})
assert pipe.calls[-1][0] == 'Fetch.continueRequest'
assert not any(method=='Fetch.fulfillRequest' for method,params in pipe.calls)
print('PASS: native capabilities and rollback retained; named keys DPAPI encrypted, blank values preserved, active-profile switching/provider isolation verified; unsafe profiles, renderer contexts and unknown assets rejected.')
