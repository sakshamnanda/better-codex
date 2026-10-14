"""Signed desktop replica: native ChatGPT routing plus the proven external service."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import hashlib
import importlib.util
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import threading
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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise GatewayError('Upstream redirects are not accepted', 502)


def open_upstream(url, headers, body=None):
    # Fresh TLS connection to a fixed origin; inherited proxies are ignored.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    return opener.open(urllib.request.Request(url, headers=dict(headers), data=body), timeout=120)


def record(event):
    with LOCK:
        if not any(item is event for item in EVENTS): EVENTS.append(event)
        temporary = SUPPORT / 'Mixed-Results.tmp'
        temporary.write_text(json.dumps({'events': EVENTS, 'real_native_authentication_required': True, 'native_auth_never_forwarded_to_external_service': True}, indent=2))
        temporary.replace(SUPPORT / 'Mixed-Results.json')


def external_headers():
    headers = {'Authorization': 'Bearer ' + DUMMY, 'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
    return headers


def prepare_routed_request(core, target, headers, body):
    # Check the actual URL, local capability, Host and bearer before parsing data.
    # GET /responses is deliberately unsupported after these shared checks.
    try: core.prepare('GET', target, headers)
    except GatewayError as error:
        if error.status != 404: raise
    encoding = next((value for name,value in headers if name.lower() == 'content-encoding'), None)
    incoming = json.loads(decode_body(body, encoding))
    if not isinstance(incoming,dict) or not isinstance(incoming.get('model'),str): raise GatewayError('Invalid Responses model')
    history = incoming.get('input')
    triggers = [index for index,item in enumerate(history) if isinstance(item,dict) and item.get('type') == 'compaction_trigger'] if isinstance(history,list) else []
    if triggers:
        if triggers != [len(history)-1] or set(history[-1]) - {'type','id'}:
            raise GatewayError('Invalid native compaction trigger',422)
        requested_model = incoming['model']
        if requested_model in EXTERNAL:
            if COMPACTION_MODEL not in core.native_models:
                raise GatewayError('Portable compaction requires the signed-in ChatGPT compaction model',422)
            # This is a checkpoint operation only. The desktop's selected model
            # and native per-thread settings remain untouched.
            incoming = {**incoming,'model':COMPACTION_MODEL}
    if incoming['model'] in EXTERNAL or incoming['model'] in core.native_models:
        incoming = apply_profile(incoming, PROFILE_SETTINGS, PROFILES)
        headers = [(name,value) for name,value in headers if name.lower() not in {'content-encoding','content-length'}]
        body = json.dumps(incoming).encode()
    removed = 0
    if incoming['model'] in EXTERNAL:
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
    if triggers and requested_model in EXTERNAL:
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
        return GatewayCore(self.server.capability, self.server.server_port, self.server.native_models,
                           lambda _provider: 'synthetic-key-for-local-validation-only')

    def relay(self, upstream, event=None):
        self.send_response(upstream.status)
        for name, value in upstream.headers.items():
            if name.lower() not in HOP_HEADERS | {'content-length'}: self.send_header(name, value)
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
        try:
            prepared = self.core().prepare('GET', self.path, list(self.headers.items()))
            if prepared.kind != 'models': raise GatewayError('Unsupported replica gateway endpoint', 404)
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
        streaming = False
        event = None
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY: raise GatewayError('Invalid request size', 413)
            body = self.rfile.read(length)
            if len(body) != length: raise GatewayError('Incomplete request body')
            prepared, incoming, removed = prepare_routed_request(self.core(),self.path,list(self.headers.items()),body)
            model = incoming.get('model')
            event = {'kind': 'responses', 'model': model, 'provider': prepared.provider, 'upstream_eof': False}
            event.update(profile_diagnostics(model, PROFILE_SETTINGS, PROFILES))
            if removed: event['openai_hosted_search_declarations_removed'] = removed
            record(event)
            if prepared.provider != 'openai':
                # The existing real service receives only its dummy local bearer.
                # It holds the DPAPI provider keys and strips native private fields.
                upstream = open_upstream(self.server.external_url, external_headers(), prepared.body)
            else:
                if prepared.provider != 'openai': raise GatewayError('Model is not allowed in this replica', 422)
                upstream = open_upstream(prepared.url, prepared.headers, prepared.body)
            with upstream:
                streaming = True
                if prepared.kind == 'compaction':
                    if upstream.headers.get_content_type() not in {'text/event-stream','text/plain'}: raise GatewayError('Native checkpoint did not return an event stream',502)
                    self.send_response(upstream.status)
                    self.send_header('Content-Type','text/event-stream')
                    self.send_header('Connection','close')
                    self.end_headers()
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
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    event['upstream_http_status'] = upstream.status
                    for frame, decoded in external_adapter.translated_events(upstream, prepared.tools):
                        # Keep provider-specific internal reasoning out of
                        # desktop history so ordinary native rollback works.
                        if decoded:
                            if decoded.get('type','').startswith('response.reasoning') or decoded.get('item',{}).get('type') == 'reasoning': continue
                            if isinstance(decoded.get('response'),dict) and isinstance(decoded['response'].get('output'),list):
                                decoded['response']['output'] = [item for item in decoded['response']['output'] if item.get('type') != 'reasoning']
                                frame = ('data: ' + json.dumps(decoded) + '\n\n').encode()
                        self.wfile.write(frame)
                        self.wfile.flush()
                        if decoded and decoded.get('type') == 'response.completed': event['response_completed'] = True
                    event['upstream_eof'] = True
                    record(event)
                else:
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
            if not streaming: self.fail(error.code if error.code in {400,401,402,403,404,422,429} else 502, safe_message, code=safe_code)
        except GatewayError as error:
            if event is None and error.status == 422:
                try:
                    incoming = json.loads(decode_body(body, self.headers.get('Content-Encoding')))
                    known_types = {'function','namespace','web_search','web_search_preview','tool_search','mcp','computer','computer_use_preview','code_interpreter','image_generation'}
                    types = sorted({tool.get('type') if tool.get('type') in known_types else 'other' for tool in incoming.get('tools',[])})
                    selected = incoming.get('model')
                    event = {'kind':'request_rejected','model': selected if selected in EXTERNAL | self.server.native_models else 'other','declared_tool_types':types}
                except (ValueError,TypeError,KeyError): pass
            if event is not None: event['gateway_error'] = str(error); record(event)
            if not streaming: self.fail(error.status, str(error))
        except (OSError, ValueError, KeyError):
            if not streaming: self.fail(502, 'Replica provider connection failed')
        finally: self.close_connection = True
