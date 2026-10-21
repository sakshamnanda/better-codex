"""Bounded 429 retries with a fake clock and transport; no network or credentials."""
from pathlib import Path
from types import SimpleNamespace
from email.utils import formatdate
import io
import sys
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src/gateway'))
import provider_relay as relay

prepared = SimpleNamespace(url='https://provider.invalid/responses', body=b'{}',
    headers={'Authorization': 'Bearer dummy-provider'})
original = (relay.urllib.request.build_opener, relay.time.monotonic, relay.time.time,
    relay.time.sleep, relay.random.uniform)

def check(statuses, headers=None, expected_attempts=1, expected_waits=(), elapsed=0):
    clock = [0]
    attempts, waits, errors = [], [], []
    result = io.BytesIO(b'fixture stream')
    class Opener:
        def open(self, request, timeout):
            assert request.data == prepared.body
            assert request.get_header('Authorization') == 'Bearer dummy-provider'
            assert 0 < timeout <= relay.PROVIDER_TIMEOUT
            attempts.append(timeout)
            clock[0] += elapsed
            status = statuses[len(attempts) - 1]
            if status != 200:
                error = urllib.error.HTTPError(prepared.url, status, 'fixture', headers or {}, io.BytesIO(b'private fixture'))
                errors.append(error)
                raise error
            return result
    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds
    relay.urllib.request.build_opener = lambda *args: Opener()
    relay.time.monotonic = lambda: clock[0]
    relay.time.time = lambda: 1700000000 + clock[0]
    relay.time.sleep = sleep
    relay.random.uniform = lambda *args: 0
    event = {}
    try:
        assert relay.open_provider(prepared, event) is result
        assert statuses[len(attempts) - 1] == 200
    except urllib.error.HTTPError as error:
        assert statuses[len(attempts) - 1] != 200
        # The final error body remains readable for sanitized diagnostics.
        assert error.read() == b'private fixture'
    assert len(attempts) == expected_attempts, attempts
    assert waits == list(expected_waits), waits
    assert event['provider_attempts'] == expected_attempts
    assert event.get('provider_rate_limit_responses', 0) == statuses[:len(attempts)].count(429)
    assert all(error.fp.closed for error in errors[:-1])
    return attempts

try:
    check([200])
    check([429, 200], {'Retry-After': '3'}, 2, [3])
    check([429, 200], {'Retry-After': formatdate(1700000005, usegmt=True)}, 2, [5])
    check([429, 200], {'Retry-After': 'invalid'}, 2, [2])
    check([429, 200], {'Retry-After': '0'}, 2, [0])
    check([429, 429, 200], expected_attempts=3, expected_waits=[2, 4])
    check([429] * 4, expected_attempts=4, expected_waits=[2, 4, 8])
    check([429] * 3, {'Retry-After': '20'}, 2, [20])
    check([429], {'Retry-After': '31'})
    check([429], elapsed=119)
    budgets = check([429, 200], expected_attempts=2, expected_waits=[2], elapsed=5)
    assert budgets == [120, 113], budgets
    for status in (400, 401, 403, 408, 500, 502, 504):
        check([status])
    check([429, 401], expected_attempts=2, expected_waits=[2])
finally:
    (relay.urllib.request.build_opener, relay.time.monotonic, relay.time.time,
        relay.time.sleep, relay.random.uniform) = original
print('PASS: only pre-stream 429s retry; Retry-After, backoff, four-attempt cap, wait budget, timeout budget and diagnostics verified.')
