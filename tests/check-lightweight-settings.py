"""Routine saves touch only small snapshots: no network, builder or vendor copy."""
from pathlib import Path
from unittest.mock import patch
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import time
import urllib.request

root=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(root/'src/desktop'),str(root/'src/gateway')]
import api_settings
from api_settings import Settings,prepare_credentials
from live_settings import verify_settings_generation

with tempfile.TemporaryDirectory(dir=root/'.local',prefix='small-settings-check-') as directory:
    project=Path(directory);config=project/'config';config.mkdir()
    for name in ('providers.json','models.json','instructions.json'):shutil.copyfile(root/'config'/name,config/name)
    shutil.copytree(root/'config/instructions',config/'instructions')
    providers=json.loads((config/'providers.json').read_text())
    for p in providers.values():
        for route in p['models'].values():route['metadata_mode']='provider'
    (config/'providers.json').write_text(json.dumps(providers))
    runtime=project/'.local/deployment-runtime';(runtime/'gateway/keys').mkdir(parents=True)
    (runtime/'support').mkdir()
    for name in ('providers.json','models.json','instructions.json'):shutil.copyfile(config/name,runtime/name)
    (project/'scripts').mkdir();(project/'scripts/build-deployment.py').write_text('raise AssertionError("Builder must not run")')
    (runtime/'Deployment.json').write_text(json.dumps({'owned-build':'fixture','native_models':['gpt-6.1-sol']}))
    shutil.copyfile(root/'src/gateway/Provider-Credentials.ps1',runtime/'gateway/Provider-Credentials.ps1')
    checks={name:hashlib.sha256((runtime/name).read_bytes()).hexdigest() for name in ('Deployment.json','gateway/Provider-Credentials.ps1')}
    (runtime/'Helper-Checksums.json').write_text(json.dumps(checks))
    runtime_pointer=project/'.local/deployment-path.txt';runtime_pointer.write_text('.local/deployment-runtime')
    applied=[];active=[runtime]
    def apply(target):
        verify_settings_generation(runtime,target);applied.append(target);active[0]=target;return {'catalog_pending':False}
    settings=Settings(runtime,apply,lambda:{'ui_reload':True},lambda:active[0])
    settings.fetch_metadata=lambda *args:(_ for _ in ()).throw(AssertionError('Routine save fetched metadata'))
    current=settings.snapshot();draft_models=copy.deepcopy(current['models']);draft_models[0]['label']='Owned renamed fixture'
    keys={pid:{'active':p['credential_profiles']['active'],'profiles':[{'id':k['id'],'label':k['label'],'key':''} for k in p['credential_profiles']['profiles']]} for pid,p in current['providers'].items()}
    assert prepare_credentials(keys,current['providers'])=={}
    saved_bytes=[];copy_file=shutil.copyfile;copy_tree=shutil.copytree
    def small_file(source,dest,*args,**kwargs):
        assert 'node_modules' not in Path(source).parts and 'opencode-engine' not in Path(source).parts
        saved_bytes.append(Path(source).stat().st_size);return copy_file(source,dest,*args,**kwargs)
    def small_tree(source,dest,*args,**kwargs):
        assert 'node_modules' not in Path(source).parts and 'opencode-engine' not in Path(source).parts
        return copy_tree(source,dest,*args,**kwargs)
    def no_process(*args,**kwargs):raise AssertionError('Routine save spawned builder/check/key subprocess')
    with patch.object(api_settings.shutil,'copyfile',small_file),patch.object(api_settings.shutil,'copytree',small_tree),patch.object(api_settings.subprocess,'run',no_process):
        started=time.perf_counter()
        result=settings.handle({'action':'save','revision':current['revision'],'providers':{pid:{k:p[k] for k in ('endpoint','default_model')} for pid,p in current['providers'].items()},'models':draft_models,'keys':keys})
        elapsed=time.perf_counter()-started
    assert result['live_applied'] and len(applied)==1 and runtime_pointer.read_text()=='.local/deployment-runtime'
    target=applied[0];assert settings.selected()==target and target.name.startswith('settings-')
    assert not (target/'opencode-engine').exists() and not (target/'launcher.py').exists()
    assert not (target/'support/opencode-runtime').exists()
    # A second deletion also reuses saved metadata and the same code/runtime.
    current=settings.snapshot();models=copy.deepcopy(current['models']);removed=models.pop()
    changes={pid:{k:p[k] for k in ('endpoint','default_model')} for pid,p in current['providers'].items()}
    changes[removed['provider']]['default_model']=next((m['id'] for m in models if m['provider']==removed['provider']),'')
    with patch.object(api_settings.subprocess,'run',no_process):
        result=settings.handle({'action':'save','revision':current['revision'],'providers':changes,'models':models,'keys':{}})
    assert result['live_applied'] and len(applied)==2
    assert result['settings']['apply_pending'] is False
    assert removed['id'] not in {m['id'] for m in result['settings']['models']}
    assert (target/'models.json').exists() # Prior immutable snapshot retained.
    settings.stage_settings()
    assert settings.snapshot()['apply_pending'] is True
    reopened=Settings(runtime,apply,lambda:{'ui_reload':True},lambda:active[0])
    assert reopened.snapshot()['apply_pending'] is True
    assert reopened.apply_selected()['settings']['apply_pending'] is False
    tampered=settings.selected();original=(tampered/'providers.json').read_bytes()
    (tampered/'providers.json').write_text('{}')
    try:verify_settings_generation(runtime,tampered);raise AssertionError('Tampered settings accepted')
    except ValueError:pass
    (tampered/'providers.json').write_bytes(original)
    # Reopening the helper selects the saved data snapshot before discovery;
    # it does not need a copied launcher or executable in the snapshot folder.
    import provider_service
    import runtime_mixed
    baseline=provider_service.ROOT;log_root=runtime_mixed.SUPPORT
    provider_service.ROOT=runtime;runtime_mixed.SUPPORT=project/'logs';runtime_mixed.SUPPORT.mkdir()
    service=provider_service.Service()
    try:
        home=project/'owned-home';home.mkdir()
        service.start(home)
        assert service.current==tampered
        req=urllib.request.Request(service.base_url+'/models?client_version=0.162.0',headers={'Authorization':'Bearer owned-metadata-fixture'})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5) as response:catalog=json.loads(response.read())
        assert removed['id'] not in {m['slug'] for m in catalog['models']}
        assert service.relay.settings_generations is service.gateway.settings_generations
        # A real DPAPI key edit uses the small snapshot path too, with no model
        # discovery and no catalog/UI refresh when only credentials changed.
        settings.live_apply=service.apply_settings
        settings.current_selection=lambda:service.current
        current=settings.snapshot();pid='openrouter'
        entry=current['providers'][pid]['credential_profiles']
        key_edit={pid:{'active':entry['active'],'profiles':[{'id':p['id'],'label':p['label'],'key':'owned-dummy-fast-save-key' if p['id']==entry['active'] else ''} for p in entry['profiles']]}}
        result=settings.handle({'action':'save','revision':current['revision'],'providers':{p:{k:v[k] for k in ('endpoint','default_model')} for p,v in current['providers'].items()},'models':current['models'],'keys':key_edit})
        assert result['live_applied'] and result['catalog_changed'] is False and 'no UI reload needed' in result['message']
        encrypted=settings.selected()/'gateway/keys/openrouter.dpapi'
        assert encrypted.exists() and b'owned-dummy-fast-save-key' not in encrypted.read_bytes()
        # Toggle with an actual encrypted fixture key: no deletion or discovery,
        # public catalog/routing change together, then restore the same key.
        ciphertext=encrypted.read_bytes();configured=result['settings']['models']
        _,etag=service.catalog_cache.describe(service.relay.catalog,'0.162.0')
        (home/'models_cache.json').write_text(json.dumps({'fetched_at':'2026-10-15T00:00:00Z','etag':etag,'identity':'owned-fixture-scope','client_version':'0.162.0','models':service.relay.catalog['models']}))
        for enabled in (False,True):
            current=settings.snapshot();changes={p:{k:v[k] for k in ('endpoint','default_model','enabled')} for p,v in current['providers'].items()}
            changes[pid]['enabled']=enabled
            result=settings.handle({'action':'save','revision':current['revision'],'providers':changes,'models':current['models'],'keys':{}})
            assert result['live_applied'] and result['settings']['providers'][pid]['enabled'] is enabled
            assert len(result['settings']['models'])==len(configured)
            assert (settings.selected()/'gateway/keys/openrouter.dpapi').read_bytes()==ciphertext
            routed={mid for mid,route in provider_service.provider_registry.ROUTES.items() if route[0]==pid}
            assert bool(routed) is enabled
            assert any(m['slug'] in {row['id'] for row in configured if row['provider']==pid} for m in service.relay.catalog['models']) is enabled
        mid=next(row['id'] for row in configured if row['provider']==pid)
        for enabled in (False,True):
            current=settings.snapshot();rows=current['models']
            next(row for row in rows if row['id']==mid)['enabled']=enabled
            result=settings.handle({'action':'save','revision':current['revision'],'providers':{p:{k:v[k] for k in ('endpoint','default_model','enabled')} for p,v in current['providers'].items()},'models':rows,'keys':{}})
            assert result['live_applied'] and next(row for row in result['settings']['models'] if row['id']==mid)['enabled'] is enabled
            assert len(result['settings']['models'])==len(configured)
            assert (mid in provider_service.provider_registry.ROUTES) is enabled
            assert any(m['slug']==mid for m in service.relay.catalog['models']) is enabled
            assert (mid in result['provider_config']['disabledModels']) is not enabled
            assert (settings.selected()/'gateway/keys/openrouter.dpapi').read_bytes()==ciphertext
    finally:
        service.stop();provider_service.ROOT=baseline;runtime_mixed.SUPPORT=log_root
    print(f'PASS: rename/delete reuse metadata and verified runtime; no network/subprocess/vendor copy, tampering rejected. Fixture save {elapsed:.3f}s; copied {sum(saved_bytes)/1024:.1f} KiB of small settings/instructions.')
