"""Opt-in real-provider test in the verified copy; never configures the install."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import tomllib
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from core import GatewayCore, GatewayError, MAX_BODY
from chat_bridge import prepare_chat, response_events
from opencode_engine import OpenCodeEngine
from provider_registry import PROVIDERS, MODELS

HERE = Path(__file__).resolve().parent
SUPPORT = HERE.parent / "support"
LOCK = threading.Lock()
EVENTS = []
REPORT_LOCK = threading.Lock()
AGENTS_MARKER = "CODEX_REAL_PROVIDER_TEST_AGENTS_OK"
BLOCKED_MODELS = {}
PUBLIC_RELAY_ERRORS = frozenset({
    'Provider rejected the request format',
    'Provider rejected this request (HTTP 400); sanitized details were recorded',
    'This chat exceeds the selected provider context window. Compact it with a model that can read the current history, then switch back.',
    'OpenCode Zen rejected the saved API key',
    'OpenCode Zen requires credits',
    'OpenCode Zen denied access to this model or client',
    'OpenCode Zen model or endpoint was unavailable',
    'OpenCode Zen rejected the model request',
    'OpenCode Zen rate limit reached',
    'OpenCode requested its own native tool; the request was aborted without approval',
    'OpenCode attempted a native tool; the inference-only check failed',
    'OpenCode returned an undeclared caller tool',
    'OpenCode returned malformed caller-tool output',
    'OpenCode returned invalid caller-tool count',
    'OpenCode returned empty output',
    'The official OpenCode engine could not complete this provider request',
    'Unexpected relay tool output',
})

def limit_output(payload,model):
    # A published ceiling is not a default output reservation. Let the
    # provider choose its default unless the caller supplies a cap.
    limit=model['output_limit']
    if model.get('metadata_mode')!='provider' or payload.get('max_output_tokens') is not None:
        payload['max_output_tokens']=min(payload.get('max_output_tokens') or limit,limit)


def provider_error_diagnostic(body):
    """Retain fixed error vocabulary only; never persist an upstream body."""
    result = {'body_truncated': len(body) > 65536}
    if result['body_truncated']:
        return result
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        return result
    codes = set('invalid_api_key authentication_error invalid_request_error validation_error bad_request context_length_exceeded context_window_exceeded max_tokens_exceeded prompt_too_long input_too_long string_above_max_length too_many_messages too_many_tools tool_call_limit_exceeded max_tool_calls_exceeded unsupported_parameter unsupported_params invalid_parameter vendor_restrictions_unavailable vendor_unavailable zdr_vendor_unavailable vendor_access_required model_not_allowed model_not_found model_required insufficient_credits insufficient_balance budget_exceeded rate_limit_exceeded output_budget_exhausted blocked_by_policy'.split())
    params = set('model input messages tools tool_choice parallel_tool_calls reasoning reasoning.effort max_output_tokens max_tokens stream store instructions temperature top_p text text.format response_format service_tier'.split())
    words = set('invalid unknown unsupported missing required unavailable rejected exceeded exceeds maximum minimum limit length size context window input output token tokens prompt messages message tools tool tool_choice call calls function schema parameters parameter arguments reasoning effort budget exhausted insufficient credits credit balance vendor vendors restrictions restriction region regions eligible eligible_vendor model models access policy policies blocked authentication key api format text json string array object content must should supported supports support found corresponding empty many too long short large character characters count request requests all failed failure unable'.split())
    found_codes, found_params, found_words, counts = set(), set(), set(), set()
    stack, visited = [value], 0
    while stack and visited < 64:
        entry = stack.pop(); visited += 1
        if isinstance(entry, list):
            stack.extend(entry[:16])
        elif isinstance(entry, dict):
            for field in ('code', 'type'):
                code = entry.get(field)
                if isinstance(code, str) and code in codes: found_codes.add(code)
            param = entry.get('param')
            if isinstance(param, str) and param in params: found_params.add(param)
            message = entry.get('message')
            if isinstance(message, str):
                message = message[:8192].lower()
                found_words.update(word for word in re.findall(r'[a-z_]+', message) if word in words)
                counts.update(int(number) for number in re.findall(r'\b(\d{1,7})\s+(?:tokens|messages|tools|items|characters)\b', message))
            # Do not walk arbitrary data, request echoes or account metadata.
            stack.extend(entry[k] for k in ('error', 'errors', 'detail', 'details') if isinstance(entry.get(k), (dict, list)))
    result.update(codes=sorted(found_codes), parameters=sorted(found_params),
                  validation_words=sorted(found_words), size_counts=sorted(counts)[:16])
    return result


def public_relay_detail(body):
    """Only our fixed diagnostic strings may cross the inner relay boundary."""
    if len(body) > 65536: return None
    try:
        value = json.loads(body).get('error', {})
        message = value.get('message')
        code = value.get('code')
        if code in {'provider_test_error', 'context_length_exceeded'} and isinstance(message, str) and message in PUBLIC_RELAY_ERRORS:
            return code, message
    except (ValueError, AttributeError, TypeError): pass
    return None


def public_relay_error(body):
    detail = public_relay_detail(body)
    return detail[1] if detail else None


def key_supplier(provider):
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(HERE / "Provider-Credentials.ps1"), "-Mode", "Token", "-Provider", provider],
        capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise GatewayError("Save this provider's API key using scripts/Setup-Keys.cmd", 401)
    return result.stdout


def save_diagnostics():
    SUPPORT.mkdir(exist_ok=True)
    with REPORT_LOCK, LOCK:
        report = {
            "mode": "real external providers only; native choices unavailable",
            "helper_pid": os.getpid(),
            "real_provider_requests": sum(bool(item.get("request_sent")) for item in EVENTS),
            "events": list(EVENTS),
            "native_fixture_events": [],
        }
        path = SUPPORT / "Real-Provider-Test-Result.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)


def record(event):
    with REPORT_LOCK:
        EVENTS.append(event)
    save_diagnostics()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise GatewayError("Provider redirects are not accepted", 502)


def open_provider(prepared):
    # Ignore inherited proxies; TLS certificate verification stays enabled.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(prepared.url, data=prepared.body,
                                     headers=dict(prepared.headers), method="POST")
    request.add_header("User-Agent", "Codex-Desktop-Provider-Gateway/0.1 (local compatibility test)")
    if prepared.url.endswith("/chat/completions"):
        request.add_header("Accept", "application/json")
    return opener.open(request, timeout=120)


def translated_events(stream, names):
    """Bounded SSE frames. Preserve comments and rewrite function namespaces."""
    total = 0
    frame = []
    frame_size = 0
    while True:
        line = stream.readline(2 * 1024 * 1024 + 1)
        if not line:
            if frame:
                raise GatewayError("Provider stream ended inside an event", 502)
            return
        total += len(line)
        frame_size += len(line)
        if len(line) > 2 * 1024 * 1024 or frame_size > 2 * 1024 * 1024 or total > 64 * 1024 * 1024:
            raise GatewayError("Provider stream exceeded the test limit", 502)
        if line.strip():
            frame.append(line.rstrip(b"\r\n"))
            continue
        data = b"\n".join(line[5:].lstrip(b" ") for line in frame if line.startswith(b"data:"))
        if data and data != b"[DONE]":
            try:
                event = json.loads(data)
            except (ValueError, UnicodeError):
                raise GatewayError("Provider returned invalid streaming data", 502) from None
            if not isinstance(event, dict):
                raise GatewayError("Provider returned invalid streaming data", 502)
            if event.get("type") in {"error", "response.failed", "response.incomplete"}:
                raise GatewayError("Provider could not complete the response", 502)
            for translated in names.response_events(event):
                yield ("data: " + json.dumps(translated) + "\n\n").encode(), translated
        else:
            yield b"\n".join(frame) + b"\n\n", None
        frame = []
        frame_size = 0


from http.server import BaseHTTPRequestHandler

class RelayBase(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self,*_args): pass
    def allowed(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}" and self.headers.get("Origin") is None and self.path.startswith(self.server.prefix + "/") and self.headers.get("Authorization") == "Bearer " + self.server.token
    def fail(self,status):
        self.send_response(status)
        self.send_header("Content-Length","0")
        self.send_header("Connection","close")
        self.end_headers()
        self.close_connection = True

class RealGateway(RelayBase):
    def error_response(self, status, message, streaming=False, code='provider_test_error'):
        # Controlled error text only: never relay provider error bodies or headers.
        error = {"code": code, "message": message}
        body = (("data: " + json.dumps({"type": "error", **error}) + "\n\n").encode()
                if streaming else json.dumps({"error": error}).encode())
        if not streaming:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True

    def do_POST(self):
        if not self.allowed() or self.path != self.server.prefix + "/backend-api/codex/responses":
            self.fail(403)
            return
        streaming = False
        event = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise GatewayError("Invalid request size", 413)
            body = self.rfile.read(length)
            if len(body) != length:
                raise GatewayError("Incomplete request body")
            from core import decode_body
            incoming = json.loads(decode_body(body, self.headers.get("Content-Encoding")))
            if incoming.get("model") in BLOCKED_MODELS:
                raise GatewayError(BLOCKED_MODELS[incoming["model"]], 403)
            capability = "provider_test_capability_12345678901234567890"
            core = GatewayCore(capability, self.server.server_port, set(), key_supplier)
            prepared = core.prepare("POST", core.prefix + "/backend-api/codex/responses",
                                    list(self.headers.items()), body)
            outgoing = json.loads(prepared.body)
            if outgoing["model"] not in {entry["slug"] for entry in self.server.catalog["models"]}:
                raise GatewayError("Model is outside this test's selected catalog", 422)
            limit_output(outgoing,MODELS[outgoing['model']])
            adapter = PROVIDERS[prepared.provider]["adapter"]
            chat = adapter == "chat_completions"
            body = json.dumps(prepare_chat(outgoing) if chat else outgoing).encode()
            from dataclasses import replace
            prepared = replace(prepared, body=body)
            event = {"model": outgoing["model"], "provider": prepared.provider,
                     "reasoning_effort": outgoing.get("reasoning", {}).get("effort"),
                     "request_bytes": len(prepared.body),
                     "input_items": len(outgoing['input']), "tools_declared": len(outgoing['tools']),
                     "request_sent": True, "response_completed": False,
                     "agents_marker_received": AGENTS_MARKER in json.dumps(outgoing),
                     "tool_output_received": any(item.get("type") == "function_call_output" for item in outgoing["input"]),
                     "function_calls_returned": 0}
            record(event)
            from contextlib import nullcontext
            engine = getattr(self.server, "opencode_engine", None)
            if adapter == "opencode":
                if engine is None:
                    raise GatewayError("The genuine OpenCode inference helper is not running", 502)
                response_context = nullcontext(None)
                stream_events = response_events(engine.complete(outgoing), prepared.tools)
            else:
                response_context = open_provider(prepared)
            with response_context as upstream:
                if upstream is None:
                    pass
                elif chat:
                    value = upstream.read(MAX_BODY + 1)
                    if len(value) > MAX_BODY:
                        raise GatewayError("Provider output exceeded the test limit", 502)
                    stream_events = response_events(json.loads(value), prepared.tools)
                elif upstream.headers.get_content_type() != "text/event-stream":
                    raise GatewayError("Provider did not return a Responses event stream", 502)
                else:
                    stream_events = translated_events(upstream, prepared.tools)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                streaming = True
                completed = False
                for frame, decoded in stream_events:
                    self.wfile.write(frame)
                    self.wfile.flush()
                    if decoded:
                        if decoded.get("type") == "response.output_item.done" and decoded.get("item", {}).get("type") == "function_call":
                            with REPORT_LOCK:
                                event["function_calls_returned"] += 1
                        if decoded.get("type") == "response.completed":
                            completed = True
                            with REPORT_LOCK:
                                event["response_completed"] = True
                        reported = decoded.get("response", {}).get("model")
                        if isinstance(reported, str) and len(reported) <= 200:
                            with REPORT_LOCK:
                                event["provider_reported_model"] = reported
                if not completed:
                    raise GatewayError("Provider stream ended without completing", 502)
            self.close_connection = True
        except urllib.error.HTTPError as error:
            diagnostic = provider_error_diagnostic(error.read(65537))
            if event is not None:
                event["http_status"] = error.code
                event['provider_error'] = diagnostic
            status = error.code if error.code in {400, 401, 402, 403, 404, 408, 422, 429} else 502
            message = {400: 'Provider rejected this request (HTTP 400); sanitized details were recorded', 401: "Provider API key was rejected", 402: "Provider credits are required",
                       403: "Provider denied access to this model", 404: "Provider model or endpoint was unavailable",
                       429: "Provider rate limit reached"}.get(status, "Provider rejected the test request")
            code = 'provider_test_error'
            if error.code == 400 and 'context_length_exceeded' in diagnostic.get('codes', []):
                code = 'context_length_exceeded'
                message = 'This chat exceeds the selected provider context window. Compact it with a model that can read the current history, then switch back.'
            self.error_response(status, message, streaming, code=code)
        except GatewayError as error:
            if event is not None:
                event["gateway_error"] = str(error)
            self.error_response(error.status, str(error), streaming)
        except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
            try:
                self.error_response(502, "Provider test connection failed; no automatic retry was made", streaming)
            except OSError:
                pass
        finally:
            if event is not None:
                save_diagnostics()
