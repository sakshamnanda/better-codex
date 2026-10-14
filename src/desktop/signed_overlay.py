"""Version-checked renderer customization over private inherited pipes.

No debugging TCP port, file replacement, security-toggle change, DOM inspection,
or mouse/keyboard automation. Provider keys entered in our settings dialog pass
only in memory to the local encryption handler. Only our own child is attached.
"""
from pathlib import Path
import hashlib
import base64
import json
import msvcrt
import os
import queue
import subprocess
import threading
import time
from urllib.parse import urlsplit


class PrivatePipe:
    def __init__(self):
        self.child_read, self.parent_write = os.pipe()
        self.parent_read, self.child_write = os.pipe()
        self.messages = queue.Queue()
        self.events = []
        self.identifier = 0
        self.lock = threading.Lock()
        self.rpc_lock = threading.RLock()
        self.trusted_contexts = set()
        self.settings_stop = threading.Event()

    def launch(self, command, **kwargs):
        handles = [msvcrt.get_osfhandle(fd) for fd in (self.child_read,self.child_write)]
        for handle in handles: os.set_handle_inheritable(handle,True)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 1
        startup.lpAttributeList = {'handle_list':handles}
        try:
            process = subprocess.Popen([command[0], '--remote-debugging-pipe', '--remote-debugging-io-pipes=' + ','.join(map(str,handles)), *command[1:]], startupinfo=startup, close_fds=True, **kwargs)
        finally:
            for handle in handles: os.set_handle_inheritable(handle,False)
            os.close(self.child_read)
            os.close(self.child_write)
        self.process = process
        threading.Thread(target=self.read,daemon=True).start()
        return process

    def read(self):
        buffer = b''
        try:
            while data := os.read(self.parent_read,65536):
                buffer += data
                if len(buffer) > 32 * 1024 * 1024: raise ValueError('Private protocol frame too large')
                while b'\0' in buffer:
                    frame,buffer = buffer.split(b'\0',1)
                    self.messages.put(json.loads(frame))
        except (OSError,ValueError): pass
        finally: self.messages.put({'pipe_closed':True})

    def call(self,method,params=None,session=None,timeout=20):
        with self.rpc_lock:
            return self._call(method,params,session,timeout)

    def _call(self,method,params=None,session=None,timeout=20):
        self.identifier += 1
        value = {'id':self.identifier,'method':method,'params':params or {}}
        if session: value['sessionId'] = session
        encoded = memoryview((json.dumps(value) + '\0').encode())
        with self.lock:
            while encoded:
                written = os.write(self.parent_write,encoded)
                encoded = encoded[written:]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try: reply = self.messages.get(timeout=min(1,max(0.01,deadline-time.monotonic())))
            except queue.Empty: continue
            if reply.get('pipe_closed'): raise RuntimeError('Private renderer pipe closed')
            if reply.get('id') == value['id']:
                if 'error' in reply: raise RuntimeError('Private renderer command rejected: ' + method + ': ' + str(reply['error'].get('message',''))[:240])
                return reply.get('result',{})
            # Keep only the static-code events needed here, never network
            # request/response events containing account or conversation data.
            if reply.get('method') in {'Debugger.scriptParsed','Fetch.requestPaused','Runtime.executionContextCreated','Runtime.executionContextDestroyed','Runtime.executionContextsCleared','Runtime.bindingCalled'}: self.events.append(reply)
        raise TimeoutError('Private renderer command timed out: ' + method)

    def patch(self,filename,original_hash,new_source,status_path,additional_assets=None,settings_handler=None):
        status = {'signed_files_replaced':False,'debug_tcp_port_opened':False,'private_inherited_pipe':True,'source_hash_verified':False,'patch_applied':False}
        def save(): Path(status_path).write_text(json.dumps(status,indent=2))
        save()
        deadline = time.monotonic() + 45
        session = None
        try:
            while time.monotonic() < deadline:
                targets = self.call('Target.getTargets')['targetInfos']
                candidates = [target for target in targets if target.get('type') == 'page' and (target.get('url','').startswith('app://-/') or target.get('url','').startswith('app://-'))]
                if len(candidates) == 1:
                    session = self.call('Target.attachToTarget',{'targetId':candidates[0]['targetId'],'flatten':True})['sessionId']
                    break
                time.sleep(0.2)
            if not session: raise RuntimeError('Unique owned app renderer not ready')
            self.call('Debugger.enable',session=session)
            script = None
            script_event = None
            while time.monotonic() < deadline:
                script_event = next((event['params'] for event in self.events if event.get('sessionId') == session and event.get('method') == 'Debugger.scriptParsed' and urlsplit(event.get('params',{}).get('url','')).path.endswith('/' + filename)),None)
                if script_event:
                    script = script_event['scriptId']
                    break
                self.call('Runtime.getIsolateId',session=session)
                time.sleep(0.1)
            if not script: raise RuntimeError('Exact provider picker bundle not loaded')
            original = self.call('Debugger.getScriptSource',{'scriptId':script},session=session)['scriptSource']
            if hashlib.sha256(original.encode()).hexdigest() != original_hash: raise RuntimeError('Renderer bundle changed; customization refused')
            status['source_hash_verified'] = True
            asset = urlsplit(script_event['url'])
            status['asset_scheme'] = asset.scheme
            # ES module LiveEdit may be unavailable. Replace only the exact
            # verified static resource response during our child's startup.
            self.call('Debugger.disable',session=session)
            if settings_handler:
                self.call('Runtime.enable',session=session)
                self.call('Runtime.addBinding',{'name':'betterCodexSettings'},session=session)
            self.call('Network.enable',session=session)
            self.call('Network.setCacheDisabled',{'cacheDisabled':True},session=session)
            self.call('Network.setBypassServiceWorker',{'bypass':True},session=session)
            status['cache_and_service_worker_bypassed_during_patch'] = True
            # Use the actual parsed resource path, allowing its query string;
            # subsequent response-body hash verification remains mandatory.
            pattern = script_event['url'].split('?',1)[0] + '*'
            patterns = [{'urlPattern':pattern,'requestStage':'Response'}]
            assets = {filename:(original_hash,new_source)}
            for name, original, updated in additional_assets or []:
                assets[name] = (original, updated)
                patterns.append({'urlPattern':script_event['url'].split('?',1)[0].rsplit('/',1)[0] + '/' + name + '*','requestStage':'Response'})
            self.call('Fetch.enable',{'patterns':patterns},session=session)
            self.call('Page.reload',{'ignoreCache':True},session=session)
            request = None
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                request = next((event['params'] for event in self.events if event.get('sessionId') == session and event.get('method') == 'Fetch.requestPaused' and urlsplit(event.get('params',{}).get('request',{}).get('url','')).path == asset.path),None)
                if request: break
                self.call('Runtime.getIsolateId',session=session)
                time.sleep(0.1)
            if not request: raise RuntimeError('Exact static resource interception unavailable')
            body = self.call('Fetch.getResponseBody',{'requestId':request['requestId']},session=session)
            original_bytes = base64.b64decode(body['body']) if body.get('base64Encoded') else body['body'].encode()
            if hashlib.sha256(original_bytes).hexdigest() != original_hash: raise RuntimeError('Static response changed; customization refused')
            response_headers = [header for header in request.get('responseHeaders',[]) if header['name'].lower() not in {'content-length','content-encoding'}]
            self.call('Fetch.fulfillRequest',{'requestId':request['requestId'],'responseCode':request.get('responseStatusCode',200),'responseHeaders':response_headers,'body':base64.b64encode(new_source.encode()).decode()},session=session)
            # Start the lazy settings import while cache bypass is still active.
            # Its verified static response is fulfilled by the event loop below.
            for name, _, _ in additional_assets or []:
                asset_url = script_event['url'].split('?',1)[0].rsplit('/',1)[0] + '/' + name
                self.call('Runtime.evaluate',{'expression':'import(' + json.dumps(asset_url) + ').catch(()=>undefined)', 'awaitPromise':False},session=session)
            if not settings_handler: self.call('Fetch.disable',session=session)
            self.call('Network.setCacheDisabled',{'cacheDisabled':False},session=session)
            self.call('Network.setBypassServiceWorker',{'bypass':False},session=session)
            self.call('Network.disable',session=session)
            status['method'] = 'exact_static_response_over_private_pipe'
            status['patch_applied'] = True
            self.call('Debugger.disable',session=session)
            if settings_handler:
                self.settings_session = session
                self.settings_handler = settings_handler
                self.settings_assets = assets
                # The initial asset was fulfilled; retain only new context events.
                self.events = [event for event in self.events if event.get('method','').startswith('Runtime.') or
                    (event.get('method') == 'Fetch.requestPaused' and event.get('params',{}).get('requestId') != request['requestId'])]
                threading.Thread(target=self.settings_loop,daemon=True).start()
            else: self.call('Target.detachFromTarget',{'sessionId':session})
            save()
            print('Signed replica: provider UI customized in memory over a private pipe; packaged files untouched.',flush=True)
        except (OSError,RuntimeError,TimeoutError,KeyError,ValueError) as error:
            status['failure_type'] = type(error).__name__
            status['failure_stage'] = str(error)
            save()
            print('Signed renderer customization did not pass; original UI/files preserved.',flush=True)
            if session:
                try:
                    self.call('Fetch.disable',session=session,timeout=2)
                    self.call('Network.setCacheDisabled',{'cacheDisabled':False},session=session,timeout=2)
                    self.call('Network.setBypassServiceWorker',{'bypass':False},session=session,timeout=2)
                    self.call('Network.disable',session=session,timeout=2)
                    self.call('Debugger.disable',session=session,timeout=2)
                    self.call('Target.detachFromTarget',{'sessionId':session},timeout=2)
                except (OSError,RuntimeError,TimeoutError): pass
            return False
        return True

    def settings_event(self, event):
        """Only the owned default app context can request bounded local settings."""
        if event.get('sessionId') != self.settings_session: return
        params = event.get('params', {})
        method = event.get('method')
        if method == 'Runtime.executionContextCreated':
            context = params.get('context', {})
            origin = urlsplit(context.get('origin', ''))
            if context.get('auxData', {}).get('isDefault') is True and origin.scheme == 'app' and origin.netloc == '-':
                self.trusted_contexts.add(context['id'])
        elif method == 'Runtime.executionContextDestroyed':
            self.trusted_contexts.discard(params.get('executionContextId'))
        elif method == 'Runtime.executionContextsCleared': self.trusted_contexts.clear()
        elif method == 'Fetch.requestPaused':
            name = urlsplit(params.get('request', {}).get('url','')).path.rsplit('/',1)[-1]
            entry = self.settings_assets.get(name)
            if not entry:
                self.call('Fetch.continueRequest',{'requestId':params['requestId']},session=self.settings_session)
                return
            body = self.call('Fetch.getResponseBody',{'requestId':params['requestId']},session=self.settings_session)
            raw = base64.b64decode(body['body']) if body.get('base64Encoded') else body['body'].encode()
            if hashlib.sha256(raw).hexdigest() != entry[0]:
                self.call('Fetch.continueRequest',{'requestId':params['requestId']},session=self.settings_session)
                return
            headers = [h for h in params.get('responseHeaders',[]) if h['name'].lower() not in {'content-length','content-encoding'}]
            self.call('Fetch.fulfillRequest',{'requestId':params['requestId'],'responseCode':params.get('responseStatusCode',200),
                'responseHeaders':headers,'body':base64.b64encode(entry[1].encode()).decode()},session=self.settings_session)
        elif method == 'Runtime.bindingCalled':
            if params.get('name') != 'betterCodexSettings' or params.get('executionContextId') not in self.trusted_contexts: return
            payload = params.get('payload','')
            if not isinstance(payload,str) or len(payload.encode()) > 128*1024: return
            request_id = None
            try:
                request = json.loads(payload)
                request_id = request.get('id')
                if type(request_id) is not int or not 1 <= request_id <= 1_000_000 or set(request) != {'id','request'}: return
                response = {'result':self.settings_handler(request['request'])}
            except ValueError as error:
                response = {'error':str(error)}
            except Exception:
                response = {'error':'Could not save local settings. The previous launch setup was retained.'}
            finally:
                params['payload'] = None
                payload = None
                request = None
            if request_id is not None:
                expression = 'globalThis.gatewaySettingsReply?.(' + json.dumps(request_id) + ',' + json.dumps(response).replace('<','\\u003c') + ')'
                self.call('Runtime.evaluate',{'expression':expression,'contextId':params['executionContextId']},session=self.settings_session)

    def settings_loop(self):
        try:
            while not self.settings_stop.is_set():
                if self.events: event = self.events.pop(0)
                else:
                    try:
                        with self.rpc_lock: event = self.messages.get(timeout=0.25)
                    except queue.Empty: continue
                if event.get('pipe_closed'): break
                self.settings_event(event)
        except (OSError,RuntimeError,TimeoutError,KeyError,ValueError):
            print('Better Codex settings connection closed; running provider setup was retained.',flush=True)

    def close(self):
        self.settings_stop.set()
        for fd in (self.parent_read,self.parent_write):
            try: os.close(fd)
            except OSError: pass
