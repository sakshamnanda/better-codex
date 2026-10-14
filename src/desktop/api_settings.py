"""Local provider settings; validate and stage the next launch, never edit a live helper."""
from pathlib import Path
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid

EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
PROFILE_ID = re.compile(r'[a-z][a-z0-9_-]{0,63}')


def credential_profiles(folder, providers):
    index = folder / 'Profiles.json'
    value = json.loads(index.read_text(encoding='utf-8')) if index.exists() else {'version':1,'providers':{}}
    if not isinstance(value,dict) or set(value) != {'version','providers'} or value['version'] != 1 or not isinstance(value['providers'],dict):
        raise ValueError('Invalid local credential profile storage.')
    result = {}
    for pid in providers:
        entry = value['providers'].get(pid, {'active':'default','profiles':{'default':'Default'}})
        if not isinstance(entry,dict) or set(entry) != {'active','profiles'} or not isinstance(entry['profiles'],dict) or not 1 <= len(entry['profiles']) <= 16 or entry['active'] not in entry['profiles']:
            raise ValueError('Invalid local credential profiles.')
        profiles = []
        for profile_id,label in entry['profiles'].items():
            if not PROFILE_ID.fullmatch(profile_id) or not isinstance(label,str) or not 1 <= len(label.strip()) <= 80 or any(c in label for c in '\r\n\0'):
                raise ValueError('Invalid local credential profile name.')
            name = pid + ('' if profile_id == 'default' else '--' + profile_id) + '.dpapi'
            path = folder / name
            profiles.append({'id':profile_id,'label':label,'saved':path.is_file() and path.stat().st_size > 0})
        result[pid] = {'active':entry['active'],'profiles':profiles}
    return result


def prepare_credentials(values, current):
    if not isinstance(values,dict) or not set(values) <= set(current):
        raise ValueError('Choose credential profiles for configured providers only.')
    result = {}
    for pid, entry in values.items():
        old = current[pid]['credential_profiles']
        # Retain compatibility with the previous one-field local key editor.
        if isinstance(entry,str):
            entry = {'active':old['active'],'profiles':[{**{k:p[k] for k in ('id','label')},'key':entry if p['id']==old['active'] else ''} for p in old['profiles']]}
        if not isinstance(entry,dict) or set(entry) != {'active','profiles'} or not isinstance(entry['profiles'],list) or not 1 <= len(entry['profiles']) <= 16:
            raise ValueError('Store between 1 and 16 named keys per provider.')
        existing = {p['id']:p for p in old['profiles']}
        ids, labels, profiles = set(), set(), []
        for p in entry['profiles']:
            if not isinstance(p,dict) or set(p) != {'id','label','key'}:
                raise ValueError('Unexpected API-key profile options.')
            profile_id,label,key = p['id'],p['label'],p['key']
            if not isinstance(profile_id,str) or not PROFILE_ID.fullmatch(profile_id) or profile_id in ids:
                raise ValueError('Invalid or duplicate API-key profile ID.')
            if not isinstance(label,str) or not 1 <= len(label.strip()) <= 80 or any(c in label for c in '\r\n\0') or label.strip().casefold() in labels:
                raise ValueError('Give each key a distinct name of 1 to 80 characters.')
            if not isinstance(key,str) or len(key)>4096 or any(c in key for c in '\r\n\0'):
                raise ValueError('API keys must be single-line values.')
            key = key.strip()
            if not key and profile_id not in existing:
                raise ValueError('Enter a key for each newly added profile.')
            if profile_id == entry['active'] and not key and not existing.get(profile_id,{}).get('saved') and any(p['saved'] for p in old['profiles']):
                raise ValueError('Select a profile with a saved key.')
            ids.add(profile_id); labels.add(label.strip().casefold())
            profiles.append({'id':profile_id,'label':label.strip(),'key':key})
        if not set(existing) <= ids or entry['active'] not in ids:
            raise ValueError('Keep existing profiles and choose an active key from the list.')
        available = {p['id']:bool(p['key']) or existing.get(p['id'],{}).get('saved',False) for p in profiles}
        if any(available.values()) and not available[entry['active']]:
            raise ValueError('Select a profile with a saved key or enter its replacement.')
        result[pid] = {'active':entry['active'],'profiles':profiles}
    if len(json.dumps(result).encode('utf-8')) > 60*1024:
        raise ValueError('Key-profile changes exceed the local settings size limit.')
    return result


