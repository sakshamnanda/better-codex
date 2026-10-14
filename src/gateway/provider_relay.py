"""Opt-in real-provider test in the verified copy; never configures the install."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
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


def public_relay_error(body):
    """Only our fixed diagnostic strings may cross the inner relay boundary."""
    if len(body) > 65536: return None
    try:
        value = json.loads(body).get('error', {})
        message = value.get('message')
        if value.get('code') == 'provider_test_error' and isinstance(message, str) and message in PUBLIC_RELAY_ERRORS:
            return message
    except (ValueError, AttributeError, TypeError): pass
    return None


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
    def error_response(self, status, message, streaming=False):
        # Controlled error text only: never relay provider error bodies or headers.
        error = {"code": "provider_test_error", "message": message}
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
            # ponytail: 4096 output tokens per test request; raise after compatibility is proven.
            limit = MODELS[outgoing["model"]]["output_limit"]
            outgoing["max_output_tokens"] = min(outgoing.get("max_output_tokens") or limit, limit)
            adapter = PROVIDERS[prepared.provider]["adapter"]
            chat = adapter == "chat_completions"
            body = json.dumps(prepare_chat(outgoing) if chat else outgoing).encode()
            from dataclasses import replace
            prepared = replace(prepared, body=body)
            event = {"model": outgoing["model"], "provider": prepared.provider,
                     "reasoning_effort": outgoing.get("reasoning", {}).get("effort"),
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
            if event is not None:
                event["http_status"] = error.code
            status = error.code if error.code in {400, 401, 402, 403, 404, 408, 422, 429} else 502
            message = {400: 'Provider rejected the request format', 401: "Provider API key was rejected", 402: "Provider credits are required",
                       403: "Provider denied access to this model", 404: "Provider model or endpoint was unavailable",
                       429: "Provider rate limit reached"}.get(status, "Provider rejected the test request")
            self.error_response(status, message, streaming)
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
