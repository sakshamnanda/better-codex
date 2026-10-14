"""Read provider metadata; never infer, persist private responses or guess limits."""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

EFFORTS = ('none','minimal','low','medium','high','xhigh','max','ultra')
MODEL_ID = re.compile(r'(?:~?[A-Za-z0-9][A-Za-z0-9_.:/~\-]{0,255}|@preset/[A-Za-z0-9][A-Za-z0-9_-]{0,127})')
MAX_METADATA = 8 * 1024 * 1024

def valid_model_id(value, provider):
    return isinstance(value,str) and MODEL_ID.fullmatch(value) is not None and (not value.startswith(('@preset/','~')) or provider=='openrouter')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Metadata redirects are not accepted.')

def get_json(url,key):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.hostname=='chatgpt.com':
        raise ValueError('Metadata requires a configured external HTTPS provider.')
    headers={'Accept':'application/json','User-Agent':'Better-Codex-Provider-Metadata/1'}
    if key:headers['Authorization']='Bearer '+key
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(urllib.request.Request(url,headers=headers,method='GET'),timeout=20) as response:
            data=response.read(MAX_METADATA+1)
        if len(data)>MAX_METADATA:raise ValueError('Provider metadata exceeded its size limit.')
        value=json.loads(data)
        if not isinstance(value,dict):raise ValueError('Provider metadata must be a JSON object.')
        return value
    except urllib.error.HTTPError as error:
        raise ValueError({401:'Provider metadata requires a valid saved API key.',403:'This key cannot read the requested model or preset metadata.',
            404:'The provider did not publish metadata for this model or preset.',429:'Provider metadata rate limit reached; retry later.'}.get(error.code,'The provider could not return model metadata.')) from None
    except (OSError,UnicodeError,json.JSONDecodeError):
        raise ValueError('Could not read provider metadata; retry or choose Customize.') from None

def number(value):
    return value if type(value) is int and 1<=value<=4_194_304 else None

def mapping(value):
    return value if isinstance(value,dict) else {}

def entry_metadata(entry):
    top=mapping(entry.get('top_provider'));limit=mapping(entry.get('limit'));caps=mapping(entry.get('capabilities'))
    context=number(entry.get('context_length')) or number(entry.get('context_window')) or number(top.get('context_length')) or number(limit.get('context'))
    output=number(entry.get('max_completion_tokens')) or number(entry.get('max_output_tokens')) or number(top.get('max_completion_tokens')) or number(limit.get('output'))
    reasoning=mapping(caps.get('reasoning') or entry.get('reasoning'))
    values=reasoning.get('effort_values') or reasoning.get('supported_efforts') or entry.get('supported_reasoning_efforts')
    if values is None and isinstance(entry.get('variants'),dict):values=list(entry['variants'])
    levels=[v for v in EFFORTS if isinstance(values,list) and v in values] or None
    tools=caps.get('supports_tool_calling') if type(caps.get('supports_tool_calling')) is bool else entry.get('tool_call')
    if type(tools) is not bool:
        params=entry.get('supported_parameters')
        tools=('tools' in params) if isinstance(params,list) else None
    defaults=mapping(entry.get('default_parameters'))
    default=mapping(defaults.get('reasoning')).get('effort') or reasoning.get('default_effort') or entry.get('default_reasoning_effort')
    return {'context':context,'output':output,'efforts':levels,'tools':tools if type(tools) is bool else None,
        'default_effort':default if levels and default in levels else None}

def combine(entries):
    if not entries:raise ValueError('The provider did not publish usable model metadata.')
    context=min(e['context'] for e in entries) if all(e['context'] for e in entries) else None
    output=min(e['output'] for e in entries) if all(e['output'] for e in entries) else None
    levels=[v for v in EFFORTS if all(e['efforts'] and v in e['efforts'] for e in entries)] or None
    tools=all(e['tools'] for e in entries) if all(type(e['tools']) is bool for e in entries) else None
    defaults={e.get('default_effort') for e in entries}
    default=next(iter(defaults)) if len(defaults)==1 else None
    return {'context':context,'output':output,'efforts':levels,'tools':tools,'default_effort':default if levels and default in levels else None}

def api_base(endpoint):
    parsed=urlsplit(endpoint)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.hostname=='chatgpt.com':
        raise ValueError('Use a valid external HTTPS provider URL.')
    path=re.sub(r'/(?:responses|chat/completions)/?$','',parsed.path)
    return urlunsplit((parsed.scheme,parsed.netloc,path.rstrip('/'),'',''))