def prepare_configuration(request, providers, catalog):
    providers, catalog = copy.deepcopy(providers), copy.deepcopy(catalog)
    if set(request['providers']) != set(providers):
        raise ValueError('Keep the configured provider IDs; new protocols need a verified adapter.')
    existing = {mid: pid for pid, p in providers.items() for mid in p['models']}
    metadata = {m['slug']: m for m in catalog['models']}
    rows = request['models']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise ValueError('Configure between 1 and 128 external models.')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'provider', 'label', 'context', 'output', 'efforts', 'default_effort'}:
            raise ValueError('Unexpected model options.')
        mid, pid = row['id'], row['provider']
        if not isinstance(mid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}', mid) or mid in seen:
            raise ValueError('Model IDs must be unique, nonempty API identifiers.')
        seen.add(mid)
        if pid not in providers or (mid in metadata and existing.get(mid) != pid):
            raise ValueError('Native models and existing provider assignments cannot be changed.')
        if not isinstance(row['label'], str) or not 1 <= len(row['label'].strip()) <= 160:
            raise ValueError('Model labels must contain 1 to 160 characters.')
        if type(row['context']) is not int or not 2 <= row['context'] <= 4_194_304 or type(row['output']) is not int or not 1 <= row['output'] < row['context'] or row['output'] > 1_048_576:
            raise ValueError('Use valid token limits; output must be smaller than context.')
        efforts = row['efforts']
        if not isinstance(efforts, list) or not efforts or any(e not in EFFORTS for e in efforts) or len(set(efforts)) != len(efforts) or row['default_effort'] not in efforts:
            raise ValueError('Choose supported efforts and a default from that list.')
        template = metadata[providers[pid]['default_model']]
        model = metadata.get(mid, copy.deepcopy(template))
        model.update(slug=mid, display_name=row['label'].strip(), context_window=row['context'],
                     max_context_window=row['context'], default_reasoning_level=row['default_effort'],
                     supported_reasoning_levels=[{'effort':e, 'description':e.capitalize() + ' reasoning effort'} for e in efforts],
                     supports_reasoning_effort_updates=len(efforts) > 1)
        if mid not in metadata:
            model['description'] = 'Custom model through ' + providers[pid]['label'] + '; verify provider capabilities before use.'
            # Do not copy another model's persistent identity/instructions.
            model['model_messages'] = {
                'instructions_template':'You are Codex, a coding assistant. Follow user and project instructions, use the advertised tools, and respect native permissions and approval requirements. Verify results before claiming success.',
                'persistent_instructions':''}
            catalog['models'].append(model)
            metadata[mid] = model
        providers[pid]['models'].setdefault(mid, {})['output_limit'] = row['output']
    if not set(existing) <= seen:
        raise ValueError('Existing models must be retained to preserve chat and instruction mappings.')
    for pid, changes in request['providers'].items():
        if not isinstance(changes, dict) or set(changes) != {'endpoint', 'default_model'}:
            raise ValueError('Unexpected provider options.')
        providers[pid].update(changes)
    return providers, catalog


