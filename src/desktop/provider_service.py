"""Independent native/external service; no test GUI or live credential-file access."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import json
import os
import secrets
import threading
import copy
import subprocess
import runtime_mixed as mixed
from provider_registry import PROVIDERS
import provider_registry
from model_profiles import load_profiles
from live_settings import ReloadGate,verify_generation

ROOT = Path(__file__).resolve().parent

class Service:
    def start(self):
        self.started_servers = []
        self.retired_engines=[]
        self.reload_lock=threading.Lock()
        self.reload_gate=ReloadGate()
        self.current=ROOT
        self.catalog_pending=False
        real = mixed.external_adapter
        self.engine = None
        if any(provider['adapter'] == 'opencode' for provider in PROVIDERS.values()):
            self.engine = real.OpenCodeEngine(real.key_supplier)
            self.engine.start(caller_tools=True)
        catalog = json.loads((ROOT / 'models.json').read_text())
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
        self.gateway.capability = secrets.token_urlsafe(32)
        self.gateway.native_models = set(manifest['native_models'])
        self.gateway.external_models = [model for model in catalog['models'] if model['slug'] in mixed.EXTERNAL]
        self.gateway.external_url = f'http://127.0.0.1:{self.relay.server_port}{self.relay.prefix}/backend-api/codex/responses'
        for server in (self.relay,self.gateway):
            threading.Thread(target=server.serve_forever,daemon=True).start()
            self.started_servers.append(server)
        self.base_url = f'http://127.0.0.1:{self.gateway.server_port}/g/{self.gateway.capability}/backend-api/codex'
        (ROOT / 'support/Gateway-State.json').write_text(json.dumps({'helper_pid':os.getpid(),'opencode_pid':self.engine.process.pid if self.engine else None,'base_url':self.base_url,'ready':True}))
        print('Standalone provider service ready; installed configuration untouched until explicit launch.',flush=True)
        return self

    def apply_settings(self,target):
        """Settings only; no app/backend restart, request cancellation or code swap."""
        with self.reload_lock:
            target=verify_generation(ROOT,target)
            if target==self.current:return {'catalog_pending':self.catalog_pending}
            providers,models,routes=provider_registry.load_registry(target)
            settings,profiles=load_profiles(target)
            catalog=json.loads((target/'models.json').read_text())
            current_catalog=json.loads((ROOT/'models.json').read_text())
            catalog_pending=catalog!=current_catalog
            if catalog_pending:
                # Keep the runtime and the cached native controls in agreement.
                # Routes for new models and changed limits/efforts remain pending;
                # keys, endpoints, labels and valid existing defaults can change.
                models=copy.deepcopy(provider_registry.MODELS)
                routes={mid:(entry[0],providers[entry[0]]['endpoint'],entry[2],entry[3])
                    for mid,entry in provider_registry.ROUTES.items()}
                for pid,p in providers.items():
                    p['models']={mid:{k:v for k,v in model.items() if k not in {'provider','metadata'}}
                        for mid,model in models.items() if model['provider']==pid}
                    if p['default_model'] not in p['models']:p['default_model']=provider_registry.PROVIDERS[pid]['default_model']
                catalog=current_catalog
            # Registry dicts are imported by reference. The outer request gate
            # drains every native/external request before their atomic update.
            # The inner relay remains private and completes inside that gate.
            real=mixed.external_adapter
            candidate=None
            opencode_changed=providers.get('opencode')!=provider_registry.PROVIDERS.get('opencode') or {
                mid:model for mid,model in models.items() if model['provider']=='opencode'}!={
                mid:model for mid,model in provider_registry.MODELS.items() if model['provider']=='opencode'}
            def credentials(folder):
                keys=folder/'gateway/keys'
                index=json.loads((keys/'Profiles.json').read_text()) if (keys/'Profiles.json').exists() else {}
                return {path.name:path.read_bytes() for path in keys.glob('opencode*.dpapi')}|{
                    'profiles':json.dumps(index.get('providers',{}).get('opencode'),sort_keys=True).encode()}
            opencode_changed=opencode_changed or credentials(target)!=credentials(self.current)
            try:
                if opencode_changed and 'opencode' in providers:
                    # Prepare and validate a replacement inference engine while
                    # the old one continues serving. Never mutate its files.
                    def candidate_key(pid):
                        ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
                        result=subprocess.run([str(ps),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'gateway/Provider-Credentials.ps1'),
                            '-Mode','Token','-Provider',pid,'-Storage',str(target/'gateway')],capture_output=True,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
                        if result.returncode:raise ValueError('Selected OpenCode credential could not be loaded; running setup retained.')
                        return result.stdout
                    candidate=real.OpenCodeEngine(candidate_key,root=target,registry=(providers,models))
                    candidate.start(caller_tools=True)
                state_path=ROOT/'support/Gateway-State.json'
                pending_state=state_path.with_suffix('.live-tmp')
                if state_path.exists():
                    state=json.loads(state_path.read_text())
                    if state.get('helper_pid')!=os.getpid():raise ValueError('Live helper ownership could not be verified.')
                    active_engine=candidate or self.engine
                    state.update(opencode_pid=active_engine.process.pid if active_engine else None,
                        settings_deployment=target.name,catalog_refresh_pending=catalog_pending)
                    pending_state.write_text(json.dumps(state))
                with self.reload_gate.replace():
                    if pending_state.exists():pending_state.replace(state_path)
                    old_engine=self.engine
                    provider_registry.PROVIDERS.clear();provider_registry.PROVIDERS.update(providers)
                    provider_registry.MODELS.clear();provider_registry.MODELS.update(models)
                    provider_registry.ROUTES.clear();provider_registry.ROUTES.update(routes)
                    mixed.EXTERNAL.clear();mixed.EXTERNAL.update(routes)
                    mixed.PROFILE_SETTINGS.clear();mixed.PROFILE_SETTINGS.update(settings)
                    mixed.PROFILES.clear();mixed.PROFILES.update(profiles)
                    real.KEY_STORAGE=target/'gateway'
                    self.relay.catalog=catalog
                    self.gateway.external_models=[m for m in catalog['models'] if m['slug'] in routes]
                    if candidate:self.engine=candidate;self.relay.opencode_engine=candidate
                    self.current=target;self.catalog_pending=catalog_pending
                    candidate=None
                if old_engine is not self.engine:
                    try:old_engine.stop()
                    except (OSError,ValueError,subprocess.SubprocessError):self.retired_engines.append(old_engine)
                return {'catalog_pending':catalog_pending}
            finally:
                pending_state=ROOT/'support/Gateway-State.live-tmp'
                if pending_state.exists():pending_state.unlink()
                if candidate:candidate.stop()

    def stop(self):
        with self.reload_lock:self._stop()

    def _stop(self):
        for name in ('gateway','relay'):
            server = getattr(self,name,None)
            if server:
                if server in getattr(self,'started_servers',[]): server.shutdown()
                server.server_close()
        if getattr(self,'engine',None): self.engine.stop()
        for engine in getattr(self,'retired_engines',[]):engine.stop()

if __name__ == '__main__':
    service = Service().start()
    try: threading.Event().wait()
    finally: service.stop()
