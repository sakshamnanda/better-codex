"""Concurrent request draining, immutable deployments and atomic live routing."""
from pathlib import Path
from types import SimpleNamespace
import copy
import hashlib
import json
import shutil
import sys
import threading
import uuid

root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'src/desktop'));sys.path.insert(0,str(root/'src/gateway'))
from live_settings import ReloadGate,verify_generation,RequestSettings,SettingsGenerations
import provider_service as service
import provider_registry as registry
import runtime_mixed as mixed
from opencode_engine import OpenCodeEngine
from catalog_refresh import CatalogCache
from api_settings import prepare_configuration

gate=ReloadGate();started=threading.Event();finish=threading.Event();published=threading.Event();errors=[]
def request():
 try:
  with gate.request():
   started.set();assert finish.wait(5)
   # The private relay is a continuation of the existing outer request and
   # must finish even while the writer is waiting for that outer stream.
   with gate.request(continuation=True):pass
 except Exception as error:errors.append(type(error).__name__)
def replace():
 try:
  with gate.replace(timeout=5):assert gate.readers==0;published.set()
 except Exception as error:errors.append(type(error).__name__)
reader=threading.Thread(target=request);reader.start();assert started.wait(2)
writer=threading.Thread(target=replace);writer.start()
assert not published.wait(0.05);finish.set();reader.join(5);writer.join(5)
assert published.is_set() and not errors and gate.readers==0 and not gate.swapping
with gate.request():
 try:
  with gate.replace(timeout=0):raise AssertionError('Active request ignored')
 except ValueError:pass
assert not gate.swapping
owned_engine=OpenCodeEngine(lambda provider:'owned-unused-fixture-key',root=root/'.local/owned-data-fixture',executable_root=root/'.local/owned-executable-fixture')
assert owned_engine.directory.parent==owned_engine.root/'support'
assert owned_engine.executable_root!=owned_engine.root
owned_registry=copy.deepcopy((registry.PROVIDERS,registry.MODELS))
frozen_engine=OpenCodeEngine(lambda provider:'unused-fixture-only',registry=owned_registry)
first=next(iter(owned_registry[1]));original_limit=frozen_engine.models[first]['output_limit']
owned_registry[1][first]['output_limit']=1
assert frozen_engine.models[first]['output_limit']==original_limit

scratch=root/'.local/test-work'/('live-settings-'+uuid.uuid4().hex[:8]);local=scratch/'.local';local.mkdir(parents=True)
current,target=local/'deployment-original',local/'deployment-new'
vendor=scratch/'vendor';vendor.mkdir();(vendor/'owned.txt').write_text('Owned installed-build hash fixture')
manifest={'source_app':str(vendor),'installed_file_hashes':{'owned.txt':hashlib.sha256((vendor/'owned.txt').read_bytes()).hexdigest()},'native_models':['gpt-6.1-sol']}
providers=json.loads((root/'config/providers.json').read_text());providers.pop('opencode')
catalog=json.loads((root/'config/models.json').read_text())
def build(folder,p,c,code='owned immutable helper code'):
 folder.mkdir();(folder/'gateway/keys').mkdir(parents=True)
 for name,value in [('Deployment.json',manifest),('providers.json',p),('models.json',c)]:
  (folder/name).write_text(json.dumps(value))
 shutil.copyfile(root/'config/instructions.json',folder/'instructions.json')
 shutil.copytree(root/'config/instructions',folder/'instructions')
 (folder/'helper.py').write_text(code)
 checks={path.relative_to(folder).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.rglob('*') if path.is_file()}
 (folder/'Helper-Checksums.json').write_text(json.dumps(checks))
build(current,providers,catalog)
p=copy.deepcopy(providers);p['merge']['endpoint']='https://owned-provider.example/v1/responses'
c=copy.deepcopy(catalog);model=copy.deepcopy(next(m for m in c['models'] if m['slug']==p['openrouter']['default_model']))
model.update(slug='@preset/live-fixture',display_name='Owned live preset');c['models'].append(model)
p['openrouter']['models'][model['slug']]={'output_limit':2048}
build(target,p,c)
assert verify_generation(current,target)==target.resolve()
backup=(dict(registry.PROVIDERS),dict(registry.MODELS),dict(registry.ROUTES),set(mixed.EXTERNAL),
 copy.deepcopy(mixed.PROFILE_SETTINGS),dict(mixed.PROFILES),service.ROOT,mixed.external_adapter.KEY_STORAGE)
