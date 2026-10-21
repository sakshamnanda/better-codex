# External model tool compatibility

External models select tools; the installed Codex runtime executes them. The gateway preserves native tool identities, schemas, session IDs, permissions and approvals. It never executes subagent/MCP calls itself or gives providers native account credentials.

## Prepared fixes, 2026-10-12

- Readable, bounded tool aliases replace opaque hashes; collisions are rejected and namespaces restored exactly.
- Delegation guidance uses actual advertised schemas for creating, messaging, waiting, resuming and closing agents. Messages are never silently changed into spawns or given invented target IDs.
- External catalog entries use the current V2 subagent backend, native text patch tools, asynchronous user questions and clock tools. Native Node tool approval remains required. Existing chats can retain V1; both interfaces are supported.
- Native text tools become JSON functions with one `input` string. Returned items and streams reconstruct the native text call; Codex parses and executes it.
- Client tool discovery becomes a JSON function and returns a native `tool_search_call`. Loaded schemas in discovery history remain callable. Already declared deferred schemas are supplied inline to providers; this can increase prompt size.
- OpenCode yields one tool request per inference response and continues the overall task with Codex's result on the next request. This is not a one-tool limit for the whole task.
- Known OpenCode provider errors retain their HTTP status with fixed public messages. Raw errors stay private; a known 403 is no longer shown as a generic 502.

## Evidence and limits

| Workflow | Verified | Remaining limit |
| --- | --- | --- |
| Shell/background sessions | Previous real desktop echo tests; offline session-ID and argument round trips | Background terminal interaction not retested live here |
| Native patches | Exact text/stream round trips; installed runtime reaches its native handler and enforces its sandbox policy | No live project edited by an external model here |
| MCP discovery/calls | Installed runtime discovers and executes an owned read-only MCP with local mock inference | Each connected app has its own permissions/availability |
| ChatGPT tunnels | Client function schemas/namespaces and credential boundary checked offline | Actual user tunnel not invoked; end-to-end parity unverified |
| Subagents | Real OpenRouter GLM delegated to `gpt-6.1-sol` with high reasoning; the child completed and GLM received its result on 2026-10-17 | Synthetic task in an isolated runtime; model reliability not guaranteed |
| Cross-chat messages | Real sender delivery confirmed; native received-message shape reproduced with Merge, then real GLM acknowledged translated synthetic context | Actual recipient retry after loading the fix remains unverified |
| Instructions/model switches | Original context preserved; matching profile supplied once per request | Delivery cannot force perfect obedience |
| Categories/effort | Existing picker checks pass; native callbacks retained | Effort support remains model-specific |
| Pasted images | Inline data and both relay hops verified offline for nine advertised vision routes | Live image inference remains unverified; native file IDs, remote attachment URLs and video are rejected |
| OpenAI-hosted tools and native attachments | Unsupported forms rejected | External routes do not acquire hosted search, file search, computer use, image generation or encrypted native reasoning |

External models retain `tool_mode: direct`: JSON schemas instead of ChatGPT's code-mode-only entry point, with native executors and permissions. Identical model decisions and every OpenAI-hosted feature are not promised.

Codex `wait_threads` accepts integer `timeoutMs` values from 0 to 120000 (two minutes), confirmed in the supported 26.1013.4894 desktop validator. External models receive that limit in shared guidance and the tool schema. The gateway caps oversized integer waits before returning them to Codex, keeping streamed arguments and completed calls consistent. Targets and cursors stay intact; repeated bounded waits can follow longer work. Native requests and unrelated tools are unchanged.

The installed runtime places external delegation messages in an `encrypted_content` slot even though their tool arguments are plaintext. Forwarding that slot to ChatGPT causes the child stream to close before `response.completed`. The outer gateway now recognizes exact messages returned by external delegation tools using a bounded in-memory hash record and restores their text content before routing the child. Genuine native ciphertext and unknown content remain unchanged. After a helper restart, send a new delegation rather than retrying an old handoff whose provenance is no longer in memory.

