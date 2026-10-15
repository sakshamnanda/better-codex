"""Refresh this helper's native metadata cache; never touch auth or chat stores."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import secrets
import threading
from functools import wraps
from portable_compaction import protect

MAX_CACHE=8*1024*1024

def locked(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self.lock:return method(self,*args,**kwargs)
    return call

class CatalogCache:
    def __init__(self,path,backups):
        self.path=Path(path);self.backups=Path(backups);self.lock=threading.RLock()
        self.salt=secrets.token_hex(16);self.versions={}
        if self.path.exists() and self.path.stat().st_size>MAX_CACHE:raise ValueError('Native model cache exceeds its verified size limit.')
        self.initial=self.path.read_bytes() if self.path.exists() else None
        self.identity=None
        if self.initial is not None:
            self.backups.mkdir(parents=True,exist_ok=True)
            (self.backups/(self.salt+'.initial.dpapi')).write_bytes(protect(self.initial))

    def tag(self,catalog):
        raw=json.dumps(catalog,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        etag='better-codex-'+hashlib.sha256(self.salt.encode()+raw).hexdigest()
        return raw,etag

    @locked
    def describe(self,catalog,version):
        raw,etag=self.tag(catalog)
        self.versions[etag]=version
        # This salt binds entries to this helper launch and no other runtime.
        if len(self.versions)>64:self.versions.pop(next(iter(self.versions)))
        return raw,etag

    @locked
    def publish(self,catalog):
        if not self.path.is_file() or self.path.stat().st_size>MAX_CACHE:
            raise ValueError('Open the model menu once to initialize this session’s catalog, then retry Refresh models.')
        original=self.path.read_bytes()
        try:entry=json.loads(original)
        except ValueError:raise ValueError('Native model metadata cache could not be verified.') from None
        if not isinstance(entry,dict) or set(entry)!={'fetched_at','etag','client_version','identity','models'}:
            raise ValueError('Unknown model-cache schema; running models were retained.')
        if entry.get('etag') not in self.versions or self.versions[entry['etag']]!=entry.get('client_version') or not isinstance(entry.get('identity'),str) or not entry['identity']:
            raise ValueError('The model cache belongs to another session. Open the model menu and retry; no unrelated cache was overwritten.')
        if self.identity is not None and self.identity!=entry['identity']:
            raise ValueError('The native authentication scope changed; its metadata cache was retained.')
        if not isinstance(entry.get('models'),list):raise ValueError('Invalid native model metadata.')
        _,etag=self.describe(catalog,entry['client_version'])
        updated={**entry,'models':catalog['models'],'etag':etag,'fetched_at':datetime.now(timezone.utc).isoformat()}
        raw=json.dumps(updated,ensure_ascii=False).encode()
        if len(raw)>MAX_CACHE:raise ValueError('Model metadata exceeds the verified cache size limit.')
        self.backups.mkdir(parents=True,exist_ok=True)
        backup=self.backups/(hashlib.sha256(original).hexdigest()+'.dpapi')
        if not backup.exists():backup.write_bytes(protect(original))
        temporary=self.path.with_name(self.path.name+'.better-codex-'+secrets.token_hex(8)+'.tmp')
        try:
            with temporary.open('xb') as handle:handle.write(raw)
            if self.path.read_bytes()!=original:raise ValueError('Model metadata changed concurrently. Retry Refresh models.')
            temporary.replace(self.path)
            self.identity=entry['identity']
        finally:
            if temporary.exists():temporary.unlink()
        return original,raw

    @locked
    def restore(self,receipt):
        original,updated=receipt
        if self.path.read_bytes()!=updated:raise ValueError('Model metadata changed elsewhere; rollback backup was retained.')
        temporary=self.path.with_name(self.path.name+'.restore-'+secrets.token_hex(8)+'.tmp')
        try:
            temporary.write_bytes(original);temporary.replace(self.path)
        finally:
            if temporary.exists():temporary.unlink()

    @locked
    def restore_initial(self):
        if not self.path.exists():return
        current=self.path.read_bytes()
        try:entry=json.loads(current)
        except ValueError:return
        # Other Codex/CLI sessions may own the shared cache by now. Leave those
        # entries untouched; only restore this helper's own published metadata.
        if not isinstance(entry,dict) or entry.get('etag') not in self.versions or (self.identity is not None and entry.get('identity')!=self.identity):return
        if self.initial is not None:self.restore((self.initial,current))
        elif self.path.read_bytes()==current:self.path.unlink()