try:
 service.ROOT=current
 instance=object.__new__(service.Service);instance.current=current;instance.engine=None;instance.catalog_pending=False
 instance.reload_lock=threading.Lock();instance.reload_gate=ReloadGate()
 instance.relay=SimpleNamespace(catalog=registry.public_catalog(catalog,providers),opencode_engine=None);instance.gateway=SimpleNamespace(external_models=[])
 initial_p,initial_m,initial_r=registry.load_registry(current)
 registry.PROVIDERS.clear();registry.PROVIDERS.update(initial_p)
 registry.MODELS.clear();registry.MODELS.update(initial_m)
 registry.ROUTES.clear();registry.ROUTES.update(initial_r);mixed.EXTERNAL.clear();mixed.EXTERNAL.update(initial_r)
 before={path.relative_to(current).as_posix():path.read_bytes() for path in current.rglob('*') if path.is_file()}
 result=instance.apply_settings(target)
 assert result=={'catalog_pending':True,'catalog_changed':False}
 assert registry.ROUTES['zai/glm-5.3-flash'][1]=='https://owned-provider.example/v1/responses'
 assert model['slug'] not in registry.ROUTES and model['slug'] not in mixed.EXTERNAL
 assert all(m['slug']!=model['slug'] for m in instance.gateway.external_models)
 assert mixed.external_adapter.KEY_STORAGE==target/'gateway'
 assert before=={path.relative_to(current).as_posix():path.read_bytes() for path in current.rglob('*') if path.is_file()}
 assert instance.current==target and instance.engine is None
 # A dynamic-catalog helper publishes new native metadata and routing together.
 instance.current=current
 registry.PROVIDERS.clear();registry.PROVIDERS.update(initial_p)
 registry.MODELS.clear();registry.MODELS.update(initial_m)
 registry.ROUTES.clear();registry.ROUTES.update(initial_r);mixed.EXTERNAL.clear();mixed.EXTERNAL.update(initial_r)
 instance.relay.catalog=registry.public_catalog(catalog,providers)
 cache_path=scratch/'models_cache.json';publisher=CatalogCache(cache_path,scratch/'catalog-backups')
 _,etag=publisher.describe(registry.public_catalog(catalog,providers),'0.162.0')
 cache_path.write_text(json.dumps({'etag':etag,'identity':'owned-native-scope','client_version':'0.162.0','fetched_at':'2026-10-15T00:00:00Z','models':registry.public_catalog(catalog,providers)['models']}))
 instance.catalog_cache=publisher
 instance.settings_generations=SettingsGenerations(RequestSettings(copy.deepcopy((initial_p,initial_m,initial_r)),
     copy.deepcopy(mixed.PROFILE_SETTINGS),dict(mixed.PROFILES),registry.public_catalog(catalog,providers),current/'gateway'),instance.retire_engine)
 with instance.settings_generations.request() as (old_token,old_snapshot):
  # The actual service publication and cache refresh must both finish while an
  # existing native/external response still holds its original settings lease.
  result=instance.apply_settings(target)
  assert old_snapshot.key_storage==current/'gateway' and model['slug'] not in old_snapshot.registry[2]
  with instance.settings_generations.request() as (_,fresh):
   assert fresh.key_storage==target/'gateway' and model['slug'] in fresh.registry[2]
  instance.refresh_catalog()
 assert result=={'catalog_pending':False,'catalog_changed':True}
 assert model['slug'] in registry.ROUTES and model['slug'] in mixed.EXTERNAL
 assert any(m['slug']==model['slug'] for m in instance.gateway.external_models)
 assert any(m['slug']==model['slug'] for m in json.loads(cache_path.read_text(encoding='utf8'))['models'])
 assert json.loads(cache_path.read_text(encoding='utf8'))['identity']=='owned-native-scope'
 instance.refresh_catalog()
 # Retire all external routes without touching native entries or old chat
 # instruction mappings. Any previously owned engine is stopped after drain.
 retired_p,retired_c=prepare_configuration({'providers':{},'models':[]},p,c)
 removed=local/'deployment-removed';build(removed,retired_p,retired_c)
 stopped=[];old_engine=SimpleNamespace(stop=lambda:stopped.append(True))
 instance.engine=old_engine;instance.relay.opencode_engine=old_engine
 instance.settings_generations.publish(RequestSettings((p,*registry.load_registry(target)[1:]),
     copy.deepcopy(mixed.PROFILE_SETTINGS),dict(mixed.PROFILES),c,target/'gateway',old_engine))
 with instance.settings_generations.request():
  instance.apply_settings(removed)
  assert not registry.ROUTES and not mixed.EXTERNAL and instance.engine is None and stopped==[]
 assert stopped==[True]
 active_ids={m['slug'] for m in json.loads(cache_path.read_text(encoding='utf8'))['models']}
 assert not active_ids.intersection({mid for provider in p.values() for mid in provider['models']})
 assert all(m['slug'] in active_ids for m in c['models'] if m['slug'] in manifest['native_models'])
 instance.apply_settings(target)
 assert model['slug'] in registry.ROUTES and instance.engine is None
 publisher.restore_initial()
 # Source changes or tampered snapshots cannot enter the running helper.
 bad=local/'deployment-bad';build(bad,p,c,code='changed helper code')
 try:instance.apply_settings(bad);raise AssertionError('Code swap accepted')
 except ValueError:pass
 assert instance.current==target and registry.ROUTES['zai/glm-5.3-flash'][1]==p['merge']['endpoint']
 (target/'providers.json').write_text('{}')
 try:verify_generation(current,target);raise AssertionError('Tamper accepted')
 except ValueError:pass
finally:
 for obj,value in ((registry.PROVIDERS,backup[0]),(registry.MODELS,backup[1]),(registry.ROUTES,backup[2]),(mixed.EXTERNAL,backup[3]),(mixed.PROFILE_SETTINGS,backup[4]),(mixed.PROFILES,backup[5])):
  obj.clear();obj.update(value)
 service.ROOT=backup[6];mixed.external_adapter.KEY_STORAGE=backup[7]
print('PASS: live service publishes routes/credentials and refreshes metadata with an old request still active; snapshots retain old settings, engines retire after their last lease, original files retained, code changes and tampering rejected. No app or inference used.')