`python tests/check-delegation-runtime.py --unfixed` reproduces the failure with the installed backend and localhost mocks. The default run verifies the repair offline. `--live` explicitly uses saved credentials for a synthetic GLM-to-native delegation, verifies high reasoning on the native request, and requires both the child result and GLM's final acknowledgement. It uses an isolated scratch profile and does not read existing chats or restart the desktop.

## ChatGPT tunnels

[OpenAI's Secure MCP Tunnel documentation](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) describes an OpenAI-managed private MCP connection governed by organization/workspace permissions. When Codex exposes its connection as client tools, external models request those functions and Codex handles authentication. Provider requests contain portable schemas/context, not tunnel authentication.

Raw Responses `mcp` declarations containing `tunnel_id`, authenticated endpoints or headers are refused. A localhost MCP fixture does not establish that a particular ChatGPT tunnel works: test the supported connection in the desktop.

## Checks

The 2026-10-13 history fix separates completed past calls from currently available tools. When code-mode, subagent versions or plugin availability change, retired function calls and their actual paired results remain readable transcripts. Their old schemas are not re-created from those calls. Incomplete/ambiguous results and new requests to unavailable tools still fail validation. Current calls retain their exact mappings; native requests remain unchanged.

The cross-chat fix on the same date handles Codex's received-message envelope: a `function_call_output` named `codex_app.send_message_to_thread` without a call ID. It becomes explicitly labelled agent-supplied context, without elevating permissions or forwarding private message IDs/routing metadata. Ordinary paired send-tool results keep their call IDs. A synthetic Merge check reproduced HTTP 400 before translation and completed a real GLM acknowledgement after translation. No real chat was messaged by that check. The actual recipient still needs a retry after loading the replacement.

The shared external-model workflow now explicitly requires reading the current project's applicable `AGENTS.md` and required referenced instruction files after model preferences, then checking required project handoffs before completion. The rule is supplied once across the two gateway layers; it preserves native permissions and requires existing human/project authorization for messaging. It is a model instruction, not a gateway bypass or a guarantee that every model obeys it. Native ChatGPT routes are unchanged.

```powershell
python tests/check-delegation-tools.py
python tests/check-chat-waits.py
python tests/check-tool-compatibility.py
python tests/check-retired-tool-history.py
python tests/check-cross-chat-context.py
python tests/check-native-client-tools.py
python tests/check-opencode-relay.py
python tests/check-opencode-engine-local.py
```

The native-client test uses the installed runtime as a harness with a fresh scratch home, dummy credentials, localhost inference and an owned read-only MCP. It does not configure/restart the desktop, use actual providers/tunnels or create agents. Generated output stays in ignored `.local/test-work/`.

`python tests/check-glm-delegation-live.py --live` explicitly makes two bounded paid Merge requests with synthetic history and the actual configured GLM profile. It checks tool selection only and never executes returned agent calls. Both V1/V2 checks passed on 2026-10-12.

`python tests/check-cross-chat-context.py --live` is another explicit opt-in check: two bounded Merge requests using synthetic incoming messages. It does not send messages to existing chats or create agents.

## Activate and verify

The replacement is staged for the next custom-shortcut launch; the active deployment and rollback state remain intact. Close Codex normally and reopen **Codex (Custom Providers)** once. Later model switches need no restart.

Use a fresh external-model chat to test V2 delegation. Request one read-only operation through an already connected tunnel/app and check its actual result and native approval behavior. A real two-worker lifecycle check needs an explicit request to create those test agents. A model label alone does not prove execution.

Rollback: close Codex and run `scripts/Rollback.cmd` to restore ordinary configuration. For the preceding custom code, restore the prior ignored deployment selection while custom sessions are closed, then launch its retained folder. Never replace an active deployment in place.
