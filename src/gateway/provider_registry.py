"""One public registry for routing, provider labels and model capabilities."""
from pathlib import Path
import json
import re
from urllib.parse import urlsplit


def require_nanogpt(provider_id, provider):
    if (provider_id != 'nanogpt' or provider['adapter'] != 'chat_completions' or
                  provider['endpoint'] not in {'https://nano-gpt.com/api/v1/chat/completions', 'https://api.nano-gpt.com/api/v1/chat/completions'}):
        raise ValueError('These routing options are supported only for NanoGPT')


def validate_upstream(provider_id, provider, value):
    if not isinstance(value, str) or (value and not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', value)):
        raise ValueError('Invalid upstream provider ID')
    if value:require_nanogpt(provider_id, provider)


def validate_service_tier(provider_id, provider, value):
    if not isinstance(value, str) or value not in {'', 'auto', 'default', 'flex', 'fast', 'priority'}:
        raise ValueError('Invalid service tier')
    if value:require_nanogpt(provider_id, provider)

def public_catalog(catalog,providers=None):
    """Keep retired metadata for instruction mappings, never advertise it."""
    external={mid for p in (providers or {}).values() for mid in p['models']}
    disabled={mid for p in (providers or {}).values() for mid,route in p['models'].items()
              if not p.get('enabled',True) or not route.get('enabled',True)}
    models=[]
    for model in catalog['models']:
        if model.get('better_codex_removed') or model['slug'] in disabled:continue
        entry={k:v for k,v in model.items() if not k.startswith('better_codex_')}
        if model['slug'] in external:
            # Use the native checkpoint flow before repeated history gets costly.
            entry['auto_compact_token_limit']=min(model['context_window']*80//100,
                model.get('better_codex_auto_compact_token_limit') or
                model.get('auto_compact_token_limit') or model['context_window']*80//100)
        models.append(entry)
    return {**catalog,'models':models}


def load_registry(directory):
    providers = json.loads((directory / 'providers.json').read_text(encoding='utf-8'))
    catalog = json.loads((directory / 'models.json').read_text(encoding='utf-8'))['models']
    metadata = {model['slug']: model for model in catalog}
    if len(metadata) != len(catalog) or not isinstance(providers, dict):
        raise ValueError('Duplicate catalog IDs or invalid provider registry')
    models, routes, seen = {}, {}, set()
    for provider_id, provider in providers.items():
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', provider_id) or provider_id == 'openai':
            raise ValueError('Invalid external provider ID; openai is reserved for ChatGPT')
        required={'label','adapter','endpoint','default_model','models'}
        if not required<=set(provider) or set(provider)-required-{'enabled'}:
            raise ValueError('Unexpected provider configuration fields')
        if type(provider.get('enabled',True)) is not bool:raise ValueError('Provider enabled must be a boolean')
        if not isinstance(provider['label'], str) or not 1<=len(provider['label'].strip())<=160 or any(c in provider['label'] for c in '\r\n\0'):
            raise ValueError('Provider label is required')
        endpoint = urlsplit(provider['endpoint'])
        if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.hostname == 'chatgpt.com':
            raise ValueError('External endpoint must be a fixed HTTPS URL without credentials or query')
        adapter = provider['adapter']
        if adapter not in {'responses', 'chat_completions', 'opencode'}:
            raise ValueError('Unknown adapter; implement and verify its protocol first')
        if adapter == 'opencode' and (provider_id != 'opencode' or provider['endpoint'] != 'https://opencode.ai/zen/v1/chat/completions'):
            raise ValueError('The genuine OpenCode adapter is restricted to OpenCode Zen')
        if not isinstance(provider['models'], dict) or (provider['default_model'] not in provider['models'] if provider['models'] else provider['default_model'] != ''):
            raise ValueError('Provider default must be an explicitly configured model')
        for model_id, settings in provider['models'].items():
            if model_id in seen or model_id not in metadata:
                raise ValueError('Model must have unique routing and catalog metadata')
            seen.add(model_id)
            if not isinstance(settings, dict) or set(settings) - {'output_limit', 'send_variant','metadata_mode','reasoning_mode','enabled','upstream_provider','service_tier'}:
                raise ValueError('Unexpected model route configuration')
            validate_upstream(provider_id, provider, settings.get('upstream_provider', ''))
            validate_service_tier(provider_id, provider, settings.get('service_tier', ''))
            if type(settings.get('enabled',True)) is not bool:raise ValueError('Model enabled must be a boolean')
            if settings.get('metadata_mode','custom') not in {'provider','custom'} or settings.get('reasoning_mode','explicit') not in {'explicit','provider_default'}:
                raise ValueError('Invalid model metadata mode')
            limit = settings.get('output_limit', 4096)
            if type(limit) is not int or not 1 <= limit <= 1048576:
                raise ValueError('Invalid output token limit')
            if type(settings.get('send_variant', False)) is not bool or (settings.get('send_variant') and adapter != 'opencode'):
                raise ValueError('Variants are specific to the genuine OpenCode adapter')
            model = metadata[model_id]
            if model.get('better_codex_removed') or model.get('better_codex_provider',provider_id)!=provider_id:
                raise ValueError('Retired models cannot be routed or reassigned')
            compact=model.get('better_codex_auto_compact_token_limit')
            if compact is not None and (type(compact) is not int or not 1 <= compact <= 4_194_304):
                raise ValueError('Invalid auto-compact token limit')
            levels = {entry['effort'] for entry in model['supported_reasoning_levels']}
            default = model['default_reasoning_level']
            if not levels or default not in levels or not levels <= {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}:
                raise ValueError('Invalid model effort metadata')
            if settings.get('reasoning_mode')=='provider_default' and (levels!={'none'} or default!='none' or settings.get('send_variant')):
                raise ValueError('Provider default must not override reasoning')
            if adapter == 'opencode' and (type(model['context_window']) is not int or model['context_window'] < limit or (model['context_window']==limit and settings.get('metadata_mode')!='provider')):
                raise ValueError('OpenCode needs a valid context limit')
            if provider.get('enabled',True) and settings.get('enabled',True):
                models[model_id] = {**settings, 'output_limit': limit, 'provider': provider_id, 'metadata': model}
                routes[model_id] = (provider_id, provider['endpoint'], default, levels)
        active=[mid for mid,settings in provider['models'].items() if settings.get('enabled',True)]
        if active and provider['default_model'] not in active:provider['default_model']=active[0]
    return providers, models, routes


root = Path(__file__).resolve().parent.parent
config = root if (root / 'providers.json').exists() else root.parent / 'config'
PROVIDERS, MODELS, ROUTES = load_registry(config)
