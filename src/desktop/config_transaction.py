"""Only two managed user-level keys; no authentication or chat database access."""
from pathlib import Path
import hashlib
import json
import re
import time
import tomllib

KEYS = ('openai_base_url','model_catalog_json')

def digest(data): return hashlib.sha256(data).hexdigest()

def managed_text(text,values):
    head,separator,tail = text.partition('\n[')
    for key in KEYS:
        head = re.sub(r'(?m)^\s*' + key + r'\s*=.*\n?', '', head)
    return ''.join(key + ' = ' + json.dumps(value) + '\n' for key,value in values.items()) + head + separator + tail

def atomic(path,data):
    path = Path(path)
    temporary = path.with_name(path.name + '.provider-write.tmp')
    with temporary.open('xb') as handle: handle.write(data)
    temporary.replace(path)

def activate(config_path,base_url,catalog_path,backup_directory,state_path):
    config_path = Path(config_path)
    original = config_path.read_bytes()
    parsed = tomllib.loads(original.decode('utf-8-sig'))
    if parsed.get('model_provider','openai') != 'openai': raise RuntimeError('The original provider must remain ChatGPT/OpenAI')
    values = {'openai_base_url':base_url}
    if catalog_path is not None:values['model_catalog_json']=str(catalog_path)
    updated = managed_text(original.decode('utf-8-sig'),values).encode()
    expected = {key:value for key,value in parsed.items() if key not in KEYS} | values
    if tomllib.loads(updated.decode()) != expected: raise RuntimeError('Configuration merge altered unrelated settings')
    backup_directory = Path(backup_directory)
    backup_directory.mkdir(exist_ok=True)
    backup = backup_directory / (time.strftime('%Y%m%d-%H%M%S') + '-' + digest(original)[:12] + '.config.toml')
    if backup.exists() and backup.read_bytes() != original: raise RuntimeError('Backup collision')
    if not backup.exists(): backup.write_bytes(original)
    state = {'config_path':str(config_path),'backup_path':str(backup),'original_sha256':digest(original),'managed_sha256':digest(updated),'managed_values':values,'status':'prepared'}
    Path(state_path).write_text(json.dumps(state,indent=2))
    if config_path.read_bytes() != original: raise RuntimeError('Settings changed during preparation; activation cancelled')
    atomic(config_path,updated)
    state['status'] = 'active'
    Path(state_path).write_text(json.dumps(state,indent=2))
    return state

def rollback(state_path):
    state_path = Path(state_path)
    if not state_path.exists(): return False
    state = json.loads(state_path.read_text())
    if state.get('status') == 'restored': return True
    original = Path(state['backup_path']).read_bytes()
    if digest(original) != state['original_sha256']: raise RuntimeError('Rollback backup verification failed')
    config = Path(state['config_path'])
    current = config.read_bytes()
    if digest(current) == state['original_sha256']:
        state['status'] = 'restored'; state_path.write_text(json.dumps(state,indent=2)); return True
    if digest(current) == state['managed_sha256']:
        restored = original
    else:
        parsed = tomllib.loads(current.decode('utf-8-sig'))
        if any(parsed.get(key) != state['managed_values'].get(key) for key in KEYS):
            raise RuntimeError('Managed keys were changed separately; refusing to overwrite them. Original backup is preserved.')
        old = tomllib.loads(original.decode('utf-8-sig'))
        restored = managed_text(current.decode('utf-8-sig'),{key:old[key] for key in KEYS if key in old}).encode()
        expected = {key:value for key,value in parsed.items() if key not in KEYS} | {key:old[key] for key in KEYS if key in old}
        if tomllib.loads(restored.decode()) != expected: raise RuntimeError('Rollback merge altered unrelated settings')
    if config.read_bytes() != current: raise RuntimeError('Settings changed during rollback; retry after closing Codex')
    atomic(config,restored)
    state['status'] = 'restored'
    state_path.write_text(json.dumps(state,indent=2))
    return True
