"""Offline privacy and HTTP-error handling checks; no inference or credentials."""
from pathlib import Path
import io
import http.client
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

def outer_rejected(*args, **kwargs):
    assert kwargs['timeout'] > relay.PROVIDER_TIMEOUT
    raise urllib.error.HTTPError('http://fixture.invalid/responses',400,'fixture',{},io.BytesIO(response))
old_open, old_record=mixed.open_upstream,mixed.record
try:
    mixed.open_upstream=outer_rejected;mixed.record=lambda event: None
    outer=OuterRequest();mixed.MixedGateway.do_POST(outer)
    assert outer.observed == (400,fake.observed[1],'context_length_exceeded'), outer.observed
finally:
    mixed.open_upstream,mixed.record=old_open,old_record

# A provider 429 must retain its safe message without triggering desktop retries.
attempts = []
events = []
try:
    def rate_limited_provider(*args):
        attempts.append(True)
        raise urllib.error.HTTPError('https://provider.invalid', 429, 'fixture', {},
            io.BytesIO(json.dumps({'error': {'message': private}}).encode()))
    relay.key_supplier = lambda provider: 'dummy-provider-fixture'
    relay.open_provider = rate_limited_provider
    relay.record = events.append
    relay.save_diagnostics = lambda: None
    fake = FakeRequest(); fake.rfile = io.BytesIO(fake.payload)
    relay.RealGateway.do_POST(fake)
    assert fake.observed == (429, 'Provider rate limit reached', False, 'provider_test_error')
    assert len(attempts) == 1 and events[0]['http_status'] == 429
    response = json.dumps({'error': {'code': fake.observed[3], 'message': fake.observed[1]}}).encode()
    assert relay.public_relay_detail(response) == ('provider_test_error', 'Provider rate limit reached')
    def outer_rate_limited(*args, **kwargs):
        raise urllib.error.HTTPError('http://fixture.invalid', 429, 'fixture', {}, io.BytesIO(response))
    mixed.open_upstream = outer_rate_limited; mixed.record = lambda event: None
    outer = OuterRequest(); outer.rfile = io.BytesIO(FakeRequest.payload)
    mixed.MixedGateway.do_POST(outer)
    assert outer.observed == (400, 'Provider rate limit reached', 'provider_test_error')
    assert private not in json.dumps(events) and private not in response.decode()
    mixed.MixedGateway.request_failure(outer, 429, 'Native fixture error', False, {'provider': 'openai'})
    assert outer.observed == (429, 'Native fixture error', 'replica_gateway_error')
finally:
    relay.key_supplier, relay.open_provider, relay.record, relay.save_diagnostics = original_key, original_open, original_record, original_save
    mixed.open_upstream, mixed.record = old_open, old_record

# The outer hop must leave time for the inner timeout's sanitized response.
for failure, status, category in ((TimeoutError(private), 504, 'timeout'),
        (urllib.error.URLError(TimeoutError(private)), 504, 'timeout'),
        (urllib.error.URLError(private), 502, 'transport'),
        (http.client.IncompleteRead(private.encode(), 100), 502, 'http_protocol'),
        (http.client.RemoteDisconnected(private), 502, 'http_protocol'),
        (ConnectionResetError(private), 502, 'transport')):
    def failed_provider(*args): raise failure
    events = []
    try:
        relay.key_supplier = lambda provider: 'dummy-provider-fixture'
        relay.open_provider = failed_provider
        relay.record = events.append
        relay.save_diagnostics = lambda: None
        fake = FakeRequest(); fake.rfile = io.BytesIO(fake.payload)
        relay.RealGateway.do_POST(fake)
        assert fake.observed[0] == status and events[0]['connection_failure'] == category
        assert events[0]['elapsed_seconds'] >= 0
        assert events[0]['provider_stage'] == 'response_headers'
        response = json.dumps({'error': {'code': fake.observed[3], 'message': fake.observed[1]}}).encode()
        assert relay.public_relay_detail(response) == (fake.observed[3], fake.observed[1])
        assert private not in json.dumps(events) and private not in response.decode()
        def outer_timeout(*args, **kwargs):
            assert kwargs['timeout'] > relay.PROVIDER_TIMEOUT == 120
            raise urllib.error.HTTPError('http://fixture.invalid', status, 'fixture', {}, io.BytesIO(response))
        mixed.open_upstream = outer_timeout; mixed.record = lambda event: None
        outer = OuterRequest(); outer.rfile = io.BytesIO(FakeRequest.payload)
        mixed.MixedGateway.do_POST(outer)
        assert outer.observed == (400, fake.observed[1], fake.observed[3])
    finally:
        relay.key_supplier, relay.open_provider, relay.record, relay.save_diagnostics = original_key, original_open, original_record, original_save
        mixed.open_upstream, mixed.record = old_open, old_record

# A truncated Chat Completions stream must emit a bounded relay error.
class TruncatedReply:
    headers = type('Headers', (), {'get_content_type': lambda self: 'text/event-stream'})()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def readline(self, limit): raise http.client.IncompleteRead(private.encode(), 100)
try:
    relay.key_supplier = lambda provider: 'dummy-provider-fixture'
    relay.open_provider = lambda *args: TruncatedReply()
    events = []; relay.record = events.append; relay.save_diagnostics = lambda: None
    fake = FakeRequest()
    fake.wfile = io.BytesIO()
    fake.send_response = lambda *args: None
    fake.send_header = lambda *args: None
    fake.end_headers = lambda: None
    fake.payload = json.dumps({'model': 'z-ai/glm-5.3-flash-uncensored', 'input': [{'role':'user', 'content':'fixture'}], 'tools': []}).encode()
    fake.headers = {**fake.headers, 'Content-Length': str(len(fake.payload))}
    fake.rfile = io.BytesIO(fake.payload)
    fake.server = type('Server', (), {'prefix':'/fixture', 'server_port':12345,
        'catalog':{'models':[{'slug':'z-ai/glm-5.3-flash-uncensored'}]}})()
    relay.RealGateway.do_POST(fake)
    assert fake.observed[0] == 502 and fake.observed[2] is True
    assert events[0]['provider_stage'] == 'response_stream'
    assert events[0]['connection_failure'] == 'http_protocol'
    assert events[0]['failure_type'] == 'IncompleteRead'
    assert private not in json.dumps(events) and private not in fake.observed[1]
