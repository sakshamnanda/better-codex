"""Bounded cache ownership, encrypted rollback and unrelated-session protection."""
from pathlib import Path
import json
import sys
import uuid
import hashlib

root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'src/desktop'));sys.path.insert(0,str(root/'src/gateway'))
from catalog_refresh import CatalogCache
from portable_compaction import protect

scratch=root/'.local/test-work'/('catalog-refresh-'+uuid.uuid4().hex[:8]);scratch.mkdir(parents=True)
path=scratch/'models_cache.json';backups=scratch/'backups'
old={'models':[{'slug':'owned/original','context_window':100000}]}
new={'models':[{'slug':'owned/new','context_window':65536}]}
ordinary={'fetched_at':'2026-10-15T00:00:00Z','etag':'owned-other-session','client_version':'0.162.0','identity':'owned-scope-fixture','models':old['models']}
path.write_text(json.dumps(ordinary));before=path.read_bytes()
cache=CatalogCache(path,backups)
try:cache.publish(new);raise AssertionError('Unrelated cache overwritten')
except ValueError:pass
assert path.read_bytes()==before
_,etag=cache.describe(old,'0.162.0');entry={**ordinary,'etag':etag};path.write_text(json.dumps(entry));owned=path.read_bytes()
receipt=cache.publish(new);updated=json.loads(path.read_text())
assert updated['identity']==entry['identity'] and updated['client_version']==entry['client_version']
assert updated['models']==new['models'] and updated['etag']!=etag
sealed=(backups/(hashlib.sha256(owned).hexdigest()+'.dpapi')).read_bytes();assert owned not in sealed and protect(sealed,decrypt=True)==owned
cache.restore(receipt);assert path.read_bytes()==owned
receipt=cache.publish(new);path.write_text(json.dumps(ordinary))
try:cache.restore(receipt);raise AssertionError('Concurrent cache change overwritten')
except ValueError:pass
cache.restore_initial();assert json.loads(path.read_text())==ordinary
path.write_text(json.dumps(entry));cache.publish(new);cache.restore_initial();assert path.read_bytes()==before
for mutation in ({**entry,'client_version':'different-version'},{**entry,'identity':''},{**entry,'identity':'other-scope'},{**entry,'extra':'unknown-schema'}):
 path.write_text(json.dumps(mutation));value=path.read_bytes()
 try:cache.publish(new);raise AssertionError('Unknown scope/schema accepted')
 except ValueError:pass
 assert path.read_bytes()==value
print('PASS: metadata refresh retains cache identity/version, requires this helper’s catalog proof, encrypts rollback, restores original metadata and refuses unrelated/concurrent/schema changes. No auth, chat database, app or network used.')