def discover(provider,definition,model_id,key,read=get_json):
    if not valid_model_id(model_id,provider):raise ValueError('Enter a valid model ID, or an OpenRouter @preset/slug.')
    base=api_base(definition['endpoint']);host=urlsplit(base).hostname
    resolved=[model_id];preset_config={};notes=[]
    if model_id.startswith('@preset/'):
        if host!='openrouter.ai':raise ValueError('Preset discovery requires the configured OpenRouter endpoint; choose Customize for a proxy.')
        if not key:raise ValueError('Save an OpenRouter key before fetching a private preset.')
        value=read(base+'/presets/'+quote(model_id[8:],safe=''),key)
        preset=mapping(value.get('data',value))
        version=preset.get('designated_version') or preset.get('current_version') or preset.get('version') or preset
        if not isinstance(version,dict) or preset.get('status') not in {None,'active'}:raise ValueError('Preset metadata did not include an active configuration.')
        preset_config=version.get('config') or preset.get('config') or {}
        if not isinstance(preset_config,dict):raise ValueError('Preset metadata did not include its active configuration.')
        models=preset_config.get('models') or ([preset_config['model']] if preset_config.get('model') else [])
        fallbacks=preset_config.get('fallbacks') or []
        if not isinstance(models,list) or not isinstance(fallbacks,list):raise ValueError('Preset model selection is not a fixed model list; choose Customize.')
        candidates=models+[v.get('model') if isinstance(v,dict) else v for v in fallbacks]
        if any(not isinstance(mid,str) for mid in candidates):raise ValueError('Preset model selection is not a fixed model list; choose Customize.')
        resolved=list(dict.fromkeys(candidates))
        if not 1<=len(resolved)<=8 or any(not valid_model_id(mid,provider) or mid.startswith('@') or mid in {'openrouter/auto','openrouter/free'} for mid in resolved):
            raise ValueError('Preset model selection is dynamic or unavailable; choose Customize instead of guessed limits.')
        if len(resolved)>1:notes.append('Uses the lowest reported limits shared by the preset models.')
    parsed=[];label=model_id;variant=False
    if provider=='merge' and host=='api-gateway.merge.dev':
        value=read('https://api-gateway.merge.dev/v1/models?'+urlencode({'model':model_id}),key)
        entry=value.get('data',value)
        if isinstance(entry,list):entry=next((e for e in entry if isinstance(e,dict) and e.get('model')==model_id),None)
        if not isinstance(entry,dict) or entry.get('model')!=model_id:raise ValueError('No matching model metadata was returned.')
        vendors=mapping(entry.get('vendors'))
        parsed=[entry_metadata(v) for v in vendors.values() if isinstance(v,dict) and v.get('availability_status') in {None,'available'} and mapping(v.get('capabilities')).get('supports_tool_calling') is not False]
        label=entry.get('display_name') or model_id
        notes.append('Uses the lowest published limits across available tool-capable vendors; actual routing can impose further limits.')
    elif provider=='opencode' and host=='opencode.ai':
        value=read('https://opencode.ai/console/api/config',key)
        config=mapping(value.get('config',value))
        providers=mapping(config.get('provider') or config.get('providers'))
        entry=mapping(mapping(providers.get('opencode')).get('models')).get(model_id)
        if not isinstance(entry,dict):raise ValueError('OpenCode did not publish this model metadata; choose Customize.')
        parsed=[entry_metadata(entry)];label=entry.get('name') or model_id;variant=bool(parsed[0]['efforts'])
    else:
        for mid in resolved:
            value=read(base+'/models?'+urlencode({'q':mid}),key)
            entries=value.get('data',[])
            if isinstance(entries,dict):entries=[entries]
            if not isinstance(entries,list):raise ValueError('Provider model metadata has an unexpected shape.')
            entry=next((e for e in entries if isinstance(e,dict) and (e.get('id')==mid or e.get('model')==mid)),None)
            if not entry:raise ValueError('No matching model metadata was returned; choose Customize.')
            parsed.append(entry_metadata(entry))
            if len(resolved)==1 and not model_id.startswith('@'):label=entry.get('name') or mid
    result=combine(parsed)
    cap=number(preset_config.get('max_tokens')) or number(preset_config.get('max_completion_tokens')) or number(preset_config.get('max_output_tokens'))
    if cap and result['output']:result['output']=min(result['output'],cap)
    requested=mapping(preset_config.get('reasoning')).get('effort')
    default=requested if result['efforts'] and requested in result['efforts'] else result['default_effort']
    if default is None and result['efforts']:
        default=result['efforts'][0]
        notes.append('No default effort was reported; the initial selection uses the first published level. You can change it.')
    if provider=='openrouter':notes.append('Published model limits can differ from the endpoint selected by routing or account restrictions.')
    if result['efforts'] is None:notes.append('Exact reasoning levels were not reported. Provider default sends no reasoning override.')
    if not result['context'] or not result['output']:notes.append('Some limits were not reported. Choose Customize to supply them.')
    if result['tools'] is False:notes.append('The provider reports no tool support for this model.')
    return {**result,'label':label if isinstance(label,str) and len(label)<=160 else model_id,
        'default_effort':default,'resolved_models':resolved,'notes':notes,'send_variant':variant}