finally:
    relay.key_supplier, relay.open_provider, relay.record, relay.save_diagnostics = original_key, original_open, original_record, original_save

# Verify the actual socket budgets without opening a connection.
from types import SimpleNamespace
original_builder = relay.urllib.request.build_opener
budgets = []
class OfflineOpener:
    def open(self, request, timeout):
        budgets.append(timeout)
        return None
try:
    relay.urllib.request.build_opener = lambda *args: OfflineOpener()
    relay.open_provider(SimpleNamespace(url='https://provider.invalid/chat/completions', body=b'{}', headers={}))
    mixed.open_upstream('https://chatgpt.com/backend-api/codex/responses', {}, b'{}')
    mixed.open_upstream('http://127.0.0.1:12345/fixture', {}, b'{}', timeout=relay.PROVIDER_TIMEOUT + 30)
    assert budgets == [120, 120, 150], budgets
finally:
    relay.urllib.request.build_opener = original_builder

# Once SSE headers are sent, errors must reach the desktop as terminal events.
# Exercise the actual outer handler, preserving safe timeout text across hops.
safe_timeout = 'Provider response timed out; no automatic retry was made'
class StreamReply(io.BytesIO):
    status = 200
    headers = type('Headers', (), {'get_content_type': lambda self: 'text/event-stream'})()

class StreamingRequest(OuterRequest):
    def __init__(self):
        mixed.FAILED_EXTERNAL_STREAMS.clear()
        self.rfile = io.BytesIO(FakeRequest.payload)
        self.wfile = io.BytesIO()
        self.statuses = []
    def send_response(self, status): self.statuses.append(status)
    def send_header(self, *args): pass
    def end_headers(self): pass

created = 'data: ' + json.dumps({'type': 'response.created', 'response': {'output': []}}) + '\n\n'
failed = 'data: ' + json.dumps({'type': 'error', 'code': 'provider_test_error', 'message': safe_timeout}) + '\n\n'
for tail in (failed, '', 'data: broken-json\n\n', 'data: {'):
    attempts = []
    try:
        def stream_reply(*args, **kwargs):
            attempts.append(True)
            return StreamReply((created + tail).encode())
        mixed.open_upstream = stream_reply
        mixed.record = lambda event: None
        outer = StreamingRequest()
        mixed.MixedGateway.do_POST(outer)
        frames = [json.loads(line[6:]) for line in outer.wfile.getvalue().decode().splitlines() if line.startswith('data: ')]
        assert outer.statuses == [200] and len(attempts) == 1
        assert frames[-1]['type'] == 'error', frames
        assert not any(frame['type'] == 'response.completed' for frame in frames)
        if tail == failed: assert frames[-1]['message'] == safe_timeout
        assert private not in outer.wfile.getvalue().decode()
    finally:
        mixed.open_upstream, mixed.record = old_open, old_record

# Content-type validation happens before headers, so it cannot silently close.
try:
    reply = StreamReply(b'')
    reply.headers = type('Headers', (), {'get_content_type': lambda self: 'text/html'})()
    mixed.open_upstream = lambda *args, **kwargs: reply
    mixed.record = lambda event: None
    outer = StreamingRequest()
    mixed.MixedGateway.do_POST(outer)
    assert outer.observed[0] == 400 and outer.statuses == []
finally:
    mixed.open_upstream, mixed.record = old_open, old_record

# Socket timeout after headers must emit a safe failure, retaining partial text.
class TimedOutStream(StreamReply):
    def readline(self, limit):
        line = super().readline(limit)
        if not line: raise TimeoutError(private)
        return line
try:
    partial = 'data: ' + json.dumps({'type': 'response.output_text.delta', 'delta': 'Partial answer'}) + '\n\n'
    mixed.open_upstream = lambda *args, **kwargs: TimedOutStream((created + partial).encode())
    mixed.record = lambda event: None
    outer = StreamingRequest()
    mixed.MixedGateway.do_POST(outer)
    visible = outer.wfile.getvalue().decode()
    assert 'Partial answer' in visible and safe_timeout in visible and private not in visible
finally:
    mixed.open_upstream, mixed.record = old_open, old_record

# Completed responses and native HTTP behavior retain their original semantics.
try:
    done = 'data: ' + json.dumps({'type': 'response.completed', 'response': {'output': []}}) + '\n\n'
    mixed.open_upstream = lambda *args, **kwargs: StreamReply((created + done).encode())
    mixed.record = lambda event: None
    outer = StreamingRequest()
    mixed.MixedGateway.do_POST(outer)
    frames = [json.loads(line[6:]) for line in outer.wfile.getvalue().decode().splitlines() if line.startswith('data: ')]
    assert frames[-1]['type'] == 'response.completed' and not any(frame['type'] == 'error' for frame in frames)
    outer = OuterRequest()
    mixed.MixedGateway.request_failure(outer, 502, 'Native fixture error', False, {'provider': 'openai'})
    assert outer.observed == (502, 'Native fixture error', 'replica_gateway_error')
finally:
    mixed.open_upstream, mixed.record = old_open, old_record
print('PASS: bounded diagnostics exclude private values; both relays preserve the context error code and safe recovery message.')
