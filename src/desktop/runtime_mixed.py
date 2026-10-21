"""Signed desktop replica: native ChatGPT routing plus the proven external service."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from contextlib import nullcontext
from collections import OrderedDict
import hashlib
import http.client
import importlib.util
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
BASE = ROOT
SUPPORT = ROOT / 'support'
GATEWAY = BASE / 'gateway' if (BASE / 'gateway').exists() else BASE.parent / 'gateway'
sys.path.insert(0, str(GATEWAY))
from core import GatewayCore, GatewayError, HOP_HEADERS, MAX_BODY, decode_body
spec = importlib.util.spec_from_file_location('external_stream_adapter', GATEWAY / 'provider_relay.py')
external_adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(external_adapter)

from provider_registry import ROUTES, config
from model_profiles import load_profiles, apply_profile, profile_diagnostics
from portable_compaction import COMPACTION_MODEL, checkpoint_events
PROFILE_SETTINGS, PROFILES = load_profiles(config)
EXTERNAL = set(ROUTES)
DUMMY = 'sk-offline-local-test-only-no-real-provider-access'
EVENTS = []
LOCK = threading.Lock()
PLAINTEXT_HANDOFFS = OrderedDict()
HANDOFF_LOCK = threading.Lock()
FAILED_EXTERNAL_STREAMS = OrderedDict()
FAILURE_LOCK = threading.Lock()


def desktop_external_event(event):
    """Keep external reasoning out of the desktop stream and saved history."""
    # Content-part completion repeats reasoning even when its deltas are hidden.
    if (event.get('type', '').startswith('response.reasoning')
            or event.get('item', {}).get('type') == 'reasoning'
            or event.get('part', {}).get('type') in {'reasoning_text', 'summary_text'}):
        return None
    response = event.get('response')
    if isinstance(response, dict) and isinstance(response.get('output'), list):
        return {**event, 'response': {**response, 'output': [item for item in response['output'] if item.get('type') != 'reasoning']}}
    return event


def remember_external_handoffs(event):
    """Recognize only plaintext arguments actually returned by external tools."""
    if event.get('type') == 'response.output_item.done': items = [event.get('item')]
    elif event.get('type') == 'response.completed':
        response = event.get('response')
        items = response.get('output', []) if isinstance(response, dict) else []
    else: return
    if not isinstance(items, list): return
    for item in items:
        if (not isinstance(item, dict) or item.get('type') != 'function_call'
                or item.get('namespace') not in {None, 'collaboration', 'multi_agent_v1', 'functions'}
                or item.get('name') not in {'spawn_agent', 'followup_task', 'send_message', 'send_input'}
                or item.get('encrypted_function_args') is not None):
            continue
        try: message = json.loads(item.get('arguments', '')).get('message')
        except (ValueError, TypeError, AttributeError): continue
        if not isinstance(message, str) or not message.strip(): continue
        digest = hashlib.sha256(message.encode('utf-8')).digest()
        with HANDOFF_LOCK:
            PLAINTEXT_HANDOFFS[digest] = None
            PLAINTEXT_HANDOFFS.move_to_end(digest)
            # Retained external tool history restores these hashes after a restart.
            if len(PLAINTEXT_HANDOFFS) > 1024: PLAINTEXT_HANDOFFS.popitem(last=False)


def normalize_agent_handoffs(history):
    if not isinstance(history, list): return history
    normalized = []
    for item in history:
        if isinstance(item, dict) and item.get('type') == 'agent_message' and isinstance(item.get('content'), list):
            content = []
            for part in item['content']:
                text = part.get('encrypted_content') if isinstance(part, dict) and part.get('type') == 'encrypted_content' else None
                with HANDOFF_LOCK:
                    known = isinstance(text, str) and hashlib.sha256(text.encode('utf-8')).digest() in PLAINTEXT_HANDOFFS
                # The runtime labels unencrypted external tool messages as ciphertext.
                content.append({'type': 'input_text', 'text': text} if known else part)
            item = {**item, 'content': content}
        normalized.append(item)
    return normalized


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise GatewayError('Upstream redirects are not accepted', 502)


def open_upstream(url, headers, body=None, *, timeout=120):
    # Fresh TLS connection to a fixed origin; inherited proxies are ignored.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    return opener.open(urllib.request.Request(url, headers=dict(headers), data=body), timeout=timeout)


def record(event):
    with LOCK:
        if not any(item is event for item in EVENTS): EVENTS.append(event)
        temporary = SUPPORT / 'Mixed-Results.tmp'
        temporary.write_text(json.dumps({'events': EVENTS, 'real_native_authentication_required': True, 'native_auth_never_forwarded_to_external_service': True}, indent=2))
        temporary.replace(SUPPORT / 'Mixed-Results.json')


def external_headers(generation=None):
    headers = {'Authorization': 'Bearer ' + DUMMY, 'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
    if generation is not None:headers['X-Better-Codex-Generation']=generation
    return headers


def expand_subagent_models(incoming, catalog):
    """Replace the native five-model hint with the enabled picker catalog."""
    lines = ['Available model overrides (optional; inherited parent model is preferred):']
    for model in catalog['models']:
        if model.get('visibility') != 'list': continue
        efforts = ', '.join(level['effort'] + (' (default)' if level['effort'] == model['default_reasoning_level'] else '')
                            for level in model['supported_reasoning_levels'])
        line = f"- `{model['slug']}`: {model['description']} Reasoning efforts: {efforts}."
        tiers = ', '.join(tier['id'] for tier in model.get('service_tiers', []))
        if tiers: line += f' Service tiers: {tiers}.'
        lines.append(line)
    listing = '\n'.join(lines) + '\n'

    def update(tools, namespace=None):
        for tool in tools:
            if not isinstance(tool, dict): continue
            if tool.get('type') == 'namespace':
                update(tool.get('tools', []), tool.get('name'))
            elif (tool.get('type') == 'function' and tool.get('name') == 'spawn_agent'
                  and namespace in {None, 'collaboration', 'multi_agent_v1', 'functions'}):
                description = tool.get('description', '')
                if 'Available model overrides' in description:
                    description = re.sub(r'Available model overrides[^\n]*\n(?:- `[^\n]*\n)*',
                                         lambda _: listing, description, count=1)
                else: description = listing + description
                tool['description'] = description

    update(incoming.get('tools', []))
    for item in incoming.get('input', []) if isinstance(incoming.get('input'), list) else []:
        if isinstance(item, dict) and item.get('type') in {'additional_tools', 'tool_search_output'}:
            update(item.get('tools', []))


def prepare_routed_request(core, target, headers, body, profile_settings=None, profiles=None, catalog=None):
    external=core.external
    profile_settings=PROFILE_SETTINGS if profile_settings is None else profile_settings
    profiles=PROFILES if profiles is None else profiles
    # Check the actual URL, local capability, Host and bearer before parsing data.
    # GET /responses is deliberately unsupported after these shared checks.
    try: core.prepare('GET', target, headers)
    except GatewayError as error:
        if error.status != 404: raise
    encoding = next((value for name,value in headers if name.lower() == 'content-encoding'), None)
    incoming = json.loads(decode_body(body, encoding))
    if not isinstance(incoming,dict) or not isinstance(incoming.get('model'),str): raise GatewayError('Invalid Responses model')
    if catalog is not None and incoming['model'] in set(core.external) | core.native_models:
        expand_subagent_models(incoming, catalog)
        headers = [(name,value) for name,value in headers if name.lower() not in {'content-encoding','content-length'}]
        body = json.dumps(incoming).encode()
    history = incoming.get('input')
    triggers = [index for index,item in enumerate(history) if isinstance(item,dict) and item.get('type') == 'compaction_trigger'] if isinstance(history,list) else []
    if triggers:
        if triggers != [len(history)-1] or set(history[-1]) - {'type','id'}:
            raise GatewayError('Invalid native compaction trigger',422)
        requested_model = incoming['model']
        if requested_model in external:
            if COMPACTION_MODEL not in core.native_models:
                raise GatewayError('Portable compaction requires the signed-in ChatGPT compaction model',422)
            # This is a checkpoint operation only. The desktop's selected model
            # and native per-thread settings remain untouched.
            reasoning = incoming.get('reasoning')
            if reasoning is not None and not isinstance(reasoning,dict): raise GatewayError('Invalid compaction reasoning',422)
            # Provider-default effort can be none; the native checkpoint needs low or above.
            incoming = {**incoming,'model':COMPACTION_MODEL,'reasoning':{**(reasoning or {}),'effort':'low'}}
    if incoming['model'] in external or incoming['model'] in core.native_models:
        if incoming['model'] in external and isinstance(history, list):
            # A resumed child retains its original task as well as the new follow-up.
            # Recover observed plaintext from the parent's saved tool calls first.
            remember_external_handoffs({'type': 'response.completed', 'response': {'output': history}})
        if isinstance(incoming.get('input'), list):
            incoming = {**incoming, 'input': normalize_agent_handoffs(incoming['input'])}
        incoming = apply_profile(incoming, profile_settings, profiles)
        headers = [(name,value) for name,value in headers if name.lower() not in {'content-encoding','content-length'}]
        body = json.dumps(incoming).encode()
    removed = 0
    if incoming['model'] in external:
        tools = incoming.get('tools',[])
        if not isinstance(tools,list) or any(not isinstance(tool,dict) for tool in tools): raise GatewayError('Invalid tool declarations')
        hosted_search = {'web_search','web_search_preview'}
        choice = incoming.get('tool_choice')
        if isinstance(choice,dict) and choice.get('type') in hosted_search:
            raise GatewayError('This gateway does not provide OpenAI-hosted web search on external routes',422)
        retained = [tool for tool in tools if tool.get('type') not in hosted_search]
        removed = len(tools) - len(retained)
        if removed:
            instructions = incoming.get('instructions') or ''
            if not isinstance(instructions,str): raise GatewayError('Invalid instructions')
            incoming = {**incoming,'tools':retained,'instructions':instructions + '\nThis gateway does not provide OpenAI-hosted web search on external routes. Use the advertised function tools through Codex and preserve its normal permissions and approvals.\n'}
        headers = [(name,value) for name,value in headers if name.lower() not in {'content-encoding','content-length'}]
        body = json.dumps(incoming).encode()
    elif incoming['model'] in core.native_models and isinstance(incoming.get('input'),list):
        # The native server accepts no plaintext reasoning content. External
        # reasoning is not portable opaque state; retain messages/tool results.
        retained = [item for item in incoming['input'] if not (isinstance(item,dict) and item.get('type') == 'reasoning' and item.get('encrypted_content') is None and isinstance(item.get('content'),list) and item['content'])]
        if len(retained) != len(incoming['input']):
            incoming = {**incoming,'input':retained}
            headers = [(name,value) for name,value in headers if name.lower() not in {'content-encoding','content-length'}]
            body = json.dumps(incoming).encode()
        # All these input IDs are optional transport identifiers. Translating
        # a function to a custom/search call can leave the old type's prefix.
        # Retain call_id pairings and every opaque/encrypted native item.
        optional_id_types = {'message','function_call','function_call_output','custom_tool_call',
            'custom_tool_call_output','tool_search_call','tool_search_output','additional_tools','compaction_trigger'}
        normalized = [({key:value for key,value in item.items() if key != 'id'} if isinstance(item,dict) and item.get('type') in optional_id_types and item.get('encrypted_content') is None and item.get('encrypted_function_args') is None else item) for item in incoming['input']]
        if normalized != incoming['input']:
            incoming = {**incoming,'input':normalized}
            headers = [(name,value) for name,value in headers if name.lower() not in {'content-encoding','content-length'}]
            body = json.dumps(incoming).encode()
    prepared = core.prepare('POST',target,headers,body)
    if triggers and requested_model in external:
        headers_identity = [(k,v) for k,v in prepared.headers if k.lower() != 'accept-encoding']+[('Accept-Encoding','identity')]
        from dataclasses import replace
        prepared = replace(prepared,kind='compaction',headers=tuple(headers_identity))
        incoming = {**incoming,'model':requested_model}
    return prepared, incoming, removed


class MixedGateway(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args): pass

    def fail(self, status, message, code='replica_gateway_error'):
        payload = json.dumps({'error': {'code': code, 'message': message}}).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def core(self):
        settings=getattr(self,'runtime_settings',None)
        return GatewayCore(self.server.capability, self.server.server_port, self.server.native_models,
                           lambda _provider: 'synthetic-key-for-local-validation-only',registry=settings.registry if settings else None)

    def request_failure(self, status, message, streaming, event, code='replica_gateway_error'):
        external = event is not None and event.get('provider') != 'openai'
        if not streaming:
            # The desktop retries 429 and 5xx responses, repeating provider requests.
            self.fail(400 if external and status in {408, 429, 502, 504} else status, message, code=code)
        elif external:
            digest = getattr(self, 'external_request_digest', None)
            if digest is not None:
                # Codex retries stream errors even after a terminal failure event.
                with FAILURE_LOCK:
                    FAILED_EXTERNAL_STREAMS[digest] = (time.monotonic(), code, message)
                    FAILED_EXTERNAL_STREAMS.move_to_end(digest)
                    if len(FAILED_EXTERNAL_STREAMS) > 128:
                        FAILED_EXTERNAL_STREAMS.popitem(last=False)
            payload = {'type': 'error', 'code': code, 'message': message}
            try:
                self.wfile.write(('data: ' + json.dumps(payload) + '\n\n').encode())
                self.wfile.flush()
            except OSError:
                pass

    def catalog_header(self):
        publisher=getattr(self.server,'catalog_cache',None)
        if publisher:self.send_header('x-models-etag',publisher.tag(self.server.model_catalog)[1])

    def relay(self, upstream, event=None):
        self.send_response(upstream.status)
        for name, value in upstream.headers.items():
            if name.lower() not in HOP_HEADERS | {'content-length'} and not (getattr(self.server,'catalog_cache',None) and name.lower()=='x-models-etag'): self.send_header(name, value)
        MixedGateway.catalog_header(self)
        self.send_header('Connection', 'close')
        self.end_headers()
        if event is not None:
            event['upstream_http_status'] = upstream.status
            record(event)
        while data := upstream.read1(65536):
            self.wfile.write(data)
            self.wfile.flush()
        self.close_connection = True
        if event is not None:
            event['upstream_eof'] = True
            record(event)

    def do_GET(self):
        generations=getattr(self.server,'settings_generations',None)
        if generations:
            with generations.request() as (self.generation_token,self.runtime_settings):MixedGateway._get(self)
            return
        gate=getattr(self.server,'reload_gate',None)
        with gate.request() if gate else nullcontext():MixedGateway._get(self)

    def _get(self):
        try:
            prepared = self.core().prepare('GET', self.path, list(self.headers.items()))
            if prepared.kind != 'models': raise GatewayError('Unsupported replica gateway endpoint', 404)
            publisher=getattr(self.server,'catalog_cache',None)
            if publisher:
                catalog=self.runtime_settings.catalog if hasattr(self,'runtime_settings') else self.server.model_catalog
                version=parse_qs(urlsplit(self.path).query).get('client_version',[''])[0]
                if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?',version):raise GatewayError('Invalid model catalog client version',400)
                payload,etag=publisher.describe(catalog,version)
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('ETag',etag);self.send_header('Content-Length',str(len(payload)));self.send_header('Connection','close');self.end_headers()
                self.wfile.write(payload);self.close_connection=True
                record({'kind':'models','dynamic_catalog':True,'model_count':len(catalog['models'])})
                return
            with open_upstream(prepared.url, prepared.headers) as upstream:
                if upstream.headers.get('Content-Encoding') not in (None, 'identity'):
                    raw = decode_body(upstream.read(MAX_BODY + 1), upstream.headers.get('Content-Encoding'))
                else: raw = upstream.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY: raise GatewayError('Model metadata exceeded limit', 502)
                value = json.loads(raw)
            native = value.get('models')
            if not isinstance(native, list): raise GatewayError('Native metadata shape was unexpected', 502)
            native_ids = {model['slug'] for model in native}
            self.server.native_models = native_ids
            value['models'] = native + [model for model in self.server.external_models if model['slug'] not in native_ids]
            payload = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(payload)
            self.close_connection = True
            record({'kind': 'models', 'native_models_received': len(native), 'external_models_added': len(value['models']) - len(native)})
        except urllib.error.HTTPError as error:
            self.fail(error.code if error.code in {400,401,403,429} else 502, 'Native model metadata request failed')
        except GatewayError as error: self.fail(error.status, str(error))
        except (OSError, ValueError, KeyError): self.fail(502, 'Model metadata could not be loaded')

    def do_POST(self):
        generations=getattr(self.server,'settings_generations',None)
        if generations:
            with generations.request() as (self.generation_token,self.runtime_settings):MixedGateway._post(self)
            return
        gate=getattr(self.server,'reload_gate',None)
        with gate.request() if gate else nullcontext():MixedGateway._post(self)

    def _post(self):
        streaming = False
        event = None
        started = time.monotonic()
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY: raise GatewayError('Invalid request size', 413)
            body = self.rfile.read(length)
            if len(body) != length: raise GatewayError('Incomplete request body')
            settings=getattr(self,'runtime_settings',None)
            profile_settings,profiles=(settings.profile_settings,settings.profiles) if settings else (PROFILE_SETTINGS,PROFILES)
            catalog = settings.catalog if settings else getattr(self.server, 'model_catalog', None)
            prepared, incoming, removed = prepare_routed_request(self.core(),self.path,list(self.headers.items()),body,profile_settings,profiles,catalog)
            model = incoming.get('model')
            event = {'kind': 'responses', 'model': model, 'provider': prepared.provider, 'upstream_eof': False}
            event.update(profile_diagnostics(model, profile_settings, profiles))
            if removed: event['openai_hosted_search_declarations_removed'] = removed
            record(event)
            if prepared.provider != 'openai':
                identity = json.dumps([self.headers.get('thread-id'), self.headers.get('x-client-request-id')]).encode()
                self.external_request_digest = hashlib.sha256(identity + prepared.body).digest()
                with FAILURE_LOCK:
                    failed = FAILED_EXTERNAL_STREAMS.pop(self.external_request_digest, None)
                if failed is not None and time.monotonic() - failed[0] < 30:
                    # Stop one immediate replay locally; deliberate later retries work.
                    event['failed_stream_retry_blocked'] = True
                    record(event)
                    self.fail(400, failed[2], code=failed[1])
                    return
                # The existing real service receives only its dummy local bearer.
                # It holds the DPAPI provider keys and strips native private fields.
                # Let the inner relay return its provider timeout before this hop expires.
                upstream = open_upstream(self.server.external_url, external_headers(getattr(self,'generation_token',None)), prepared.body, timeout=external_adapter.PROVIDER_TIMEOUT + 30)
            else:
                if prepared.provider != 'openai': raise GatewayError('Model is not allowed in this replica', 422)
                upstream = open_upstream(prepared.url, prepared.headers, prepared.body)
            with upstream:
                if prepared.kind == 'compaction':
                    if upstream.headers.get_content_type() not in {'text/event-stream','text/plain'}: raise GatewayError('Native checkpoint did not return an event stream',502)
                    self.send_response(upstream.status)
                    self.send_header('Content-Type','text/event-stream')
                    MixedGateway.catalog_header(self)
                    self.send_header('Connection','close')
                    self.end_headers()
                    streaming = True
                    event['kind'] = 'compaction'
                    event['compaction_model'] = json.loads(prepared.body)['model']
                    try:
                        for frame,decoded in checkpoint_events(upstream,prepared,open_upstream):
                            self.wfile.write(frame); self.wfile.flush()
                            if decoded and decoded.get('type') == 'response.completed':
                                event['response_completed'] = True
                                event['portable_summary_saved'] = True
                    except (ValueError,OSError,TypeError,KeyError,AttributeError) as error:
                        failure={'type':'error','code':'portable_compaction_failed','message':'Compaction could not create a verified portable checkpoint. The previous working history was retained.'}
                        self.wfile.write(('data: '+json.dumps(failure)+'\n\n').encode());self.wfile.flush()
                        event['portable_summary_saved'] = False
                        event['compaction_failure_type'] = type(error).__name__
                        if isinstance(error,urllib.error.HTTPError):
                            event['native_summary_http_status'] = error.code
                            event['native_summary_error'] = external_adapter.provider_error_diagnostic(error.read(65537))
                    record(event)
                elif prepared.provider != 'openai':
                    if upstream.headers.get_content_type() != 'text/event-stream': raise GatewayError('External service did not return an event stream', 502)
                    self.send_response(upstream.status)
                    self.send_header('Content-Type', 'text/event-stream')
                    MixedGateway.catalog_header(self)
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    streaming = True
                    event['upstream_http_status'] = upstream.status
                    completed = False
                    for frame, decoded in external_adapter.translated_events(upstream, prepared.tools):
                        if decoded:
                            decoded = desktop_external_event(decoded)
                            if decoded is None: continue
                            frame = ('data: ' + json.dumps(decoded) + '\n\n').encode()
                            remember_external_handoffs(decoded)
                        self.wfile.write(frame)
                        self.wfile.flush()
                        if decoded and decoded.get('type') == 'response.completed':
                            event['response_completed'] = completed = True
                    if not completed:
                        raise GatewayError('Provider stream ended without completing', 502)
                    event['upstream_eof'] = True
                    record(event)
                else:
                    streaming = True
                    self.relay(upstream, event)
        except urllib.error.HTTPError as error:
            safe_message = 'Selected provider rejected this request'
            safe_code = 'replica_gateway_error'
            if event is not None and event.get('provider') != 'openai':
                detail = external_adapter.public_relay_detail(error.read(65537))
                if detail:
                    safe_code, safe_message = detail
            if event is not None:
                event['upstream_http_status'] = error.code
                if event.get('provider') == 'openai' and error.code == 400:
                    try:
                        detail = json.loads(error.read(65536)).get('error',{})
                        message = detail.get('message','') if isinstance(detail,dict) else ''
                        # Only fixed diagnostic vocabulary; no IDs, prompts or auth.
                        vocabulary = set('invalid value for id expected an that begins with item input content type unknown unsupported function function_call function_call_output custom_tool_call reasoning summary encrypted_content missing required must be not found corresponding output argument name namespace tool call previous response does exist field parameter allowed was provided to this caller array object string text block blocks element elements input_text output_text reasoning_text summary_text list of a is one either empty nonempty'.split())
                        vocabulary.update('minimum maximum length size least most short long too more than exactly got but received it zero one two instead above below'.split())
                        event['native_validation_words'] = [word for word in re.findall(r'[a-z_]+',message.lower()) if word in vocabulary]
                        event['native_validation_small_counts'] = [int(number) for number in re.findall(r'\b\d{1,2}\b',message)]
                        param = detail.get('param') if isinstance(detail,dict) else None
                        match = re.fullmatch(r'input\[(\d{1,6})\]\.id',param) if isinstance(param,str) else None
                        if match:
                            index = int(match[1])
                            event['native_invalid_id_index'] = index
                            items = incoming.get('input',[])
                            kind = items[index].get('type') if isinstance(items,list) and index < len(items) and isinstance(items[index],dict) else None
                            if kind in {'message','reasoning','compaction','compaction_trigger','function_call','function_call_output','custom_tool_call','custom_tool_call_output','tool_search_call','tool_search_output','additional_tools'}:
                                event['native_invalid_id_item_type'] = kind
                    except (ValueError,TypeError,AttributeError): pass
                record(event)
            MixedGateway.request_failure(self, error.code if error.code in {400,401,402,403,404,408,422,429,504} else 502, safe_message, streaming, event, code=safe_code)
        except GatewayError as error:
            if event is None and error.status == 422:
                try:
                    incoming = json.loads(decode_body(body, self.headers.get('Content-Encoding')))
                    known_types = {'function','namespace','web_search','web_search_preview','tool_search','mcp','computer','computer_use_preview','code_interpreter','image_generation'}
                    types = sorted({tool.get('type') if tool.get('type') in known_types else 'other' for tool in incoming.get('tools',[])})
                    selected = incoming.get('model')
                    event = {'kind':'request_rejected','model': selected if selected in set(self.core().external) | self.server.native_models else 'other','declared_tool_types':types}
                except (ValueError,TypeError,KeyError): pass
            if event is not None: event['gateway_error'] = str(error); record(event)
            MixedGateway.request_failure(self, error.status, str(error), streaming, event)
        except (OSError, ValueError, KeyError, http.client.HTTPException) as error:
            if event is not None:
                event['connection_failure'] = 'timeout' if isinstance(error, TimeoutError) or isinstance(getattr(error, 'reason', None), TimeoutError) else 'transport' if isinstance(error, OSError) else 'invalid_response'
                event['failure_type'] = type(getattr(error, 'reason', error)).__name__
                event['elapsed_seconds'] = round(time.monotonic() - started, 2)
                record(event)
            external = event is not None and event.get('provider') != 'openai'
            timed_out = external and (isinstance(error, TimeoutError) or isinstance(getattr(error, 'reason', None), TimeoutError))
            message = 'Provider response timed out; no automatic retry was made' if timed_out else 'Replica provider connection failed'
            MixedGateway.request_failure(self, 504 if timed_out else 502, message, streaming, event)
        finally: self.close_connection = True
