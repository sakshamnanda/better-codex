"""Meaningful rollback cases with public scratch settings; no real profile."""
from pathlib import Path
import ast
import ctypes
import importlib.util
import json
import os
import tomllib
import uuid
root = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('transaction',root / 'src/desktop/config_transaction.py')
transaction = importlib.util.module_from_spec(spec); spec.loader.exec_module(transaction)
scratch = root / '.local/test-work' / ('rollback-' + uuid.uuid4().hex[:8]); scratch.mkdir(parents=True)
config = scratch / 'settings.toml'; state = scratch / 'state.json'; backups = scratch / 'backups'
original = b'model = "gpt-6.1-sol"\nnotify = []\n[features]\ncode_mode_host = true\n'
config.write_bytes(original)
transaction.activate(config,'http://127.0.0.1:12345/g/fixture/backend-api/codex',scratch / 'models.json',backups,state)
transaction.rollback(state); assert config.read_bytes() == original
transaction.activate(config,'http://127.0.0.1:12345/g/fixture/backend-api/codex',scratch / 'models.json',backups,state)
config.write_text('fixture_preference = "preserve"\n' + config.read_text())
transaction.rollback(state)
parsed = tomllib.loads(config.read_text()); assert parsed.pop('fixture_preference') == 'preserve'
assert parsed == tomllib.loads(original.decode())
transaction.activate(config,'http://127.0.0.1:12345/g/fixture/backend-api/codex',scratch / 'models.json',backups,state)
config.write_text(config.read_text().replace('12345','23456'))
try: transaction.rollback(state); raise AssertionError('Competing key overwritten')
except RuntimeError: pass
print('PASS: exact restoration, unrelated edits preserved, separately changed managed keys refused.')

# Exercise the actual builder guard with our own PID and isolated public state.
guarded = scratch / 'guarded-deployment'
(guarded / 'support').mkdir(parents=True)
(guarded / 'support/Activation-State.json').write_text(json.dumps({'helper_pid': os.getpid(), 'status': 'active'}))
builder = ast.parse((root / 'scripts/build-deployment.py').read_text())
function = next(node for node in builder.body if isinstance(node, ast.FunctionDef) and node.name == 'require_inactive')
context = {'DEPLOY': guarded, 'os': os, 'ctypes': ctypes, 'json': json}
exec(compile(ast.Module(body=[function], type_ignores=[]), 'builder-guard', 'exec'), context)
try: context['require_inactive'](); raise AssertionError('Active helper allowed to rebuild')
except RuntimeError as error: assert 'active' in str(error)
print('PASS: rebuild refuses an active helper without stopping it or replacing runtime files.')
