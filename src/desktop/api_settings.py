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
# Shared provider metadata parser lives beside the gateway protocol adapters.
sys.path.insert(0,str(Path(__file__).resolve().parent / 'gateway' if (Path(__file__).resolve().parent / 'gateway').is_dir() else Path(__file__).resolve().parent.parent / 'gateway'))
from model_metadata import discover, discover_upstreams, valid_model_id
from provider_registry import validate_upstream, validate_service_tier


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
        if not isinstance(entry,dict) or set(entry) != {'active','profiles'} or not isinstance(entry['profiles'],list) or len(entry['profiles']) > 16:
            raise ValueError('Store at most 16 named keys per provider.')
        existing = {p['id']:p for p in old['profiles']}
        if not entry['profiles']:
            if entry['active'] is not None:raise ValueError('An empty key list cannot have an active key.')
            result[pid]={'active':'default','profiles':[{'id':'default','label':'Default','key':''}],'clear':list(existing)}
            continue
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
            if not key and profile_id not in existing and profile_id!='default':
                raise ValueError('Enter a key for each newly added profile.')
            ids.add(profile_id); labels.add(label.strip().casefold())
            profiles.append({'id':profile_id,'label':label.strip(),'key':key})
        if entry['active'] not in ids:
            raise ValueError('Choose an active key from the list.')
        available = {p['id']:bool(p['key']) or existing.get(p['id'],{}).get('saved',False) for p in profiles}
        if any(available.values()) and not available[entry['active']]:
            raise ValueError('Select a profile with a saved key or enter its replacement.')
        changed=entry['active']!=old['active'] or ids!=set(existing) or any(p['key'] or p['label']!=existing.get(p['id'],{}).get('label') for p in profiles)
        if changed:result[pid] = {'active':entry['active'],'profiles':profiles,'clear':sorted(set(existing)-ids)}
    if len(json.dumps(result).encode('utf-8')) > 60*1024:
        raise ValueError('Key-profile changes exceed the local settings size limit.')
    return result


