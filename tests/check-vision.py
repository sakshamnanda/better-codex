"""Inline images survive both gateway hops without native credentials; offline."""
import base64
import copy
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/gateway'))
from core import GatewayCore, GatewayError
from chat_bridge import prepare_chat
from provider_registry import MODELS, PROVIDERS, public_catalog

image = 'data:image/png;base64,' + base64.b64encode(bytes.fromhex('89504e470d0a1a0a') + b'fixture').decode()
reads = []
gateway = GatewayCore('vision_fixture_capability_12345678901234567890', 12345, {'native-fixture'},
                      lambda pid: reads.append(pid) or 'provider-fixture')
headers = [('Host', gateway.host), ('Authorization', 'Bearer native-private-fixture'),
           ('Content-Type', 'application/json'), ('ChatGPT-Account-Id', 'private-account-fixture')]
path = gateway.prefix + '/backend-api/codex/responses'

def prepare(payload):
    return gateway.prepare('POST', path, headers, json.dumps(payload).encode())

vision = [mid for mid, route in MODELS.items() if 'image' in route['metadata']['input_modalities']]
assert 'glm-5.3-flash-abliterated' in vision and len(vision) == 9
catalog = public_catalog(json.loads((root / 'config/models.json').read_text()), PROVIDERS)
assert all('image' in next(m for m in catalog['models'] if m['slug'] == mid)['input_modalities'] for mid in vision)
for mid in vision:
    payload = {'model': mid, 'input': [{'role': 'user', 'content': [
        {'type': 'input_text', 'text': 'First'}, {'type': 'input_image', 'image_url': image, 'detail': 'original'},
        {'type': 'input_text', 'text': 'Second'}, {'type': 'input_image', 'image_url': image}]}]}
    first = prepare(payload)
    second = prepare(json.loads(first.body))
    assert json.loads(first.body)['input'] == json.loads(second.body)['input']
    assert dict(second.headers)['Authorization'] == 'Bearer provider-fixture'
    assert 'native-private-fixture' not in second.body.decode()
    chat = prepare_chat(json.loads(second.body), stream=True)
    parts = chat['messages'][-1]['content']
    assert [p['type'] for p in parts] == ['text', 'image_url', 'text', 'image_url']
    assert parts[1]['image_url'] == {'url': image, 'detail': 'high'}
    assert parts[3]['image_url'] == {'url': image}

payload = {'model': 'glm-5.3-flash-abliterated', 'input': [{'role': 'user', 'content': [
    {'type': 'input_image', 'image_url': image}]}]}
bad_parts = [
    {'type': 'input_image', 'image_url': 'https://chatgpt.com/private-fixture'},
    {'type': 'input_image', 'file_id': 'native-file-fixture'},
    {'type': 'input_image', 'image_url': 'data:image/png;base64,A'},
    {'type': 'input_image', 'image_url': 'data:image/svg+xml;base64,AAAA'},
    {'type': 'input_image', 'image_url': image, 'detail': 'unknown'},
    {'type': 'input_image', 'image_url': image, 'detail': []},
    {'type': 'input_image', 'image_url': image, 'private': 'fixture'},
]
for part in bad_parts:
    bad = copy.deepcopy(payload)
    bad['input'][0]['content'] = [part]
    count = len(reads)
    try:
        prepare(bad)
    except GatewayError:
        assert len(reads) == count
    else:
        raise AssertionError('Unsafe image accepted')
    try:
        prepare_chat(bad)
    except GatewayError:
        pass
    else:
        raise AssertionError('Unsafe bridge image accepted')
bad = copy.deepcopy(payload)
bad['input'][0]['role'] = 'assistant'
try:
    prepare(bad)
except GatewayError:
    pass
else:
    raise AssertionError('Assistant image accepted')
for mid in set(MODELS) - set(vision):
    bad = {**payload, 'model': mid}
    count = len(reads)
    try:
        prepare(bad)
    except GatewayError:
        assert len(reads) == count
    else:
        raise AssertionError('Text-only model accepted an image')
native = prepare({**payload, 'model': 'native-fixture'})
assert native.provider == 'openai' and image in native.body.decode()
assert prepare_chat({'model': 'fixture', 'input': [{'role': 'user', 'content': [
    {'type': 'input_text', 'text': 'one'}, {'type': 'input_text', 'text': 'two'}]}]})['messages'][0]['content'] == 'one\ntwo'
print('PASS: nine vision routes, both hops, image ordering/detail, native routing and rejection before credentials.')
