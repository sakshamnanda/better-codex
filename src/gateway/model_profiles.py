"""Bounded, model-wide preferences supplied once per desktop request."""
from pathlib import Path
import hashlib
import json

MAX_PROFILE_BYTES = 32 * 1024
MAX_COMBINED_BYTES = 48 * 1024


def profile_text(model, settings, profiles):
    names = [settings['default']]
    specific = settings['models'].get(model)
    if specific is not None and specific not in names: names.append(specific)
    text = '\n\n'.join(profiles[name] for name in names if profiles[name])
    if len(text.encode('utf-8')) > MAX_COMBINED_BYTES:
        raise ValueError('Combined model instructions exceed 48 KiB')
    return text


def profile_diagnostics(model, settings, profiles):
    data = profile_text(model, settings, profiles).encode('utf-8')
    return {'model_profile_bytes': len(data), 'model_profile_sha256': hashlib.sha256(data).hexdigest()}


def load_profiles(directory):
    settings = json.loads((directory / 'instructions.json').read_text())
    if set(settings) != {'default', 'models'} or not isinstance(settings['models'], dict):
        raise ValueError('Invalid model instruction settings')
    known = {model['slug'] for model in json.loads((directory / 'models.json').read_text())['models']}
    if any(not isinstance(model, str) or model not in known for model in settings['models']):
        raise ValueError('Instruction profile must reference a catalog model ID')
    profiles = {}
    folder = (directory / 'instructions').resolve()
    for name in [settings['default'], *settings['models'].values()]:
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise ValueError('Instruction profile must be a relative Markdown path')
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or path.suffix != '.md':
            raise ValueError('Instruction profile path is outside its configuration folder')
        with path.open('rb') as handle: data = handle.read(MAX_PROFILE_BYTES + 1)
        if len(data) > MAX_PROFILE_BYTES or b'\0' in data:
            raise ValueError('Instruction profile must be UTF-8 text of at most 32 KiB')
        profiles[name] = data.decode('utf-8').strip()
    for model in settings['models']: profile_text(model, settings, profiles)
    return settings, profiles


def apply_profile(payload, settings, profiles):
    model = payload['model']
    original = payload.get('instructions') or ''
    if not isinstance(original, str): raise ValueError('Instructions must be text')
    text = profile_text(model, settings, profiles)
    if not text: return payload
    # Preferences precede the original instructions and do not enter chat history.
    prefix = ('Model-wide working preferences for this request; selected model: ' + model + '.\n'
              'Apply these as defaults. Explicit user/project instructions and tool permissions take precedence.\n'
              + text + '\n\nEnd model-wide preferences. Original Codex instructions follow:\n\n')
    return {**payload, 'instructions': prefix + original}