class Settings:
    def __init__(self, deployment):
        self.deployment = Path(deployment).resolve()
        self.project = self.deployment.parent.parent
        if self.deployment.parent.name != '.local' or not (self.project / 'scripts/build-deployment.py').is_file():
            raise ValueError('Settings require a managed project deployment.')
        self.lock = threading.Lock()

    def selected(self):
        path = (self.project / (self.project / '.local/deployment-path.txt').read_text().strip()).resolve()
        if path.parent != self.project / '.local':
            raise ValueError('Invalid selected deployment.')
        return path

    def snapshot(self):
        folder = self.project / 'config'
        pbytes, mbytes = [(folder / name).read_bytes() for name in ('providers.json', 'models.json')]
        providers, catalog = json.loads(pbytes), json.loads(mbytes)
        metadata = {m['slug']: m for m in catalog['models']}
        selected = self.selected()
        key_folder = selected / 'gateway/keys'
        profiles = credential_profiles(key_folder, providers)
        revision = hashlib.sha256(pbytes + b'\0' + mbytes + json.dumps(profiles,sort_keys=True).encode())
        for pid,entry in profiles.items():
            for p in entry['profiles']:
                if p['saved']:
                    name = pid + ('' if p['id']=='default' else '--' + p['id']) + '.dpapi'
                    revision.update(hashlib.sha256((key_folder / name).read_bytes()).digest())
        return {'revision':revision.hexdigest(),
            'providers':{pid:{'label':p['label'],'adapter':p['adapter'],'endpoint':p['endpoint'],
                'default_model':p['default_model'],'saved_key':any(profile['id']==profiles[pid]['active'] and profile['saved'] for profile in profiles[pid]['profiles']),
                'credential_profiles':profiles[pid]} for pid,p in providers.items()},
            'models':[{'id':mid,'provider':pid,'label':metadata[mid]['display_name'],
                'context':metadata[mid]['context_window'],'output':route.get('output_limit',4096),
                'efforts':[e['effort'] for e in metadata[mid]['supported_reasoning_levels']],
                'default_effort':metadata[mid]['default_reasoning_level']} for pid,p in providers.items() for mid,route in p['models'].items()]}

    def stage(self, keys=None):
        """Fresh local files only; preserve all prior deployments and rollback state."""
        previous = self.selected()
        target = self.project / '.local' / ('deployment-settings-' + uuid.uuid4().hex[:10])
        target.mkdir()
        for name in ('Deployment.json', 'Provider-Overlay.json'):
            shutil.copyfile(previous / name, target / name)
        (target / 'opencode-engine').mkdir()
        for name in ('opencode.exe','Verification.json'):
            shutil.copyfile(previous / 'opencode-engine' / name,target / 'opencode-engine' / name)
        if (previous / 'gateway/keys').exists():
            shutil.copytree(previous / 'gateway/keys', target / 'gateway/keys')
        dependencies = previous / 'support/opencode-runtime/config/opencode/node_modules'
        if dependencies.exists():
            shutil.copytree(dependencies, target / 'support/opencode-runtime/config/opencode/node_modules')
        selection = self.project / '.local/deployment-path.txt'
        original_selection = selection.read_bytes()
        try:
            built = subprocess.run([sys.executable, str(self.project / 'scripts/build-deployment.py'), '--output', str(target.relative_to(self.project)), '--no-select'],
                cwd=self.project,capture_output=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
            if built.returncode: raise ValueError('Could not prepare a verified deployment; running settings were retained.')
            if keys:
                ps = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
                saved = subprocess.run([str(ps), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    str(target / 'gateway/Provider-Credentials.ps1'), '-Mode', 'SaveProfiles'],
                    input=json.dumps(keys),text=True,capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
                if saved.returncode: raise ValueError('Could not encrypt the keys; previous keys were retained.')
            check = subprocess.run([sys.executable,str(target / 'launcher.py'),'--check'],
                capture_output=True,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
            if check.returncode: raise ValueError('Deployment verification failed; previous selection was retained.')
        except Exception:
            selection.write_bytes(original_selection)
            raise
        (target / 'support/Previous-Settings-Deployment.txt').write_bytes(original_selection)
        rollback = self.project / '.local/previous-api-settings-deployment.txt'
        if not rollback.exists(): rollback.write_bytes(original_selection)
        temporary = selection.with_suffix('.tmp')
        temporary.write_text(target.relative_to(self.project).as_posix())
        temporary.replace(selection)
        return target

    def handle(self, request):
        if not isinstance(request, dict): raise ValueError('Invalid settings request.')
        if request == {'action':'get'}: return self.snapshot()
        if set(request) != {'action','revision','providers','models','keys'} or request['action'] != 'save':
            raise ValueError('Invalid settings action.')
        with self.lock:
            current = self.snapshot()
            if request['revision'] != current['revision']:
                raise ValueError('Settings changed elsewhere. Close and reopen Better Codex before saving.')
            keys = prepare_credentials(request['keys'], current['providers'])
            folder = self.project / 'config'
            providers, catalog = prepare_configuration(request,json.loads((folder / 'providers.json').read_text(encoding='utf-8')),json.loads((folder / 'models.json').read_text(encoding='utf-8')))
            # Validate with the same routing and instruction guards used at launch.
            sys.path.insert(0,str(self.project / 'src/gateway'))
            from provider_registry import load_registry
            from model_profiles import load_profiles
            with tempfile.TemporaryDirectory(dir=self.project / '.local',prefix='settings-validation-') as temp:
                validation = Path(temp)
                (validation / 'providers.json').write_text(json.dumps(providers))
                (validation / 'models.json').write_text(json.dumps(catalog))
                shutil.copyfile(folder / 'instructions.json',validation / 'instructions.json')
                shutil.copytree(folder / 'instructions',validation / 'instructions')
                load_registry(validation); load_profiles(validation)
            originals = {name:(folder / name).read_bytes() for name in ('providers.json','models.json')}
            written = {}
            try:
                for name,value in (('providers.json',providers),('models.json',catalog)):
                    temporary = folder / (name + '.tmp')
                    temporary.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
                    written[name] = temporary.read_bytes()
                    temporary.replace(folder / name)
                self.stage(keys)
            except Exception:
                for name,data in originals.items():
                    if (folder / name).read_bytes() == written.get(name): (folder / name).write_bytes(data)
                raise
            return {'message':'Saved for the next launch. Close and reopen Codex (Custom Providers) when ready; the running chats are unchanged.',
                    'settings':self.snapshot()}
