"""External context budgets leave native metadata and source catalogs intact."""
from pathlib import Path
import copy
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'src/gateway'))
from provider_registry import public_catalog

catalog={'models':[
    {'slug':'native','context_window':1000000,'auto_compact_token_limit':800000},
    {'slug':'large','context_window':1000000},
    {'slug':'small','context_window':32000},
    {'slug':'lower','context_window':1000000,'auto_compact_token_limit':16000},
    {'slug':'disabled','context_window':1000000},
    {'slug':'retired','context_window':1000000,'better_codex_removed':True}]}
providers={'fixture':{'models':{mid:{} for mid in ('large','small','lower','retired')}}}
providers['fixture']['models']['disabled']={'enabled':False}
original=copy.deepcopy(catalog)
models={m['slug']:m for m in public_catalog(catalog,providers)['models']}
assert models['native']==catalog['models'][0]
assert models['large']['auto_compact_token_limit']==128000
assert models['large']['context_window']==1000000
assert models['small']['auto_compact_token_limit']==25600
assert models['lower']['auto_compact_token_limit']==16000
assert 'disabled' not in models and 'retired' not in models
assert catalog==original
assert public_catalog({'models':[catalog['models'][0]]})['models']==[catalog['models'][0]]
print('PASS: external budgets, smaller contexts, lower thresholds, disabled/retired filtering and unchanged native/source metadata.')