def prepare_configuration(request, providers, catalog):
    providers, catalog = copy.deepcopy(providers), copy.deepcopy(catalog)
    existing = {mid: pid for pid, p in providers.items() for mid in p['models']}
    old_routes={mid:route for p in providers.values() for mid,route in p['models'].items()}
    metadata = {m['slug']: m for m in catalog['models']}
    requested=request['providers']
    if not isinstance(requested,dict) or len(requested)>32:raise ValueError('Configure at most 32 external providers.')
    updated={}
    for pid,changes in requested.items():
        if not isinstance(pid,str) or not PROFILE_ID.fullmatch(pid) or pid=='openai':raise ValueError('Use a unique provider ID; openai is reserved for ChatGPT.')
        if not isinstance(changes,dict) or set(changes)-{'enabled'} not in ({'endpoint','default_model'},{'label','adapter','endpoint','default_model'}):raise ValueError('Unexpected provider options.')
        if type(changes.get('enabled',True)) is not bool:raise ValueError('Provider enabled must be a boolean.')
        old=providers.get(pid)
        if not old and set(changes)-{'enabled'}!={'label','adapter','endpoint','default_model'}:raise ValueError('New providers require a name and a verified protocol.')
        if old and changes.get('adapter',old['adapter'])!=old['adapter']:raise ValueError('Existing provider protocols cannot be changed.')
        provider={**(old or {}),**changes,'models':{}}
        if not old and provider['adapter'] not in {'responses','chat_completions'}:raise ValueError('New providers must use Responses or Chat Completions.')
        updated[pid]=provider
    # Retire external models without deleting their instructions or changing
    # old chat IDs. Native models are never marked or removed.
    owners={mid:pid for mid,pid in existing.items()}
    owners.update({mid:m['better_codex_provider'] for mid,m in metadata.items() if 'better_codex_provider' in m})
    for mid,pid in owners.items():
        metadata[mid].update(better_codex_provider=pid,better_codex_removed=True)
    providers=updated
    rows = request['models']
    if not isinstance(rows, list) or len(rows)>128:
        raise ValueError('Configure at most 128 external models.')
    seen = set()
    for row in rows:
        fields={'id', 'provider', 'label', 'context', 'output', 'efforts', 'default_effort'}
        if not isinstance(row, dict) or not fields <= set(row) or set(row)-fields-{'metadata_mode','reasoning_mode','enabled','upstream_provider','service_tier','auto_compact_token_limit'}:
            raise ValueError('Unexpected model options.')
        if type(row.get('enabled',True)) is not bool:raise ValueError('Model enabled must be a boolean.')
        mid, pid = row['id'], row['provider']
        mode=row.get('metadata_mode','custom');reasoning_mode=row.get('reasoning_mode','explicit')
        if mode not in {'provider','custom'} or reasoning_mode not in {'provider_default','explicit'}:
            raise ValueError('Choose provider metadata or Customize.')
        if not valid_model_id(mid,pid) or mid in seen:
            raise ValueError('Model IDs must be unique, nonempty API identifiers.')
        seen.add(mid)
        if pid not in providers or (mid in metadata and owners.get(mid) != pid):
            raise ValueError('Native models and existing provider assignments cannot be changed.')
        if not isinstance(row['label'], str) or not 1 <= len(row['label'].strip()) <= 160:
            raise ValueError('Model labels must contain 1 to 160 characters.')
        if type(row['context']) is not int or not 2 <= row['context'] <= 4_194_304 or type(row['output']) is not int or not 1 <= row['output'] <= row['context'] or row['output'] > 1_048_576 or (mode=='custom' and row['output']==row['context']):
            raise ValueError('Supply valid limits; use Customize if the provider does not report them.')
        compact=row.get('auto_compact_token_limit')
        if compact is not None and (type(compact) is not int or not 1 <= compact <= 4_194_304):
            raise ValueError('Auto-compact tokens must be a positive whole number or blank.')
        efforts = row['efforts']
        if not isinstance(efforts, list) or not efforts or any(e not in EFFORTS for e in efforts) or len(set(efforts)) != len(efforts) or row['default_effort'] not in efforts:
            raise ValueError('Choose supported efforts and a default from that list.')
        if reasoning_mode=='provider_default' and (efforts!=['none'] or row['default_effort']!='none'):
            raise ValueError('Provider default must not claim specific reasoning levels.')
        template = metadata.get(providers[pid]['default_model']) or next(iter(metadata.values()))
        model = metadata.get(mid, copy.deepcopy(template))
        model.update(slug=mid, display_name=row['label'].strip(), context_window=row['context'],
                     max_context_window=row['context'], default_reasoning_level=row['default_effort'],
                     supported_reasoning_levels=[{'effort':e, 'description':'Provider default (no reasoning override)' if reasoning_mode=='provider_default' else e.capitalize() + ' reasoning effort'} for e in efforts],
                     supports_reasoning_effort_updates=len(efforts) > 1)
        if mid not in metadata:
            model['input_modalities'] = ['text']
            model['description'] = 'Custom model through ' + providers[pid]['label'] + '; verify provider capabilities before use.'
            # Do not copy another model's persistent identity/instructions.
            model['model_messages'] = {
                'instructions_template':'You are Codex, a coding assistant. Follow user and project instructions, use the advertised tools, and respect native permissions and approval requirements. Verify results before claiming success.',
                'persistent_instructions':''}
            catalog['models'].append(model)
            metadata[mid] = model
        if 'auto_compact_token_limit' in row:
            if compact is None:model.pop('better_codex_auto_compact_token_limit',None)
            else:model['better_codex_auto_compact_token_limit']=compact
        elif mid not in owners:model.pop('better_codex_auto_compact_token_limit',None)
        model.update(better_codex_provider=pid,better_codex_removed=False)
        providers[pid]['models'][mid]=copy.deepcopy(old_routes.get(mid,{}))
        providers[pid]['models'][mid]['output_limit'] = row['output']
        route=providers[pid]['models'][mid]
        route['enabled']=row.get('enabled',True)
        if 'metadata_mode' in row:route['metadata_mode']=mode
        if 'reasoning_mode' in row:route['reasoning_mode']=reasoning_mode
        if providers[pid]['adapter']=='opencode' and ('metadata_mode' in row or 'reasoning_mode' in row):
            route['send_variant']=reasoning_mode=='explicit'
        upstream=row.get('upstream_provider', route.get('upstream_provider', ''))
        validate_upstream(pid, providers[pid], upstream)
        if upstream:route['upstream_provider']=upstream
        else:route.pop('upstream_provider', None)
        tier=row.get('service_tier', route.get('service_tier', ''))
        validate_service_tier(pid, providers[pid], tier)
        if tier:route['service_tier']=tier
        else:route.pop('service_tier', None)
    for p in providers.values():
        if not p['default_model'] and p['models']:p['default_model']=next(iter(p['models']))
        if p['models'] and p['default_model'] not in p['models']:raise ValueError('Choose a remaining default model before deleting the current default.')
        if not p['models']:p['default_model']=''
        active=[mid for mid,route in p['models'].items() if route.get('enabled',True)]
        if active and p['default_model'] not in active:p['default_model']=active[0]
    return providers, catalog


