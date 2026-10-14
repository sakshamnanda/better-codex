"""Independent native/external service; no test GUI or live credential-file access."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import json
import os
import secrets
import threading
import runtime_mixed as mixed
from provider_registry import PROVIDERS

ROOT = Path(__file__).resolve().parent

class Service:
    def start(self):
        self.started_servers = []
        real = mixed.external_adapter
        self.engine = None
        if any(provider['adapter'] == 'opencode' for provider in PROVIDERS.values()):
            self.engine = real.OpenCodeEngine(real.key_supplier)
            self.engine.start(caller_tools=True)
        catalog = json.loads((ROOT / 'models.json').read_text())
        manifest = json.loads((ROOT / 'Deployment.json').read_text())
        self.relay = ThreadingHTTPServer(('127.0.0.1',0),real.RealGateway)
        self.relay.daemon_threads = True
        self.relay.prefix = '/relay_' + secrets.token_urlsafe(32)
        self.relay.token = mixed.DUMMY
        self.relay.catalog = catalog
        self.relay.opencode_engine = self.engine
        self.gateway = ThreadingHTTPServer(('127.0.0.1',0),mixed.MixedGateway)
        self.gateway.daemon_threads = True
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

    def stop(self):
        for name in ('gateway','relay'):
            server = getattr(self,name,None)
            if server:
                if server in getattr(self,'started_servers',[]): server.shutdown()
                server.server_close()
        if getattr(self,'engine',None): self.engine.stop()

if __name__ == '__main__':
    service = Service().start()
    try: threading.Event().wait()
    finally: service.stop()
