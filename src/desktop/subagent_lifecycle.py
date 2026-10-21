"""Native subagent cleanup through the desktop's existing RPC connection."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import hmac
import json
import os
import secrets
import threading
import urllib.error
import urllib.request
import uuid


def thread_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Expected a canonical thread UUID.')
    return value


def manage(request, native):
    if not isinstance(request, dict) or set(request) != {'parent', 'action', 'target'}:
        raise ValueError('Invalid subagent cleanup request.')
    parent, action, target = request['parent'], request['action'], request['target']
    thread_id(parent)
    if action not in {'list', 'close', 'delete'}:
        raise ValueError('Use list, close or delete.')
    if action == 'list':
        if target is not None: raise ValueError('List does not accept a target.')
    else:
        thread_id(target)
        if target == parent: raise ValueError('Cannot clean up the calling chat.')
    agents = {}
    for archived in (False, True):
        cursor, seen = None, set()
        while True:
            page = native('thread/list', {'ancestorThreadId': parent, 'archived': archived,
                                         'cursor': cursor, 'limit': 100})
            for row in page['data']:
                identifier = thread_id(row['id'])
                if identifier == parent: raise ValueError('Native descendant inventory included the caller.')
                source = row.get('source')
                subagent = source.get('subAgent') if isinstance(source, dict) else None
                spawn = subagent.get('thread_spawn', {}) if isinstance(subagent, dict) else {}
                agents[identifier] = {'id': identifier, 'parent': row.get('parentThreadId'),
                                      'task': spawn.get('agent_path'), 'nickname': row.get('agentNickname'),
                                      'status': (row.get('status') or {}).get('type'), 'archived': archived}
            cursor = page.get('nextCursor')
            if not cursor: break
            if cursor in seen or len(agents) > 10000:
                raise ValueError('Native descendant inventory exceeded its bounds.')
            seen.add(cursor)
    if action == 'list': return {'agents': list(agents.values())}
    if target not in agents:
        raise ValueError('Target is not a saved subagent of the calling chat.')
    descendants, pending = set(), [target]
    while pending:
        current = pending.pop()
        for identifier, row in agents.items():
            if row['parent'] == current and identifier not in descendants:
                descendants.add(identifier)
                pending.append(identifier)
    if target in descendants: raise ValueError('Invalid native subagent ancestry.')
    if any(action == 'delete' or not agents[identifier]['archived'] for identifier in descendants):
        raise ValueError('Clean up descendants first; use list to find their thread IDs.')
    # Archive is the native close operation: it unloads the worker and retains history.
    if not agents[target]['archived']:
        native('thread/archive', {'threadId': target})
    if action == 'delete':
        # Recheck after shutdown so a last-moment spawn cannot lose its parent history.
        for archived in (False, True):
            if native('thread/list', {'parentThreadId': target, 'archived': archived,
                                      'cursor': None, 'limit': 1})['data']:
                raise ValueError('Target is closed; delete its descendants before deleting its history.')
        native('thread/delete', {'threadId': target})
    return {'id': target, 'status': 'deleted' if action == 'delete' else 'closed',
            'history_retained': action != 'delete'}


class LifecycleServer:
    def __init__(self, native, support):
        self.state = Path(support) / 'Subagent-Lifecycle.json'
        token, operation_lock = secrets.token_urlsafe(32), threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def log_message(self, *_args): pass

            def do_POST(self):
                expected_host = '127.0.0.1:' + str(self.server.server_port)
                authorized = (self.path == '/manage' and self.headers.get('Host') == expected_host
                    and self.headers.get('Origin') is None and self.headers.get('Transfer-Encoding') is None
                    and hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode()))
                status, result = 403, {'error': 'Subagent cleanup request refused.'}
                if authorized:
                    try:
                        size = int(self.headers.get('Content-Length', '0'))
                        if not 0 < size <= 4096: raise ValueError('Invalid cleanup request size.')
                        request = json.loads(self.rfile.read(size))
                        with operation_lock: result = manage(request, native)
                        status = 200
                    except (ValueError, TypeError, KeyError):
                        status, result = 400, {'error': 'Invalid target or request. List subagents and clean up descendants first.'}
                    except Exception:
                        status, result = 409, {'error': 'Native cleanup did not complete. List subagents before retrying; the target may already be closed.'}
                data = json.dumps(result).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.state.write_text(json.dumps({'port': self.server.server_port, 'token': token}), encoding='utf8')
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.state.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='List, close or permanently delete this chat\'s saved subagents. Clean up descendants first.')
    parser.add_argument('action', choices=('list', 'close', 'delete'))
    parser.add_argument('target', nargs='?')
    args = parser.parse_args()
    parent = thread_id(os.environ.get('CODEX_THREAD_ID'))
    state = json.loads((Path(__file__).resolve().parent / 'support/Subagent-Lifecycle.json').read_text(encoding='utf8'))
    port, token = state['port'], state['token']
    if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str) or len(token) != 43:
        raise ValueError('Invalid local cleanup connection.')
    request = urllib.request.Request('http://127.0.0.1:' + str(port) + '/manage',
        data=json.dumps({'parent': parent, 'action': args.action, 'target': args.target}).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=45) as response: result = json.load(response)
    except urllib.error.HTTPError as error:
        # Only our fixed, local error messages may leave the helper.
        result = json.load(error)
        raise ValueError(result['error']) from None
    print(json.dumps(result))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError('Cleanup redirects are refused.')


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, TypeError):
        raise SystemExit('Subagent cleanup unavailable or refused. Use the current custom launcher, list targets, and clean up descendants first. No success is claimed.')
