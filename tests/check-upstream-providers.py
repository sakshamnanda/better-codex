"""NanoGPT upstream discovery, settings round trips and request isolation; offline."""
from pathlib import Path
import copy
import json
import sys
import tempfile

root=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(root/'src/gateway'),str(root/'src/desktop')]
from provider_registry import load_registry
from model_metadata import discover_upstreams
from api_settings import prepare_configuration
from core import GatewayCore
from chat_bridge import prepare_chat

providers=json.loads((root/'config/providers.json').read_text())
catalog=json.loads((root/'config/models.json').read_text())
mid=providers['nanogpt']['default_model']
definition=providers['nanogpt']
calls=[]
def read(url,key):
    calls.append((url,key))
    if url.endswith('/models?detailed=true'):
        return {'data':[{'id':'unrelated','supported_service_tiers':['fast']},{'id':mid,'supported_service_tiers':['flex','priority']}]}
    return {'supportsProviderSelection':True,'providers':[
        {'provider':'kitani','available':True,'private_unused':'fixture'},
        {'provider':'arnict','available':False}]}
info=discover_upstreams('nanogpt',definition,mid,read)
assert info=={'supported':True,'providers':[{'id':'kitani','available':True},{'id':'arnict','available':False}],'service_tiers':['flex','priority']}
assert calls==[('https://nano-gpt.com/api/models/z-ai%2Fglm-5.3-flash-uncensored/providers',''),('https://nano-gpt.com/api/v1/models?detailed=true','')]
assert discover_upstreams('nanogpt',definition,mid,lambda *_:{'supportsProviderSelection':False})=={'supported':False,'providers':[],'service_tiers':[]}
for bad in ({'supportsProviderSelection':'true'},
            {'supportsProviderSelection':True,'providers':[{'provider':'bad\r\nheader','available':True}]}):
    try:discover_upstreams('nanogpt',definition,mid,lambda *_:bad);raise AssertionError('Malformed discovery accepted')
    except ValueError:pass
for pid,p in [('merge',providers['merge']),('nanogpt',{**definition,'endpoint':'https://other.example/v1/chat/completions'})]:
    try:discover_upstreams(pid,p,mid,read);raise AssertionError('Unsupported discovery accepted')
    except ValueError:pass
assert len(calls)==2

metadata={m['slug']:m for m in catalog['models']}
rows=[{'id':m,'provider':pid,'label':metadata[m]['display_name'],'context':metadata[m]['context_window'],
       'output':route.get('output_limit',4096),'efforts':[e['effort'] for e in metadata[m]['supported_reasoning_levels']],
       'default_effort':metadata[m]['default_reasoning_level']}
      for pid,p in providers.items() for m,route in p['models'].items()]
request={'providers':{pid:{k:p[k] for k in ('label','adapter','endpoint','default_model')} for pid,p in providers.items()},'models':rows}
row=next(r for r in rows if r['id']==mid)
row['upstream_provider']='kitani'
row['service_tier']='flex'
p,c=prepare_configuration(request,providers,catalog)
assert p['nanogpt']['models'][mid]['upstream_provider']=='kitani'
assert p['nanogpt']['models'][mid]['service_tier']=='flex'
preserved,_=prepare_configuration({**request,'models':[{k:v for k,v in r.items() if k not in {'upstream_provider','service_tier'}} for r in rows]},p,c)
assert preserved['nanogpt']['models'][mid]['upstream_provider']=='kitani'
assert preserved['nanogpt']['models'][mid]['service_tier']=='flex'

with tempfile.TemporaryDirectory(dir=root/'.local',prefix='upstream-check-') as directory:
    folder=Path(directory)
    (folder/'models.json').write_text(json.dumps(c))
    def registry(value):
        (folder/'providers.json').write_text(json.dumps(value))
        return load_registry(folder)
    pinned=registry(p)
    gateway=GatewayCore('upstream_fixture_capability_12345678901234567890',12345,set(),lambda _: 'dummy-provider-key',registry=pinned)
    headers=[('Host',gateway.host),('Content-Type','application/json'),('Authorization','Bearer dummy-native-key'),('X-Provider','caller-spoof')]
    def prepare(g,model):
        return g.prepare('POST',g.prefix+'/backend-api/codex/responses',headers,json.dumps({'model':model,'input':[]}).encode())
    assert dict(prepare(gateway,mid).headers)['X-Provider']=='kitani'
    assert prepare_chat(json.loads(prepare(gateway,mid).body))['service_tier']=='flex'
    other=providers['merge']['default_model']
    assert 'X-Provider' not in dict(prepare(gateway,other).headers)
    assert 'service_tier' not in json.loads(prepare(gateway,other).body)
    row['upstream_provider']=''
    row['service_tier']=''
    cleared,cc=prepare_configuration(request,p,c)
    assert 'upstream_provider' not in cleared['nanogpt']['models'][mid]
    assert 'service_tier' not in cleared['nanogpt']['models'][mid]
    fresh=GatewayCore('upstream_fixture_capability_12345678901234567890',12345,set(),lambda _: 'dummy-provider-key',registry=registry(cleared))
    assert 'X-Provider' not in dict(prepare(fresh,mid).headers)
    assert 'service_tier' not in prepare_chat(json.loads(prepare(fresh,mid).body))
    assert dict(prepare(gateway,mid).headers)['X-Provider']=='kitani'
    assert json.loads(prepare(gateway,mid).body)['service_tier']=='flex'
    for tier in ('auto','default','flex','fast','priority'):
        variant=copy.deepcopy(p);variant['nanogpt']['models'][mid]['service_tier']=tier
        g=GatewayCore('tier_fixture_capability_12345678901234567890',12345,set(),lambda _:'dummy-provider-key',registry=registry(variant))
        assert prepare_chat(json.loads(prepare(g,mid).body))['service_tier']==tier
    for value in ('unsupported',None,[]):
        invalid=copy.deepcopy(p);invalid['nanogpt']['models'][mid]['service_tier']=value
        try:registry(invalid);raise AssertionError('Invalid tier accepted')
        except ValueError:pass
    for value in ('bad\nheader',None,{'only':['kitani']}):
        invalid=copy.deepcopy(p);invalid['nanogpt']['models'][mid]['upstream_provider']=value
        try:registry(invalid);raise AssertionError('Invalid upstream accepted')
        except ValueError:pass
    invalid=copy.deepcopy(p);invalid['merge']['models'][other]['upstream_provider']='kitani'
    try:registry(invalid);raise AssertionError('Other provider accepted upstream pin')
    except ValueError:pass
    invalid=copy.deepcopy(p);invalid['merge']['models'][other]['service_tier']='priority'
    try:registry(invalid);raise AssertionError('Other provider accepted service tier')
    except ValueError:pass
    invalid_request=copy.deepcopy(request)
    next(r for r in invalid_request['models'] if r['provider']=='merge')['upstream_provider']='kitani'
    try:prepare_configuration(invalid_request,p,c);raise AssertionError('Other provider settings accepted upstream pin')
    except ValueError:pass
print('PASS: public provider/tier discovery, settings save/retain/clear, all service tiers, pinned requests, automatic routing and NanoGPT-only isolation.')
