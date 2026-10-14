"""One public registry for routing, provider labels and model capabilities."""
from pathlib import Path
import json
import re
from urllib.parse import urlsplit


def load_registry(directory):
    providers = json.loads((directory / 'providers.json').read_text())
    catalog = json.loads((directory / 'models.json').read_text())['models']
    metadata = {model['slug']: model for model in catalog}
    if len(metadata) != len(catalog) or not isinstance(providers, dict) or not providers:
        raise ValueError('Duplicate catalog IDs or invalid provider registry')
    models, routes = {}, {}
    for provider_id, provider in providers.items():
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', provider_id) or provider_id == 'openai':
            raise ValueError('Invalid external provider ID; openai is reserved for ChatGPT')
        if set(provider) != {'label', 'adapter', 'endpoint', 'default_model', 'models'}:
            raise ValueError('Unexpected provider configuration fields')
        if not isinstance(provider['label'], str) or not provider['label'].strip():
            raise ValueError('Provider label is required')
        endpoint = urlsplit(provider['endpoint'])
        if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.hostname == 'chatgpt.com':
            raise ValueError('External endpoint must be a fixed HTTPS URL without credentials or query')
        adapter = provider['adapter']
        if adapter not in {'responses', 'chat_completions', 'opencode'}:
            raise ValueError('Unknown adapter; implement and verify its protocol first')
        if adapter == 'opencode' and (provider_id != 'opencode' or provider['endpoint'] != 'https://opencode.ai/zen/v1/chat/completions'):
            raise ValueError('The genuine OpenCode adapter is restricted to OpenCode Zen')
        if not isinstance(provider['models'], dict) or provider['default_model'] not in provider['models']:
            raise ValueError('Provider default must be an explicitly configured model')
        for model_id, settings in provider['models'].items():
            if model_id in models or model_id not in metadata:
                raise ValueError('Model must have unique routing and catalog metadata')
            if not isinstance(settings, dict) or set(settings) - {'output_limit', 'send_variant'}:
                raise ValueError('Unexpected model route configuration')
            limit = settings.get('output_limit', 4096)
            if type(limit) is not int or not 1 <= limit <= 1048576:
                raise ValueError('Invalid output token limit')
            if type(settings.get('send_variant', False)) is not bool or (settings.get('send_variant') and adapter != 'opencode'):
                raise ValueError('Variants are specific to the genuine OpenCode adapter')
            model = metadata[model_id]
            levels = {entry['effort'] for entry in model['supported_reasoning_levels']}
            default = model['default_reasoning_level']
            if not levels or default not in levels or not levels <= {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}:
                raise ValueError('Invalid model effort metadata')
            if adapter == 'opencode' and (type(model['context_window']) is not int or model['context_window'] <= limit):
                raise ValueError('OpenCode needs a valid context limit')
            models[model_id] = {**settings, 'output_limit': limit, 'provider': provider_id, 'metadata': model}
            routes[model_id] = (provider_id, provider['endpoint'], default, levels)
    return providers, models, routes


root = Path(__file__).resolve().parent.parent
config = root if (root / 'providers.json').exists() else root.parent / 'config'
PROVIDERS, MODELS, ROUTES = load_registry(config)
