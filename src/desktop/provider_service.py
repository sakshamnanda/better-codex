"""Independent native/external service; no test GUI or live credential-file access."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import json
import hashlib
import os
import secrets
import threading
import copy
import subprocess
import runtime_mixed as mixed
from provider_registry import PROVIDERS
import provider_registry
from model_profiles import load_profiles
from live_settings import ReloadGate,verify_generation,verify_settings_generation,RequestSettings,SettingsGenerations
from catalog_refresh import CatalogCache
from api_settings import credential_profiles

ROOT = Path(__file__).resolve().parent

def needs_opencode(folder,providers):
    if not any(route.get('enabled',True) for route in providers.get('opencode',{}).get('models',{}).values()) or not providers['opencode'].get('enabled',True):return False
    entry=credential_profiles(folder/'gateway/keys',{'opencode':providers['opencode']})['opencode']
    return any(p['id']==entry['active'] and p['saved'] for p in entry['profiles'])

class Service:
    def start(self,codex_home=None):
        self.started_servers = []
        self.retired_engines=[]
        self.reload_lock=threading.Lock()
        self.reload_gate=ReloadGate()
        self.current=ROOT
        self.runtime_sha256=hashlib.sha256((ROOT/'Helper-Checksums.json').read_bytes()).hexdigest()
        pointer=ROOT.parent/'settings-path.txt'
        if pointer.exists():
            self.current=verify_settings_generation(ROOT,ROOT.parent.parent/pointer.read_text().strip(),self.runtime_sha256)
            providers,models,routes=provider_registry.load_registry(self.current)
            settings,profiles=load_profiles(self.current)
            provider_registry.PROVIDERS.clear();provider_registry.PROVIDERS.update(providers)
            provider_registry.MODELS.clear();provider_registry.MODELS.update(models)
            provider_registry.ROUTES.clear();provider_registry.ROUTES.update(routes)
            mixed.EXTERNAL.clear();mixed.EXTERNAL.update(routes)
            mixed.PROFILE_SETTINGS.clear();mixed.PROFILE_SETTINGS.update(settings)
            mixed.PROFILES.clear();mixed.PROFILES.update(profiles)
        mixed.external_adapter.KEY_STORAGE=self.current/'gateway'
        self.catalog_pending=False
        real = mixed.external_adapter
        self.engine = None
        if needs_opencode(self.current,PROVIDERS):
            self.engine = real.OpenCodeEngine(real.key_supplier,root=self.current,executable_root=ROOT)
            self.engine.start(caller_tools=True)
        catalog = provider_registry.public_catalog(json.loads((self.current / 'models.json').read_text()),PROVIDERS)
        self.catalog_cache=CatalogCache(Path(codex_home or Path(os.environ['USERPROFILE'])/'.codex')/'models_cache.json',
            ROOT.parent/'catalog-backups')
        manifest = json.loads((ROOT / 'Deployment.json').read_text())
        self.relay = ThreadingHTTPServer(('127.0.0.1',0),real.RealGateway)
        self.relay.daemon_threads = True
        self.relay.reload_gate=self.reload_gate
        self.relay.prefix = '/relay_' + secrets.token_urlsafe(32)
        self.relay.token = mixed.DUMMY
        self.relay.catalog = catalog
        self.relay.opencode_engine = self.engine
        self.gateway = ThreadingHTTPServer(('127.0.0.1',0),mixed.MixedGateway)
        self.gateway.daemon_threads = True
        self.gateway.reload_gate=self.reload_gate
        self.gateway.catalog_cache=self.catalog_cache
        self.gateway.model_catalog=catalog
        self.gateway.capability = secrets.token_urlsafe(32)
        self.gateway.native_models = set(manifest['native_models'])
        self.gateway.external_models = [model for model in catalog['models'] if model['slug'] in mixed.EXTERNAL]
        self.gateway.external_url = f'http://127.0.0.1:{self.relay.server_port}{self.relay.prefix}/backend-api/codex/responses'
        self.settings_generations=SettingsGenerations(RequestSettings(
            copy.deepcopy((provider_registry.PROVIDERS,provider_registry.MODELS,provider_registry.ROUTES)),
            copy.deepcopy(mixed.PROFILE_SETTINGS),dict(mixed.PROFILES),catalog,self.current/'gateway',self.engine),self.retire_engine)
        for server in (self.relay,self.gateway):server.settings_generations=self.settings_generations
        for server in (self.relay,self.gateway):
            threading.Thread(target=server.serve_forever,daemon=True).start()
            self.started_servers.append(server)
        self.base_url = f'http://127.0.0.1:{self.gateway.server_port}/g/{self.gateway.capability}/backend-api/codex'
        (ROOT / 'support/Gateway-State.json').write_text(json.dumps({'helper_pid':os.getpid(),'opencode_pid':self.engine.process.pid if self.engine else None,
            'opencode_pids':[self.engine.process.pid] if self.engine else [],'base_url':self.base_url,'ready':True,'settings_deployment':self.current.name}))
        print('Standalone provider service ready; installed configuration untouched until explicit launch.',flush=True)
        return self

    def apply_settings(self,target):
        """Settings only; no app/backend restart, request cancellation or code swap."""
        with self.reload_lock:
            target=Path(target).resolve()
            if target==self.current:return {'catalog_pending':self.catalog_pending,'catalog_changed':False}
            if (target/'Settings-Manifest.json').exists():
                target=verify_settings_generation(ROOT,target,self.runtime_sha256)
            else:target=verify_generation(ROOT,target)
            providers,models,routes=provider_registry.load_registry(target)
            settings,profiles=load_profiles(target)
            catalog=provider_registry.public_catalog(json.loads((target/'models.json').read_text()),providers)
            current_catalog=provider_registry.public_catalog(json.loads((ROOT/'models.json').read_text()),json.loads((ROOT/'providers.json').read_text()))
            catalog_pending=catalog!=current_catalog and not getattr(self,'catalog_cache',None)
            if catalog_pending:
                # Keep the runtime and the cached native controls in agreement.
                # Routes for new models and changed limits/efforts remain pending;
                # keys, endpoints, labels and valid existing defaults can change.
                models=copy.deepcopy(provider_registry.MODELS)
                routes={mid:(entry[0],providers[entry[0]]['endpoint'],entry[2],entry[3])
                    for mid,entry in provider_registry.ROUTES.items()}
                for pid,p in providers.items():
                    flags={mid:route.get('enabled',True) for mid,route in p['models'].items()}
                    p['models']={mid:{**{k:v for k,v in model.items() if k not in {'provider','metadata'}},'enabled':flags.get(mid,False)}
                        for mid,model in models.items() if model['provider']==pid}
                    if p['default_model'] not in p['models']:p['default_model']=provider_registry.PROVIDERS[pid]['default_model']
                models={mid:model for mid,model in models.items() if providers[model['provider']].get('enabled',True) and providers[model['provider']]['models'][mid]['enabled']}
                routes={mid:route for mid,route in routes.items() if mid in models}
                catalog=provider_registry.public_catalog(current_catalog,providers)
            catalog_changed=catalog!=self.relay.catalog
            # Production requests pin immutable settings, including the private
            # relay hop. Shared defaults below serve standalone legacy callers.
            real=mixed.external_adapter
            candidate=None
            receipt=None
            def engine_provider(value):
                p=value.get('opencode',{})
                return tuple(p.get(k) for k in ('adapter','endpoint','default_model'))+(p.get('enabled',True),)
            def engine_models(value):
                return {mid:(m['output_limit'],m.get('send_variant',False),m['metadata']['context_window'],
                    tuple(sorted(e['effort'] for e in m['metadata']['supported_reasoning_levels'])))
                    for mid,m in value.items() if m['provider']=='opencode'}
            opencode_changed=engine_provider(providers)!=engine_provider(provider_registry.PROVIDERS) or engine_models(models)!=engine_models(provider_registry.MODELS)
            def credentials(folder):
                keys=folder/'gateway/keys'
                index=json.loads((keys/'Profiles.json').read_text()) if (keys/'Profiles.json').exists() else {}
                active=index.get('providers',{}).get('opencode',{}).get('active','default')
                path=keys/('opencode'+('' if active=='default' else '--'+active)+'.dpapi')
                return active,path.read_bytes() if path.exists() else None
            opencode_changed=opencode_changed or credentials(target)!=credentials(self.current)
            engine_needed=needs_opencode(target,providers)
            try:
                if engine_needed and (opencode_changed or self.engine is None):
                    # Prepare and validate a replacement inference engine while
                    # the old one continues serving. Never mutate its files.
                    def candidate_key(pid):
                        ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
                        result=subprocess.run([str(ps),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'gateway/Provider-Credentials.ps1'),
                            '-Mode','Token','-Provider',pid,'-Storage',str(target/'gateway')],capture_output=True,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
                        if result.returncode:raise ValueError('Selected OpenCode credential could not be loaded; running setup retained.')
                        return result.stdout
                    # Keep the original verified executable/parent identity so
                    # guarded crash recovery can recognize replacement engines.
                    candidate=real.OpenCodeEngine(candidate_key,root=target,registry=(providers,models),executable_root=ROOT)
                    candidate.start(caller_tools=True)
                state_path=ROOT/'support/Gateway-State.json'
                pending_state=state_path.with_suffix('.live-tmp')
                if state_path.exists():
                    state=json.loads(state_path.read_text())
                    if state.get('helper_pid')!=os.getpid():raise ValueError('Live helper ownership could not be verified.')
                    active_engine=(candidate or self.engine) if engine_needed else None
                    # Old generations can still own an engine. Preserve their
                    # PIDs for guarded crash recovery; dead/reused retired PIDs
                    # are checked again and never stopped without ownership.
                    engine_pids=set(state.get('opencode_pids',[]))
                    if state.get('opencode_pid'):engine_pids.add(state['opencode_pid'])
                    if active_engine:engine_pids.add(active_engine.process.pid)
                    state.update(opencode_pid=active_engine.process.pid if active_engine else None,
                        opencode_pids=sorted(engine_pids),settings_deployment=target.name,catalog_refresh_pending=catalog_pending)
                    pending_state.write_text(json.dumps(state))
                def commit():
                    nonlocal candidate,receipt
                    if getattr(self,'catalog_cache',None) and catalog!=self.relay.catalog:
                        receipt=self.catalog_cache.publish(catalog)
                    if pending_state.exists():pending_state.replace(state_path)
                    provider_registry.PROVIDERS.clear();provider_registry.PROVIDERS.update(providers)
                    provider_registry.MODELS.clear();provider_registry.MODELS.update(models)
                    provider_registry.ROUTES.clear();provider_registry.ROUTES.update(routes)
                    mixed.EXTERNAL.clear();mixed.EXTERNAL.update(routes)
                    mixed.PROFILE_SETTINGS.clear();mixed.PROFILE_SETTINGS.update(settings)
                    mixed.PROFILES.clear();mixed.PROFILES.update(profiles)
                    real.KEY_STORAGE=target/'gateway'
                    self.relay.catalog=catalog
                    self.gateway.external_models=[m for m in catalog['models'] if m['slug'] in routes]
                    self.gateway.model_catalog=catalog
                    if candidate or not engine_needed:
                        self.engine=candidate;self.relay.opencode_engine=candidate
                    self.current=target;self.catalog_pending=catalog_pending
                    candidate=None
                    receipt=None
                generations=getattr(self,'settings_generations',None)
                active_engine=(candidate or self.engine) if engine_needed else None
                if generations:
                    generations.publish(RequestSettings((providers,models,routes),settings,profiles,catalog,target/'gateway',active_engine),commit)
                else:
                    # Compatibility for isolated/older callers without pinned
                    # settings. Production never waits for in-flight responses.
                    old_engine=self.engine
                    with self.reload_gate.replace():commit()
                    if old_engine and old_engine is not self.engine:self.retire_engine(old_engine)
                return {'catalog_pending':catalog_pending,'catalog_changed':catalog_changed}
            finally:
                if receipt:self.catalog_cache.restore(receipt)
                pending_state=ROOT/'support/Gateway-State.live-tmp'
                if pending_state.exists():pending_state.unlink()
                if candidate:candidate.stop()

    def refresh_catalog(self):
        with self.reload_lock:
            self.catalog_cache.publish(self.relay.catalog)
        return {'catalog_pending':False,'ui_reload':True}

    def retire_engine(self,engine):
        try:engine.stop()
        except (OSError,ValueError,subprocess.SubprocessError):self.retired_engines.append(engine)

    def stop(self):
        with self.reload_lock:self._stop()

    def _stop(self):
        for name in ('gateway','relay'):
            server = getattr(self,name,None)
            if server:
                if server in getattr(self,'started_servers',[]): server.shutdown()
                server.server_close()
        if getattr(self,'settings_generations',None):self.settings_generations.close()
        elif getattr(self,'engine',None): self.engine.stop()
        for engine in getattr(self,'retired_engines',[]):engine.stop()
        if getattr(self,'catalog_cache',None):self.catalog_cache.restore_initial()

if __name__ == '__main__':
    service = Service().start()
    try: threading.Event().wait()
    finally: service.stop()
