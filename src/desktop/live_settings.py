"""Publish verified settings between requests; keep code and rollback immutable."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import threading
import time

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
                    if remaining<=0:raise ValueError('Chats are still sending requests. Saved changes remain pending; retry Apply live when idle.')
                    self.condition.wait(remaining)
                yield
            finally:self.swapping=False;self.condition.notify_all()

def verify_generation(current,target):
    current,target=Path(current).resolve(),Path(target).resolve()
    if target.parent!=current.parent or target.parent.name!='.local':raise ValueError('Live settings require a sibling managed deployment.')
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
