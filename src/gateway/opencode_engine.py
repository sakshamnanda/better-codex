"""Official OpenCode server as an isolated, tool-disabled inference backend."""
import base64
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from core import GatewayError, MAX_BODY
from provider_registry import PROVIDERS, MODELS

ROOT = Path(__file__).resolve().parent.parent


class OpenCodeEngine:
    def __init__(self, key_supplier, root=None, registry=None, executable_root=None):
        self.key_supplier = key_supplier
        self.root=Path(root) if root is not None else ROOT
        self.executable_root=Path(executable_root) if executable_root is not None else self.root
        self.providers,self.models=registry if registry is not None else (PROVIDERS,MODELS)
        self.process = None
        self.directory = self.root / "support/opencode-runtime"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def start(self, mock_url=None, caller_tools=False):
        exe = self.executable_root / "opencode-engine/opencode.exe"
        manifest = json.loads((exe.parent / "Verification.json").read_text())
        assert hashlib.sha256(exe.read_bytes()).hexdigest() == manifest["executable_sha256"]
        self.directory.mkdir(exist_ok=True)
        inference = self.directory / "inference"
        inference.mkdir(exist_ok=True)
        environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "COMSPEC") if key in os.environ}
        for name in ("data", "cache", "config", "state", "temp", "home"):
            (self.directory / name).mkdir(exist_ok=True)
        for variable, name in (("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"), ("TEMP", "temp"), ("TMP", "temp"), ("OPENCODE_TEST_HOME", "home")):
            environment[variable] = str(self.directory / name)
        password = secrets.token_urlsafe(32)
        self.auth = "Basic " + base64.b64encode(("opencode:" + password).encode()).decode()
        default = self.providers["opencode"]["default_model"]
        config = {"model": "opencode/" + default, "small_model": "opencode/" + default, "enabled_providers": ["opencode"], "autoupdate": False,
                  "snapshot": False, "share": "disabled", "compaction": {"auto": False, "prune": False}, "permission": {"*": "deny"}, "mcp": {}, "plugin": [],
                  "agent": {"build": {"permission": {"*": "deny"}}, "inference": {"mode": "primary", "description": "Inference only; Codex executes tools", "permission": {"*": "deny"}, "prompt": "Follow the supplied system instructions. Native OpenCode tools are disabled. Represent requested caller tools only in the exact response format specified by the caller."}},
                  "provider": {"opencode": {"options": {"apiKey": "{env:CODEX_TEST_OPENCODE_KEY}"}, "models": {model_id: {"name": model["metadata"]["display_name"], "limit": {"context": model["metadata"]["context_window"], "output": model["output_limit"]}} for model_id, model in self.models.items() if model["provider"] == "opencode"}}}}
        if mock_url is not None:
            assert mock_url.startswith("http://127.0.0.1:")
            config["provider"]["opencode"]["options"]["baseURL"] = mock_url
        if caller_tools:
            rules = {"*": "deny", "codex_request": "allow", "bash": "allow"}
            config["permission"] = rules
            config["agent"]["build"]["permission"] = rules
            config["agent"]["inference"]["permission"] = rules
            dependencies = self.directory / "config/opencode"
            dependencies.mkdir(exist_ok=True)
            plugins = dependencies / "plugins"
            plugins.mkdir(exist_ok=True)
            plugin = plugins / "codex-relay.ts"
            plugin.write_text((self.root / "gateway/codex-relay.ts").read_text(encoding="utf-8"), encoding="utf-8")
            config["plugin"] = [plugin.as_uri()]
            (dependencies / "package.json").write_text(json.dumps({"dependencies": {"@opencode-ai/plugin": "1.18.35"}}))
            environment["BUN_INSTALL_CACHE_DIR"] = str(self.directory / "cache/bun")
            environment["NPM_CONFIG_CACHE"] = str(self.directory / "cache/npm")
        self.caller_tools = caller_tools
        environment.update(OPENCODE_SERVER_PASSWORD=password, OPENCODE_CONFIG_CONTENT=json.dumps(config),
                           CODEX_TEST_OPENCODE_KEY=self.key_supplier("opencode"), OPENCODE_PURE="0" if caller_tools else "1",
                           OPENCODE_DISABLE_PROJECT_CONFIG="1", OPENCODE_DISABLE_AUTOUPDATE="1",
                           OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER="1", OPENCODE_DISABLE_MODELS_FETCH="1")
        self.environment = environment
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        self.process = subprocess.Popen([str(exe), "serve", "--hostname", "127.0.0.1", "--port", str(port), "--log-level", "ERROR"], cwd=inference, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise GatewayError("The isolated OpenCode engine could not start", 502)
            try:
                health = self.call("GET", "/global/health", timeout=1)
                if health.get("healthy"):
                    break
            except (OSError, ValueError):
                time.sleep(0.2)
        else:
            raise GatewayError("The isolated OpenCode engine did not become ready", 502)
        paths = self.call("GET", "/path")
        for name in ("data", "config", "state"):
            if name in paths and not Path(paths[name]).resolve().is_relative_to(self.directory.resolve()):
                raise GatewayError("OpenCode data isolation did not pass", 502)
        settings = self.call("GET", "/config")
        expected = "deny"
        if settings.get("permission", {}).get("*") != expected:
            raise GatewayError("OpenCode permission policy did not pass", 502)
        agents = self.call("GET", "/agent")
        inference_agent = next(agent for agent in agents if agent.get("name") == "inference")
        self.inference_permissions = inference_agent.get("permission", [])
        self.tool_ids = self.call("GET", "/experimental/tool/ids")
        if not isinstance(self.tool_ids, list) or not all(isinstance(tool, str) for tool in self.tool_ids):
            raise GatewayError("OpenCode tool discovery was unavailable", 502)
        if caller_tools and not isinstance(self.call("GET", "/permission"), list):
            raise GatewayError("OpenCode permission monitoring was unavailable", 502)
        if caller_tools:
            schemas = self.call("GET", "/experimental/tool?provider=opencode&model=" + default)
            by_name = {tool["id"]: tool for tool in schemas}
            if not by_name.get("bash", {}).get("description", "").startswith("CODEX_DATA_ONLY_BASH_V1") or not by_name.get("codex_request", {}).get("description", "").startswith("CODEX_DATA_ONLY_RELAY_V1"):
                raise GatewayError("The data-only relay tool registration did not pass", 502)
        print("Official OpenCode engine ready: isolated data, native tools denied, data-only relays " + ("enabled" if caller_tools else "disabled") + ", loopback authentication enabled.", flush=True)

    def call(self, method, path, value=None, timeout=120):
        body = json.dumps(value).encode() if value is not None else None
        request = urllib.request.Request(self.base + path, data=body, method=method,
                                         headers={"Authorization": self.auth, "Content-Type": "application/json"})
        with self.opener.open(request, timeout=timeout) as response:
            data = response.read(MAX_BODY + 1)
        if len(data) > MAX_BODY:
            raise GatewayError("OpenCode output exceeded the test limit", 502)
        return json.loads(data)

    def complete(self, payload):
        # Only the sanitized external request reaches this backend.
        definitions = payload.get("tools", [])
        system = payload.get("instructions", "") + "\nCaller function definitions: " + json.dumps(definitions)
        system += '\nWhen a caller function is needed, call codex_request with its exact declared name and arguments_json. Command requests may use the data-only bash relay. All execution occurs later in Codex. Return one caller-tool request in this inference response, then yield control to Codex; continue the overall task on the next inference request using its actual tool result. This is not a limit on the number of tools or task steps overall. Do not use read/edit/task or other native OpenCode tools. The caller conversation JSON includes actual previous function outputs; when a command has already completed, use those outputs without repeating that command unless the task requires a new run.'
        session = self.call("POST", "/session", {"title": "Isolated Codex inference test"})
        sid = session["id"]
        body = {
            "model": {"providerID": "opencode", "modelID": payload["model"]}, "agent": "inference",
            "system": system,
            "parts": [{"type": "text", "text": "Caller conversation history (JSON):\n" + json.dumps(payload["input"])}],
        }
        models=getattr(self,'models',MODELS)
        if models[payload["model"]].get("send_variant", False):
            effort = payload.get("reasoning", {}).get("effort", "medium")
            if effort not in {level["effort"] for level in models[payload["model"]]["metadata"]["supported_reasoning_levels"]}:
                raise GatewayError("Unsupported OpenCode effort variant", 422)
            body["variant"] = effort
        # Hide native tools as well as denying them. Codex owns all execution.
        body["tools"] = {tool: self.caller_tools and tool in {"codex_request", "bash"} for tool in self.tool_ids}
        # No permission-response endpoint is ever called with an approval.
        stop_monitor = threading.Event()
        native_approval_requested = threading.Event()
        def monitor():
            while not stop_monitor.wait(0.25):
                try:
                    pending = self.call("GET", "/permission", timeout=2)
                    if isinstance(pending, list) and any(item.get("sessionID") == sid for item in pending):
                        native_approval_requested.set()
                        self.call("POST", "/session/" + sid + "/abort", timeout=2)
                        return
                    history = self.call("GET", "/session/" + sid + "/message", timeout=2)
                    if any(part.get("type") == "tool" and part.get("tool") in {"codex_request", "bash"} and part.get("state", {}).get("status") == "completed" for message in history for part in message.get("parts", [])):
                        self.call("POST", "/session/" + sid + "/abort", timeout=2)
                        return
                except (OSError, ValueError):
                    continue
        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        try:
            result = self.call("POST", "/session/" + sid + "/message", body)
        except (OSError, ValueError):
            try:
                self.call("POST", "/session/" + sid + "/abort", timeout=2)
            except (OSError, ValueError):
                pass
            raise
        finally:
            stop_monitor.set()
            watcher.join(timeout=3)
        if native_approval_requested.is_set():
            raise GatewayError("OpenCode requested its own native tool; the request was aborted without approval", 422)
        messages = self.call("GET", "/session/" + sid + "/message")
        parts = [part for message in messages for part in message.get("parts", []) if part.get("type") == "tool"]
        if any(part.get("tool") not in {"codex_request", "bash"} for part in parts):
            raise GatewayError("OpenCode attempted a native tool; the inference-only check failed", 422)
        known = {tool["name"] for tool in definitions}
        calls = []
        for part in parts:
            state = part.get("state", {})
            if state.get("status") != "completed":
                continue
            data = json.loads(state.get("output", "{}"))
            if data.get("codex_request") is not True:
                raise GatewayError("Unexpected relay tool output", 422)
            name = data["name"]
            if name == "exec_command" and name not in known:
                name = next((tool["name"] for tool in definitions if tool.get("description", "").split(":", 1)[0].endswith(".exec_command")), name)
            arguments = json.loads(data["arguments_json"])
            if name not in known or not isinstance(arguments, dict):
                raise GatewayError("OpenCode returned an undeclared caller tool", 422)
            calls.append({"id": "call_" + secrets.token_hex(16), "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}})
        if calls:
            return {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": calls[:1]}}]}
        if result.get("info", {}).get("error"):
            self.last_error = result["info"]["error"]
            detail = self.last_error.get('data', {}) if isinstance(self.last_error, dict) else {}
            status = detail.get('statusCode') if isinstance(detail, dict) else None
            messages = {401: 'OpenCode Zen rejected the saved API key', 402: 'OpenCode Zen requires credits', 403: 'OpenCode Zen denied access to this model or client', 404: 'OpenCode Zen model or endpoint was unavailable', 422: 'OpenCode Zen rejected the model request', 429: 'OpenCode Zen rate limit reached'}
            if type(status) is int and status in messages:
                raise GatewayError(messages[status], status)
            raise GatewayError("The official OpenCode engine could not complete this provider request", 502)
        text = "\n".join(part.get("text", "") for part in result.get("parts", []) if part.get("type") == "text")
        if not text.strip():
            # Recover only this completed response, never an older chat answer.
            message_id = result.get('info', {}).get('id')
            completed = next((message for message in messages if message_id and message.get('info', {}).get('id') == message_id and message.get('info', {}).get('role') == 'assistant' and message.get('info', {}).get('time', {}).get('completed') and not message.get('info', {}).get('error')), None)
            if completed:
                text = '\n'.join(part.get('text', '') for part in completed.get('parts', []) if part.get('type') == 'text')
        fences = re.findall(r"```codex_tool_calls\s*([\s\S]*?)```", text)
        calls = []
        known = {tool["name"] for tool in definitions}
        for fence in fences:
            try:
                value = json.loads(fence)
                items = value["tool_calls"]
            except (ValueError, KeyError, TypeError):
                raise GatewayError("OpenCode returned malformed caller-tool output", 502) from None
            if not isinstance(items, list) or len(items) > 8:
                raise GatewayError("OpenCode returned invalid caller-tool count", 502)
            for item in items:
                if not isinstance(item, dict) or item.get("name") not in known or not isinstance(item.get("arguments"), dict):
                    raise GatewayError("OpenCode returned an undeclared caller tool", 502)
                calls.append({"id": "call_" + secrets.token_hex(16), "type": "function", "function": {"name": item["name"], "arguments": json.dumps(item["arguments"])}})
        content = re.sub(r"```codex_tool_calls\s*[\s\S]*?```", "", text).strip()
        if not calls and not content:
            raise GatewayError("OpenCode returned empty output", 502)
        return {"choices": [{"finish_reason": "tool_calls" if calls else "stop", "message": {"content": content or None, "tool_calls": calls}}]}

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
