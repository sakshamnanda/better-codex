"""Publish verified settings between requests; keep code and rollback immutable."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import threading
import time
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestSettings:
    registry: tuple
    profile_settings: dict
    profiles: dict
    catalog: dict
    key_storage: Path
    engine: object = None


class SettingsGenerations:
    """Pin settings per response; retire old engines only after their last user."""
    def __init__(self,settings,retire_engine):
        self.lock=threading.RLock();self.entries={};self.retire_engine=retire_engine
        self.current=None;self.closed=False
        self.publish(settings)

    @contextmanager
    def request(self,token=None):
        with self.lock:
            token=self.current if token is None else token
            if self.closed or token not in self.entries:raise ValueError('Request settings generation is unavailable.')
            entry=self.entries[token];entry['readers']+=1
        try:yield token,entry['settings']
        finally:
            with self.lock:
                entry['readers']-=1
                engines=self._collect()
            for engine in engines:self.retire_engine(engine)

    def _collect(self):
        removed=[]
        for token,entry in list(self.entries.items()):
            if token!=self.current and not entry['readers']:
                removed.append(entry['settings'].engine);del self.entries[token]
        remaining={id(e['settings'].engine) for e in self.entries.values()}
        return list({id(engine):engine for engine in removed if engine is not None and id(engine) not in remaining}.values())

    def publish(self,settings,before_publish=lambda:None):
        with self.lock:
            if self.closed:raise ValueError('Provider service is closing.')
            token=secrets.token_urlsafe(32)
            before_publish()
            self.entries[token]={'settings':settings,'readers':0};self.current=token
            engines=self._collect()
        for engine in engines:self.retire_engine(engine)

    def close(self):
        with self.lock:
            engines={id(e['settings'].engine):e['settings'].engine for e in self.entries.values() if e['settings'].engine is not None}
            self.closed=True;self.current=None;self.entries.clear()
        for engine in engines.values():self.retire_engine(engine)

class ReloadGate:
    def __init__(self):
        self.condition=threading.Condition();self.readers=0;self.swapping=False

    @contextmanager
    def request(self,continuation=False):
        with self.condition:
            while self.swapping and not continuation:self.condition.wait()
            self.readers+=1
        try:yield
        finally:
            with self.condition:
                self.readers-=1;self.condition.notify_all()

    @contextmanager
    def replace(self,timeout=30):
        deadline=time.monotonic()+timeout
        with self.condition:
            if self.swapping:raise ValueError('Another live settings update is in progress.')
            self.swapping=True
            try:
                while self.readers:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise ValueError('A chat or background request is still active. Wait for it to finish, then retry Apply live and Refresh models. Saved changes remain pending; nothing was restarted.')
                    self.condition.wait(remaining)
                yield
            finally:self.swapping=False;self.condition.notify_all()

def verify_generation(current,target):
    current,target=Path(current).resolve(),Path(target).resolve()
    if target.parent!=current.parent or target.parent.name!='.local':raise ValueError('Live settings require a sibling managed deployment.')
    if (target/'Settings-Manifest.json').exists():return verify_settings_generation(current,target)
    original=json.loads((current/'Deployment.json').read_text())
    manifest=json.loads((target/'Deployment.json').read_text())
    if manifest!=original:raise ValueError('Live settings cannot change the installed build or native model allowlist.')
    checks=json.loads((target/'Helper-Checksums.json').read_text())
    previous=json.loads((current/'Helper-Checksums.json').read_text())
    code={name:value for name,value in previous.items() if name.endswith(('.py','.ps1','.ts','.exe'))}
    if any(checks.get(name)!=value for name,value in code.items()) or {name for name in checks if name.endswith(('.py','.ps1','.ts','.exe'))}!=set(code):
        raise ValueError('This update changes helper code. It cannot be installed into a running helper; settings-only updates support live apply.')
    for name,expected in checks.items():
        path=(target/name).resolve()
        if not path.is_relative_to(target) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Live settings deployment verification failed.')
    for name,expected in manifest['installed_file_hashes'].items():
        with (Path(manifest['source_app'])/name).open('rb') as handle:
            if hashlib.file_digest(handle,'sha256').hexdigest()!=expected:raise ValueError('Installed build changed; live settings refused.')
    return target


def verify_settings_generation(runtime,target,expected_runtime_sha256=None):
    """Validate data-only snapshots against an already verified runtime."""
    runtime,target=Path(runtime).resolve(),Path(target).resolve()
    if target.parent!=runtime.parent or target.parent.name!='.local' or not target.name.startswith('settings-'):
        raise ValueError('Settings snapshots must remain beside their verified runtime.')
    manifest=json.loads((target/'Settings-Manifest.json').read_text())
    digest=hashlib.sha256((runtime/'Helper-Checksums.json').read_bytes()).hexdigest()
    if not isinstance(manifest,dict) or set(manifest)!={'version','runtime','runtime_sha256','files'} or manifest['version']!=1 or manifest['runtime']!=runtime.name or manifest['runtime_sha256']!=digest or (expected_runtime_sha256 is not None and digest!=expected_runtime_sha256):
        raise ValueError('Settings snapshot does not match this verified runtime.')
    required={'Deployment.json','providers.json','models.json','instructions.json','gateway/Provider-Credentials.ps1'}
    files=manifest['files']
    if not isinstance(files,dict) or not required<=set(files):raise ValueError('Settings snapshot is incomplete.')
    for name,expected in files.items():
        path=(target/name).resolve()
        if (name not in required and not (name.startswith('instructions/') and name.endswith('.md'))) or not path.is_relative_to(target) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Settings snapshot verification failed.')
    runtime_checks=json.loads((runtime/'Helper-Checksums.json').read_text())
    if files['Deployment.json']!=runtime_checks['Deployment.json'] or files['gateway/Provider-Credentials.ps1']!=runtime_checks['gateway/Provider-Credentials.ps1']:
        raise ValueError('Settings snapshots cannot replace runtime code or build identity.')
    return target
