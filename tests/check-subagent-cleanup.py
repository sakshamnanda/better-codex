"""Owned-tree cleanup, native execution, local authentication and CLI isolation."""
from pathlib import Path
import copy
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/desktop'))
from subagent_lifecycle import manage, LifecycleServer
from signed_overlay import PrivatePipe

# Only the owned default renderer can forward the three native cleanup methods.
pipe = object.__new__(PrivatePipe)
pipe.trusted_contexts, pipe.settings_session = {42}, 'owned-renderer'
evaluations = []
def evaluate(method, params, **kwargs):
    assert method == 'Runtime.evaluate' and params['contextId'] == 42
    assert params['awaitPromise'] and params['returnByValue'] and kwargs['session'] == 'owned-renderer'
    evaluations.append(params['expression'])
    return {'result': {'value': {'data': [], 'nextCursor': None}}}
pipe.call = evaluate
assert pipe.subagent_request('thread/list', {'limit': 1})['data'] == []
for method in ('exec_command', 'thread/start'):
    try: pipe.subagent_request(method, {})
    except ValueError: pass
    else: raise AssertionError('Arbitrary renderer RPC accepted')
pipe.trusted_contexts = set()
try: pipe.subagent_request('thread/list', {})
except RuntimeError: pass
else: raise AssertionError('Untrusted renderer accepted')
assert len(evaluations) == 1

parent, child, grandchild, unrelated = [str(uuid.uuid4()) for _ in range(4)]
rows = {child: {'id': child, 'parentThreadId': parent},
        grandchild: {'id': grandchild, 'parentThreadId': child}}
rows[child].update(source={'subAgent': {'thread_spawn': {'agent_path': '/root/owned_worker'}}},
                   agentNickname='Owned worker', status={'type': 'idle'}, preview='PRIVATE_TRANSCRIPT_CANARY')
archived, calls = set(), []


def native(method, params):
    calls.append((method, copy.deepcopy(params)))
    if method == 'thread/list':
        assert params.get('ancestorThreadId') == parent or params.get('parentThreadId') in rows
        return {'data': [row for identifier, row in rows.items() if (identifier in archived) == params['archived']
                         and ('parentThreadId' not in params or row['parentThreadId'] == params['parentThreadId'])], 'nextCursor': None}
    identifier = params['threadId']
    assert identifier in rows
    if method == 'thread/archive': archived.add(identifier)
    elif method == 'thread/delete': del rows[identifier]
    else: raise AssertionError('Unexpected native operation')
    return {}


def request(action, target=None): return {'parent': parent, 'action': action, 'target': target}


def refused(value):
    before = copy.deepcopy(rows), archived.copy()
    try: manage(value, native)
    except (ValueError, TypeError): pass
    else: raise AssertionError('Unsafe cleanup accepted')
    assert (rows, archived) == before


assert {row['id'] for row in manage(request('list'), native)['agents']} == {child, grandchild}
inventory = manage(request('list'), native)
assert inventory['agents'][0]['task'] == '/root/owned_worker' and inventory['agents'][0]['status'] == 'idle'
assert 'PRIVATE_TRANSCRIPT_CANARY' not in json.dumps(inventory)
for value in (request('close', parent), request('delete', unrelated), request('close', '/root/worker'),
              request('close', child), request('delete', child), request('list', child),
              {**request('close', grandchild), 'method': 'arbitrary'}, request('unexpected')):
    refused(value)
assert manage(request('close', grandchild), native)['history_retained']
assert grandchild in rows and grandchild in archived
assert manage(request('close', child), native)['status'] == 'closed'
refused(request('delete', child))  # Archived descendants still have saved history.
assert manage(request('delete', grandchild), native)['status'] == 'deleted'
assert manage(request('delete', child), native)['history_retained'] is False
assert not rows

# The native action may fail after close. Never report deletion in that case.
rows[child] = {'id': child, 'parentThreadId': parent}
archived.clear()
def failing(method, params):
    if method == 'thread/delete': raise RuntimeError('owned private native error')
    return native(method, params)
try: manage(request('delete', child), failing)
except RuntimeError: pass
else: raise AssertionError('Native deletion failure was hidden')
assert child in archived and child in rows

# A worker can spawn just before native shutdown. Preserve that child's parent history.
archived.clear()
def spawning(method, params):
    result = native(method, params)
    if method == 'thread/archive': rows[grandchild] = {'id': grandchild, 'parentThreadId': child}
    return result
try: manage(request('delete', child), spawning)
except ValueError: pass
else: raise AssertionError('A concurrent descendant was orphaned')
assert child in rows and grandchild in rows
del rows[grandchild]

with tempfile.TemporaryDirectory() as directory:
    support = Path(directory) / 'support'
    support.mkdir()
    helper = Path(directory) / 'subagent_lifecycle.py'
    helper.write_bytes((root / 'src/desktop/subagent_lifecycle.py').read_bytes())
    server = LifecycleServer(native, support)
    state = json.loads(server.state.read_text())
    url = 'http://127.0.0.1:' + str(state['port']) + '/manage'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for headers in ({}, {'Authorization': 'Bearer incorrect'},
                        {'Authorization': 'Bearer ' + state['token'], 'Origin': 'https://example.invalid'},
                        {'Authorization': 'Bearer ' + state['token'], 'Host': 'example.invalid'}):
            try: opener.open(urllib.request.Request(url, data=json.dumps(request('delete', child)).encode(), headers=headers))
            except urllib.error.HTTPError as error: assert error.code == 403
            else: raise AssertionError('Unauthenticated cleanup accepted')
        assert child in rows
        env = {**os.environ, 'CODEX_THREAD_ID': parent, 'HTTP_PROXY': 'http://unreachable.invalid:1'}
        result = subprocess.run([sys.executable, str(helper), 'list'], env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0 and json.loads(result.stdout)['agents'][0]['id'] == child
        env['CODEX_THREAD_ID'] = '/root'
        result = subprocess.run([sys.executable, str(helper), 'delete', child], env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode != 0 and child in rows
        assert state['token'] not in result.stdout + result.stderr
    finally: server.close()
    assert not (support / 'Subagent-Lifecycle.json').exists()
print('PASS: native close retains history; delete removes only owned targets; descendants first, self/unrelated refusal, failure reporting, local authentication and CLI credential isolation.')