class Settings:
    def __init__(self, deployment, live_apply=None, catalog_refresh=None, current_selection=None):
        self.deployment = Path(deployment).resolve()
        self.project = self.deployment.parent.parent
        if self.deployment.parent.name != '.local' or not (self.project / 'scripts/build-deployment.py').is_file():
            raise ValueError('Settings require a managed project deployment.')
        self.lock = threading.Lock()
        self.live_apply=live_apply
        self.catalog_refresh=catalog_refresh
        self.current_selection=current_selection
        self.applied_selection=self.deployment
        self.metadata_cache={}
        self.runtime_checks=json.loads((self.deployment/'Helper-Checksums.json').read_text())
        self.runtime_sha256=hashlib.sha256((self.deployment/'Helper-Checksums.json').read_bytes()).hexdigest()

    def selected(self):
        pointer=self.project/'.local/settings-path.txt'
        if not pointer.exists():pointer=self.project/'.local/deployment-path.txt'
        path = (self.project / pointer.read_text().strip()).resolve()
        if path.parent != self.project / '.local':
            raise ValueError('Invalid selected deployment.')
        return path

    def snapshot(self):
        folder = self.project / 'config'
        pbytes, mbytes = [(folder / name).read_bytes() for name in ('providers.json', 'models.json')]
        providers, catalog = json.loads(pbytes), json.loads(mbytes)
        metadata = {m['slug']: m for m in catalog['models']}
        selected = self.selected()
        current_selection=getattr(self,'current_selection',None)
        applied=Path(current_selection() if current_selection else getattr(self,'applied_selection',self.deployment)).resolve()
        key_folder = selected / 'gateway/keys'
        profiles = credential_profiles(key_folder, providers)
        revision = hashlib.sha256(pbytes + b'\0' + mbytes + json.dumps(profiles,sort_keys=True).encode())
        for pid,entry in profiles.items():
            for p in entry['profiles']:
                if p['saved']:
                    name = pid + ('' if p['id']=='default' else '--' + p['id']) + '.dpapi'
                    revision.update(hashlib.sha256((key_folder / name).read_bytes()).digest())
        return {'revision':revision.hexdigest(),'live_supported':bool(getattr(self,'live_apply',None)),
            'catalog_refresh_supported':bool(getattr(self,'catalog_refresh',None)),
            'apply_pending':bool(getattr(self,'live_apply',None)) and selected!=applied,
            'providers':{pid:{'label':p['label'],'adapter':p['adapter'],'endpoint':p['endpoint'],
                'enabled':p.get('enabled',True),
                'default_model':p['default_model'],'saved_key':any(profile['id']==profiles[pid]['active'] and profile['saved'] for profile in profiles[pid]['profiles']),
                'credential_profiles':profiles[pid]} for pid,p in providers.items()},
            'models':[{'id':mid,'provider':pid,'label':metadata[mid]['display_name'],
                'auto_compact_token_limit':metadata[mid].get('better_codex_auto_compact_token_limit'),
                'context':metadata[mid]['context_window'],'output':route.get('output_limit',4096),'enabled':route.get('enabled',True),
                'efforts':[e['effort'] for e in metadata[mid]['supported_reasoning_levels']],
                'default_effort':metadata[mid]['default_reasoning_level'],
                'metadata_mode':route.get('metadata_mode','custom'),
                'reasoning_mode':route.get('reasoning_mode','explicit'),
                'upstream_provider':route.get('upstream_provider',''),
                'service_tier':route.get('service_tier','')} for pid,p in providers.items() for mid,route in p['models'].items()]}

    def provider_key(self, pid, pending=None):
        """Read only the selected external credential; never return it to the UI."""
        profile=None
        if pending and pid in pending:
            entry=pending[pid];profile=entry['active']
            key=next(p['key'] for p in entry['profiles'] if p['id']==profile)
            if key:return key
            if profile in entry.get('clear',[]):return ''
        if pid not in json.loads((self.selected()/'providers.json').read_text()):return ''
        ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        # Use the reviewed source reader so older staged deployments can read
        # a named profile without changing their saved active selection.
        reader=self.project/'src/gateway/Provider-Credentials.ps1'
        command=[str(ps),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(reader),'-Mode','Token','-Provider',pid,
            '-Storage',str(self.selected()/'gateway')]
        if profile:command+=['-Profile',profile]
        result=subprocess.run(command,text=True,capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        return result.stdout if result.returncode==0 else ''

    def fetch_metadata(self,pid,mid,definition,pending=None):
        if not valid_model_id(mid,pid):raise ValueError('Enter a valid provider model ID or OpenRouter @preset/slug.')
        key=self.provider_key(pid,pending)
        try:return discover(pid,definition,mid,key)
        finally:key=None

    def stage(self, keys=None, select=True):
        """Fresh local files only; preserve all prior deployments and rollback state."""
        if getattr(self,'live_apply',None):return self.stage_settings(keys,select)
        previous = self.selected()
        runtime=(self.project/(self.project/'.local/deployment-path.txt').read_text().strip()).resolve()
        if runtime.parent!=self.project/'.local':raise ValueError('Runtime must remain in this project local folder.')
        target = self.project / '.local' / ('deployment-settings-' + uuid.uuid4().hex[:10])
        target.mkdir()
        for name in ('Deployment.json', 'Provider-Overlay.json'):
            shutil.copyfile(runtime / name, target / name)
        (target / 'opencode-engine').mkdir()
        for name in ('opencode.exe','Verification.json'):
            shutil.copyfile(runtime / 'opencode-engine' / name,target / 'opencode-engine' / name)
        if (previous / 'gateway/keys').exists():
            shutil.copytree(previous / 'gateway/keys', target / 'gateway/keys')
            # Prune only the fresh copy. Previous deployments retain encrypted
            # rollback keys; re-adding a deleted provider must not resurrect one.
            retained=json.loads((self.project/'config/providers.json').read_text())
            old=json.loads((previous/'providers.json').read_text())
            profiles=credential_profiles(previous/'gateway/keys',old)
            for pid in set(old)-set(retained):
                for profile in profiles[pid]['profiles']:
                    name=pid+('' if profile['id']=='default' else '--'+profile['id'])+'.dpapi'
                    path=target/'gateway/keys'/name
                    if path.exists():path.unlink()
            index=target/'gateway/keys/Profiles.json'
            if index.exists():
                value=json.loads(index.read_text())
                filtered={pid:entry for pid,entry in value['providers'].items() if pid in retained}
                if filtered!=value['providers']:
                    value['providers']=filtered
                    index.write_text(json.dumps(value),encoding='utf-8')
        dependencies = runtime / 'support/opencode-runtime/config/opencode/node_modules'
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
        if not select:return target
        rollback = self.project / '.local/previous-api-settings-deployment.txt'
        if not rollback.exists(): rollback.write_bytes(original_selection)
        temporary = selection.with_suffix('.tmp')
        temporary.write_text(target.relative_to(self.project).as_posix())
        temporary.replace(selection)
        settings_pointer=self.project/'.local/settings-path.txt'
        if settings_pointer.exists():settings_pointer.unlink()
        return target

    def stage_settings(self,keys=None,select=True):
        """Data only. Keep all executable/UI/vendor assets in the verified runtime."""
        from live_settings import verify_settings_generation
        from model_profiles import load_profiles
        if hashlib.sha256((self.deployment/'Helper-Checksums.json').read_bytes()).hexdigest()!=self.runtime_sha256:
            raise ValueError('Verified runtime identity changed; settings were retained.')
        previous=self.selected();target=self.project/'.local'/('settings-'+uuid.uuid4().hex[:10])
        (target/'gateway').mkdir(parents=True);(target/'support').mkdir()
        for name in ('providers.json','models.json','instructions.json'):
            shutil.copyfile(self.project/'config'/name,target/name)
        shutil.copyfile(self.deployment/'Deployment.json',target/'Deployment.json')
        _,profiles=load_profiles(self.project/'config')
        for name in profiles:
            path=target/'instructions'/name;path.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(self.project/'config/instructions'/name,path)
        script=self.deployment/'gateway/Provider-Credentials.ps1'
        if hashlib.sha256(script.read_bytes()).hexdigest()!=self.runtime_checks['gateway/Provider-Credentials.ps1']:
            raise ValueError('Credential helper changed; settings were retained.')
        shutil.copyfile(script,target/'gateway/Provider-Credentials.ps1')
        providers=json.loads((target/'providers.json').read_text())
        old=json.loads((previous/'providers.json').read_text())
        profiles=credential_profiles(previous/'gateway/keys',old)
        source_keys=previous/'gateway/keys';dest=target/'gateway/keys';dest.mkdir()
        index={'version':1,'providers':{}}
        for pid in providers:
            if pid not in profiles:continue
            entry=profiles[pid];index['providers'][pid]={'active':entry['active'],'profiles':{p['id']:p['label'] for p in entry['profiles']}}
            for profile in entry['profiles']:
                name=pid+('' if profile['id']=='default' else '--'+profile['id'])+'.dpapi'
                if profile['saved']:shutil.copyfile(source_keys/name,dest/name)
        (dest/'Profiles.json').write_text(json.dumps(index),encoding='utf8')
        if keys:
            ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
            saved=subprocess.run([str(ps),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(target/'gateway/Provider-Credentials.ps1'),'-Mode','SaveProfiles'],
                input=json.dumps(keys),text=True,capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
            if saved.returncode:raise ValueError('Could not encrypt the keys; previous keys were retained.')
        files={p.relative_to(target).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file() and not p.is_relative_to(dest)}
        manifest={'version':1,'runtime':self.deployment.name,
            'runtime_sha256':hashlib.sha256((self.deployment/'Helper-Checksums.json').read_bytes()).hexdigest(),'files':files}
        (target/'Settings-Manifest.json').write_text(json.dumps(manifest),encoding='utf8')
        verify_settings_generation(self.deployment,target,self.runtime_sha256)
        (target/'support/Previous-Settings-Deployment.txt').write_text(previous.relative_to(self.project).as_posix())
        if select:
            pointer=self.project/'.local/settings-path.txt';temporary=pointer.with_suffix('.tmp')
            temporary.write_text(target.relative_to(self.project).as_posix());temporary.replace(pointer)
        return target

    def handle(self, request):
        if not isinstance(request, dict): raise ValueError('Invalid settings request.')
        if request == {'action':'get'}: return self.snapshot()
        if set(request)=={'action','revision'} and request['action']=='refresh_catalog':
            with self.lock:
                if request['revision']!=self.snapshot()['revision']:raise ValueError('Settings changed; reopen this page before refreshing.')
                if not getattr(self,'catalog_refresh',None):raise ValueError('This running helper does not support in-app model refresh.')
                self.apply_selected()
                return self.catalog_refresh()
        if set(request)=={'action','revision'} and request['action']=='apply_live':
            with self.lock:
                if request['revision']!=self.snapshot()['revision']:raise ValueError('Settings changed; reopen the page before applying.')
                if not getattr(self,'live_apply',None):raise ValueError('This running helper does not support live apply. No process was restarted.')
                return self.apply_selected()
        if set(request)=={'action','revision','provider','model'} and request['action'] in {'metadata','upstream_providers'}:
            with self.lock:
                current=self.snapshot()
                if request['revision']!=current['revision']:raise ValueError('Settings changed. Reopen Better Codex before fetching metadata.')
                pid=request['provider']
                if not isinstance(pid,str) or pid not in current['providers']:raise ValueError('Choose a configured external provider.')
                if request['action']=='upstream_providers':
                    return discover_upstreams(pid, current['providers'][pid], request['model'])
                info=self.fetch_metadata(pid,request['model'],current['providers'][pid])
                if not hasattr(self,'metadata_cache'):self.metadata_cache={}
                self.metadata_cache[(current['revision'],pid,request['model'])]=info
                if len(self.metadata_cache)>128:self.metadata_cache.pop(next(iter(self.metadata_cache)))
                return info
        if set(request) != {'action','revision','providers','models','keys'} or request['action'] != 'save':
            raise ValueError('Invalid settings action.')
        with self.lock:
            current = self.snapshot()
            if request['revision'] != current['revision']:
                raise ValueError('Settings changed elsewhere. Close and reopen Better Codex before saving.')
            folder = self.project / 'config'
            original_providers=json.loads((folder/'providers.json').read_text(encoding='utf-8'))
            original_catalog=json.loads((folder/'models.json').read_text(encoding='utf-8'))
            # Validate destination/schema before making any metadata request.
            # Provisional limits are never saved; automatic rows are replaced
            # exclusively by the authenticated provider response below.
            validated=copy.deepcopy(request)
            for row in validated['models']:
                if isinstance(row,dict) and row.get('metadata_mode')=='provider':
                    row.update(context=2,output=1,efforts=['none'],default_effort='none',reasoning_mode='provider_default')
                    if not row.get('label'):row['label']=row.get('id','')
            providers,catalog=prepare_configuration(validated,original_providers,original_catalog)
            self.validate(providers,catalog,folder)
            current_keys=credential_profiles(self.selected()/'gateway/keys',providers)
            keys=prepare_credentials(request['keys'],{pid:{'credential_profiles':entry} for pid,entry in current_keys.items()})
            for index,row in enumerate(validated['models']):
                if row.get('metadata_mode')!='provider':continue
                pid=row['provider'];entry=keys.get(pid)
                previous=next((m for m in current['models'] if m['id']==row['id'] and m['provider']==pid),None)
                info=getattr(self,'metadata_cache',{}).get((current['revision'],pid,row['id']))
                unchanged_credentials=not entry or (entry['active']==current['providers'].get(pid,{}).get('credential_profiles',{}).get('active') and
                    not any(p['key'] for p in entry['profiles'] if p['id']==entry['active']) and entry['active'] not in entry['clear'])
                if pid not in current['providers'] or providers[pid]['endpoint']!=current['providers'][pid]['endpoint'] or not unchanged_credentials:info=None
                if info is None and previous and previous['metadata_mode']=='provider':
                    # Routine edits reuse trusted saved limits. Only adding a
                    # model, enabling provider mode or explicit refresh discovers.
                    for field in ('context','output','efforts','default_effort','reasoning_mode'):row[field]=previous[field]
                    desired=request['models'][index]['default_effort']
                    if desired in row['efforts']:row['default_effort']=desired
                    continue
                if info is None:info=self.fetch_metadata(row['provider'],row['id'],providers[row['provider']],keys)
                if not info['context'] or not info['output']:raise ValueError('Provider limits are incomplete. Choose Customize and supply the missing values.')
                if info['tools'] is False:raise ValueError('The provider reports no tool support; choose a tool-capable model.')
                row.update(context=info['context'],output=info['output'],efforts=info['efforts'] or ['none'],
                    default_effort=request['models'][index]['default_effort'] if info['efforts'] and request['models'][index]['default_effort'] in info['efforts'] else info['default_effort'] or 'none',
                    reasoning_mode='explicit' if info['efforts'] else 'provider_default')
                if not request['models'][index]['label']:row['label']=info['label']
            providers,catalog=prepare_configuration(validated,original_providers,original_catalog)
            self.validate(providers,catalog,folder)
            # Validate with the same routing and instruction guards used at launch.
            originals = {name:(folder / name).read_bytes() for name in ('providers.json','models.json')}
            written = {}
            try:
                for name,value in (('providers.json',providers),('models.json',catalog)):
                    temporary = folder / (name + '.tmp')
                    temporary.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
                    written[name] = temporary.read_bytes()
                    temporary.replace(folder / name)
                self.stage(keys)
                if hasattr(self,'metadata_cache'):self.metadata_cache.clear()
            except Exception:
                for name,data in originals.items():
                    if (folder / name).read_bytes() == written.get(name): (folder / name).write_bytes(data)
                raise
            if getattr(self,'live_apply',None):
                try:return self.apply_selected()
                except (ValueError,OSError,RuntimeError) as error:
                    reason='Use Retry apply to see the specific validation error.'
                    if isinstance(error,ValueError):
                        if str(error).startswith('This update changes helper code.'):
                            reason='This includes a helper-code update, which loads on the next normal launch.'
                        elif str(error).startswith(('The model cache belongs to another session.','Open the model menu once')):
                            reason='Open the chat model menu once, then retry Refresh models.'
                    return {'message':'Saved, but not applied. The previous running setup was retained. '+reason,
                        'settings':self.snapshot(),'live_applied':False}
            return {'message':'Saved for the next launch. This running helper has no live-apply hook; the running chats are unchanged.',
                'settings':self.snapshot(),'live_applied':False}

    def apply_selected(self):
        selected=self.selected()
        result=self.live_apply(selected)
        self.applied_selection=selected
        snapshot=self.snapshot()
        return {**result,'settings':snapshot,'live_applied':True,
            'provider_config':{'providers':[{'id':'openai','label':'ChatGPT'}]+[
                {'id':pid,'label':p['label'],'defaultModel':p['default_model'],'enabled':p['enabled']} for pid,p in snapshot['providers'].items()],
                'models':{row['id']:row['provider'] for row in snapshot['models']},
                'disabledModels':[row['id'] for row in snapshot['models'] if not row['enabled']]},
            'message':'Keys, URLs and routing applied live. Model catalog changes are pending a backend catalog refresh.' if result['catalog_pending'] else
                'Settings applied for new requests; running responses keep their original settings. Click Refresh models to update the picker with a UI reload.' if result.get('catalog_changed',True) and getattr(self,'catalog_refresh',None) else 'Settings applied for new requests; no UI reload needed.'}

    def validate(self,providers,catalog,folder):
        from provider_registry import load_registry
        from model_profiles import load_profiles
        with tempfile.TemporaryDirectory(dir=self.project/'.local',prefix='settings-validation-') as temp:
            validation=Path(temp)
            (validation/'providers.json').write_text(json.dumps(providers))
            (validation/'models.json').write_text(json.dumps(catalog))
            shutil.copyfile(folder/'instructions.json',validation/'instructions.json')
            shutil.copytree(folder/'instructions',validation/'instructions')
            load_registry(validation);load_profiles(validation)
