"""Native/external profile delivery and model switching without real inference."""
from pathlib import Path
import copy
import json
import sys
import uuid

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/desktop'))
sys.path.insert(0, str(root / 'src/gateway'))
import runtime_mixed as mixed
from core import GatewayCore, GatewayError, PROJECT_WORKFLOW
from model_profiles import load_profiles, apply_profile, profile_diagnostics, profile_text, MAX_PROFILE_BYTES

capability = 'profile_fixture_capability_12345678901234567890'
gateway = GatewayCore(capability, 12345, {'gpt-6.1-sol', 'native-new-fixture'}, lambda provider: 'fixture-provider-key')
headers = [('Host', gateway.host), ('Authorization', 'Bearer native-fixture-secret'), ('Content-Type', 'application/json'), ('ChatGPT-Account-Id', 'private-fixture-account')]
path = gateway.prefix + '/backend-api/codex/responses'
original = {'instructions': 'ORIGINAL_CODEX_REQUIREMENTS', 'input': [{'role': 'user', 'content': 'AGENTS_FIXTURE_PROJECT_REQUIREMENTS'}], 'tools': []}
for model in (
    'gpt-6.1-sol',
    'nvidia/nemotron-3-ultra-550b-a55b:free',
    'space-bunny-free',
    'zai/glm-5.3-flash',
    'native-new-fixture',
):
    payload = {**copy.deepcopy(original), 'model': model}
    prepared, incoming, _ = mixed.prepare_routed_request(gateway, path, headers, json.dumps(payload).encode())
    forwarded = json.loads(prepared.body)
    # Compare exact configured text: user profiles may reference other models.
    names = [mixed.PROFILE_SETTINGS['default']]
    specific = mixed.PROFILE_SETTINGS['models'].get(model)
    if specific and specific not in names: names.append(specific)
    for name in names:
        assert mixed.PROFILES[name] in forwarded['instructions']
    diagnostic = profile_diagnostics(model, mixed.PROFILE_SETTINGS, mixed.PROFILES)
    assert diagnostic['model_profile_bytes'] == len(profile_text(model, mixed.PROFILE_SETTINGS, mixed.PROFILES).encode('utf-8'))
    assert set(diagnostic) == {'model_profile_bytes', 'model_profile_sha256'}
    assert forwarded['instructions'].count('Model-wide working preferences for this request;') == 1
    assert 'ORIGINAL_CODEX_REQUIREMENTS' in forwarded['instructions']
    assert forwarded['input'] == original['input']
    assert payload['instructions'] == original['instructions']
    if prepared.provider == 'openai':
        assert PROJECT_WORKFLOW not in forwarded['instructions']
        assert dict(prepared.headers)['authorization'] == 'Bearer native-fixture-secret'
        assert prepared.url.startswith('https://chatgpt.com/')
    else:
        assert forwarded['instructions'].count(PROJECT_WORKFLOW) == 1
        assert forwarded['instructions'].index(PROJECT_WORKFLOW) > forwarded['instructions'].index('End model-wide preferences.')
        assert 'AGENTS.md' in PROJECT_WORKFLOW and '@path references' in PROJECT_WORKFLOW and 'PROJECT_RULEBOOK.md' in PROJECT_WORKFLOW
        assert 'before your final response here' in PROJECT_WORKFLOW and 'does not grant messaging authorization' in PROJECT_WORKFLOW
        assert 'native-fixture-secret' not in prepared.body.decode()
        assert not any(name.lower() == 'chatgpt-account-id' for name, value in prepared.headers)
        # The inner external relay sanitizes again but does not append profiles.
        relay = GatewayCore(capability, 12345, set(), lambda provider: 'fixture-provider-key')
        inner = relay.prepare('POST', path, headers, prepared.body)
        assert json.loads(inner.body)['instructions'].count('Model-wide working preferences for this request;') == 1
        assert json.loads(inner.body)['instructions'].count(PROJECT_WORKFLOW) == 1
try:
    mixed.prepare_routed_request(gateway, path, [('Host', 'wrong-host'), *headers[1:]], json.dumps({**original, 'model': 'gpt-6.1-sol'}).encode())
    raise AssertionError('Untrusted caller accepted')
except GatewayError as error: assert error.status == 403

directory = root / '.local/test-work' / ('profiles-' + uuid.uuid4().hex[:8])
(directory / 'instructions').mkdir(parents=True)
(directory / 'models.json').write_text(json.dumps({'models': [{'slug': 'fixture'}]}))
(directory / 'instructions/default.md').write_text('DEFAULT_FIXTURE')
(directory / 'instructions/custom.md').write_text('SPECIFIC_FIXTURE')
settings = {'default': 'default.md', 'models': {'fixture': 'custom.md'}}
(directory / 'instructions.json').write_text(json.dumps(settings))
loaded, profiles = load_profiles(directory)
assert 'SPECIFIC_FIXTURE' in apply_profile({'model': 'fixture', 'instructions': 'original'}, loaded, profiles)['instructions']
for reference in ('../models.json', '../outside.md'):
    settings['models']['fixture'] = reference
    (directory / 'instructions.json').write_text(json.dumps(settings))
    try: load_profiles(directory); raise AssertionError('Outside profile accepted')
    except ValueError: pass
settings['models']['fixture'] = 'custom.md'
(directory / 'instructions.json').write_text(json.dumps(settings))
(directory / 'instructions/custom.md').write_bytes(b'x' * 26328)
loaded, profiles = load_profiles(directory)
assert profiles['custom.md'] in apply_profile({'model': 'fixture'}, loaded, profiles)['instructions']
(directory / 'instructions/custom.md').write_bytes(b'x' * (MAX_PROFILE_BYTES + 1))
try: load_profiles(directory); raise AssertionError('Oversized profile accepted')
except ValueError: pass
(directory / 'instructions/default.md').write_bytes(b'd' * (MAX_PROFILE_BYTES - 1))
(directory / 'instructions/custom.md').write_bytes(b'x' * (MAX_PROFILE_BYTES - 1))
try: load_profiles(directory); raise AssertionError('Oversized combined profiles accepted at startup')
except ValueError: pass
print('PASS: profiles delivered once to native and external models, switching/fallback, project/history preservation, native credential isolation, caller checks and bounded profile paths.')
