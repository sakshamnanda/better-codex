"""Cached/query-bearing asset regression; no real UI, auth or network."""
from pathlib import Path
import base64
import hashlib
import importlib.util
import json
import uuid
root = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('overlay',root / 'src/desktop/signed_overlay.py')
overlay = importlib.util.module_from_spec(spec); spec.loader.exec_module(overlay)
original = 'original static source'
updated = 'updated static source'
url = 'app://-/assets/picker.js?cached=1'
class Cached(overlay.PrivatePipe):
    def __init__(self): self.events = []; self.calls = []; self.disabled = False; self.bypass = False
    def call(self,method,params=None,session=None,timeout=20):
        params = params or {}; self.calls.append(method)
        if method == 'Target.getTargets': return {'targetInfos':[{'type':'page','url':'app://-/index.html','targetId':'owned'}]}
        if method == 'Target.attachToTarget': return {'sessionId':'session'}
        if method == 'Debugger.enable': self.events.append({'method':'Debugger.scriptParsed','sessionId':'session','params':{'url':url,'scriptId':'script'}})
        if method == 'Debugger.getScriptSource': return {'scriptSource':original}
        if method == 'Network.setCacheDisabled': self.disabled = params['cacheDisabled']
        if method == 'Network.setBypassServiceWorker': self.bypass = params['bypass']
        if method == 'Fetch.enable': assert params['patterns'][0]['urlPattern'] == 'app://-/assets/picker.js*'
        if method == 'Page.reload':
            assert self.disabled and self.bypass
            self.events.append({'method':'Fetch.requestPaused','sessionId':'session','params':{'requestId':'request','request':{'url':'app://-/assets/picker.js?cached=2'},'responseStatusCode':200,'responseHeaders':[]}})
        if method == 'Fetch.getResponseBody': return {'body':original,'base64Encoded':False}
        if method == 'Fetch.fulfillRequest': assert base64.b64decode(params['body']).decode() == updated
        return {}
scratch = root / '.local/test-work' / ('overlay-cache-' + uuid.uuid4().hex[:8]); scratch.mkdir(parents=True)
pipe = Cached()
assert pipe.patch('picker.js',hashlib.sha256(original.encode()).hexdigest(),updated,scratch / 'Check.json')
assert not pipe.disabled and not pipe.bypass
assert json.loads((scratch / 'Check.json').read_text())['patch_applied']
print('PASS: cached resources require temporary cache/service-worker bypass; actual resource URL/query matches; source hash checked; bypass removed after patch.')
