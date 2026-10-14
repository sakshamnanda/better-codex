"""Offline privacy and HTTP-error handling checks; no inference or credentials."""
from pathlib import Path
import io
import json
import sys
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src/gateway'))
import provider_relay as relay

private = 'PRIVATE_FIXTURE_VALUE_993abc'
body = json.dumps({'error': {'code': 'context_length_exceeded', 'param': 'input',
    'message': 'Maximum context length exceeded: 806746 tokens, limit 200000 tokens. ' + private,
    'details': [{'error': {'code': 'vendor_restrictions_unavailable', 'message': 'No eligible vendor. ' + private}}],
    'request': {'message': private}, 'account_id': private}}).encode()
diagnostic = relay.provider_error_diagnostic(body)
assert diagnostic['codes'] == ['context_length_exceeded', 'vendor_restrictions_unavailable']
assert diagnostic['parameters'] == ['input']
assert diagnostic['size_counts'] == [200000, 806746]
assert private not in json.dumps(diagnostic)
assert relay.provider_error_diagnostic(b'x' * 65537) == {'body_truncated': True}
assert relay.provider_error_diagnostic(b'<html>private</html>') == {'body_truncated': False}
assert relay.provider_error_diagnostic(json.dumps({'error': {'code': private, 'param': private,
    'message': private, 'data': {'error': {'code': 'context_length_exceeded'}}}}).encode())['codes'] == []
for malformed in (None, [], {'error': {'code': [], 'param': {}, 'message': None}}):
    relay.provider_error_diagnostic(json.dumps(malformed).encode())

# Exercise the actual relay exception branch, including safe outward messaging.
class FakeRequest:
    path = '/fixture/backend-api/codex/responses'
    payload = json.dumps({'model':'zai/glm-5.3-flash','input':[{'role':'user','content':'fixture'}],'tools':[]}).encode()
    headers = {'Content-Length': str(len(payload)), 'Host':'127.0.0.1:12345',
               'Authorization':'Bearer dummy-native-fixture','Content-Type':'application/json'}
    rfile = io.BytesIO(payload)
    server = type('Server', (), {'prefix':'/fixture','server_port':12345,
        'catalog':{'models':[{'slug':'zai/glm-5.3-flash'}]}})()
    allowed = lambda self: True
    fail = lambda *args: (_ for _ in ()).throw(AssertionError('Unexpected rejection'))
    def error_response(self, status, message, streaming=False, code='provider_test_error'):
        self.observed = (status, message, streaming, code)

def rejected_provider(*args):
    raise urllib.error.HTTPError('https://provider.invalid',400,'fixture',{},io.BytesIO(body))

original_key, original_open, original_record, original_save = relay.key_supplier, relay.open_provider, relay.record, relay.save_diagnostics
events = []
try:
    relay.key_supplier = lambda provider: 'dummy-provider-fixture'
    relay.open_provider = rejected_provider
    relay.record = events.append
    relay.save_diagnostics = lambda: None
    fake = FakeRequest()
    relay.RealGateway.do_POST(fake)
    assert fake.observed == (400, 'This chat exceeds the selected provider context window. Compact it with a model that can read the current history, then switch back.', False, 'context_length_exceeded'), fake.observed
    response=json.dumps({'error': {'code':fake.observed[3], 'message':fake.observed[1]}}).encode()
    assert relay.public_relay_detail(response) == ('context_length_exceeded',fake.observed[1])
    assert relay.public_relay_error(response) == fake.observed[1]
    assert relay.public_relay_detail(json.dumps({'error':{'code':private,'message':fake.observed[1]}}).encode()) is None
    assert events[0]['http_status'] == 400 and events[0]['provider_error'] == diagnostic
    assert private not in json.dumps(events)
finally:
    relay.key_supplier, relay.open_provider, relay.record, relay.save_diagnostics = original_key, original_open, original_record, original_save

# The desktop-facing outer relay must preserve the same machine-readable code.
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'src/desktop'))
import runtime_mixed as mixed
capability='fixture_capability_12345678901234567890'
class OuterRequest:
    server=type('Server',(),{'capability':capability,'server_port':12345,'native_models':set(),
        'external_url':'http://fixture.invalid/responses'})()
    path='/g/'+capability+'/backend-api/codex/responses'
    headers=FakeRequest.headers
    rfile=io.BytesIO(FakeRequest.payload)
    core=mixed.MixedGateway.core
    def fail(self,status,message,code='replica_gateway_error'):
        self.observed=(status,message,code)

def outer_rejected(*args):
    raise urllib.error.HTTPError('http://fixture.invalid/responses',400,'fixture',{},io.BytesIO(response))
old_open, old_record=mixed.open_upstream,mixed.record
try:
    mixed.open_upstream=outer_rejected;mixed.record=lambda event: None
    outer=OuterRequest();mixed.MixedGateway.do_POST(outer)
    assert outer.observed == (400,fake.observed[1],'context_length_exceeded'), outer.observed
finally:
    mixed.open_upstream,mixed.record=old_open,old_record
print('PASS: bounded diagnostics exclude private values; both relays preserve the context error code and safe recovery message.')
