# Setup and operating notes

The live app was confirmed working on 2026-10-11 with provider categories and effort sliders. Backend checks completed real shell commands with exit code zero and retained instructions/history across ChatGPT → Nemotron → Space Bunny → ChatGPT. A subsequent native-only check read the same history without a gateway.

## Launch and rollback

`scripts/Launch.cmd` invokes Windows PowerShell's registered-package command launcher. Its helper verifies package identity, installed/helper hashes and the original UI source. It starts a loopback provider gateway, backs up the current configuration, changes only `openai_base_url` and `model_catalog_json`, then launches the unchanged signed app with private pipes.

The UI update uses the actual asset URL, tolerates query strings, and temporarily bypasses that target's resource cache/service worker. Normal handling is restored afterward. A category timeout keeps the native window/provider service open rather than forcing a quit.

`scripts/Rollback.cmd` restores settings after Codex closes, or cancels a queued activation. Exact original bytes are restored when no unrelated edits occurred. Otherwise unrelated later edits are preserved; separately edited managed keys are not overwritten. Authentication and chat databases are never restored/replaced by this script.

## Local-only assets

The project contains an ignored, verified copy of the official OpenCode engine and its pinned plugin dependency, encrypted provider key files, and private configuration backups. Fresh runtime state is created on first project-based launch. Active leases, browser/account profiles and databases were not copied from the old deployment.

Active deployments are retained while their session runs. Their settings backups and key lookups use their existing paths. The next desktop-shortcut launch uses the folder selected by `.local/deployment-path.txt`. A staged replacement contains a fresh runtime state and takes its own configuration backup after the old app closes. Do not run old and new provider launches concurrently.

## Provider details and limits

- OpenRouter: `nvidia/nemotron-3-ultra-550b-a55b:free`, Low/Medium/High.
- OpenCode Zen: `space-bunny-free`, Low/Medium/High/Extra High/Max, through the genuine OpenCode model variants.
- Merge Gateway: `zai/glm-5.3-flash`, Low/High/Max, with Low as the local default and a 16,384-token output cap. Uses `https://api-gateway.merge.dev/v1/openai/responses`, a separate encrypted Merge key, and the shared model instruction default. Context is conservatively capped at 1,000,000 tokens pending authenticated per-vendor metadata. No OpenRouter GLM route was added.
- Step 5 remains configured with a Medium placeholder and 4,096 output cap; the adapter currently sends no Step-specific reasoning effort. These local overrides are not provider limits. StepFun's official model card confirms Low/Medium/High effort and 64k maximum output. OpenCode's own provider catalog lists 1,000,000 context and 65,536 output tokens for `step-5-preview-free`. Its direct global StepFun API has a 1,024,000 input/context entry; use the OpenCode-specific value for this route. This research does not change the running configuration.
- ChatGPT retains original supported model/effort metadata and its normal authentication.
- External routes do not provide OpenAI-hosted web search. Advertised function tools run through normal Codex approvals. Unsupported nonportable items are rejected rather than forwarded blindly.

The OpenCode inference agent denies and hides native tools, exposing only the verified `codex_request` and data-only `bash` relays. Actual shell, files, browser and other operations remain Codex caller tools subject to Codex permissions. A completed assistant reply can be recovered from the same response's stored parts when the immediate message result is empty; older, pending or failed replies are never substituted. Controlled OpenCode errors are shown by the desktop gateway without forwarding arbitrary provider messages, headers or prompt contents.

On 2026-10-12, Step 5's reported 502 was traced to the isolated engine's upstream APIError with HTTP 403, zero input/output/reasoning usage and a provider message restricting free-model use to OpenCode. It is an access/client-policy rejection, not evidence of thinking-budget exhaustion. The compatibility update preserves known provider HTTP errors, including this 403, using fixed public messages. The verified installed client was separately exercised against a localhost mock: its configured key resolves correctly, and its upstream request includes a native OpenCode User-Agent, `x-opencode-client: cli` and a session header. Why the provider rejects this particular live route is not yet established. No client-identity spoofing or account changes were made.

Production OpenCode routing is Codex desktop → local gateway → genuine isolated OpenCode server → OpenCode Zen → selected model. The client uses the saved encrypted OpenCode API key. OpenRouter and Merge remain direct HTTP routes with separate saved keys. A local mock test's dummy key never replaces the production store.

On 2026-10-13, direct API-only probes used the saved OpenCode key and synthetic text requests for `space-bunny-free` and `step-5-preview-free`. Both paths documented by OpenCode were checked: the model table's `/inference/v1/chat/completions` and the inference reference's `/inference/openai/v1/chat/completions`. Both models returned HTTP 403 before producing a reply. A further check with honest `X-Opencode-Client: better-codex` and generated session headers received the same free-model/OpenCode-client restriction. No official-client identity was spoofed. The public model catalog returned 200 and listed both models; because it is public, that is not proof of credential validation or inference access. Tool request/result probes could not run after the initial rejection. No engine was used by these direct probes, and encrypted keys, provider/model configuration and deployment selection were verified unchanged. The engine remains in the working setup; the tests do not prove an engine is a universal requirement for every OpenCode model or account. Sanitized local probe results remain ignored under `.local/research/`.

Further request-format investigation on 2026-10-13–14 did not obtain an engine-free response. An isolated localhost mock with a dummy key captured the verified v1.18.35 client's actual SDK request: its User-Agent includes `ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14`, alongside the OpenCode version; it sends session/request/project metadata, streaming usage options, reasoning effort and tool definitions. The reference client was stopped before the captured synthetic request was sent directly using the saved OpenCode key. Both legacy Zen and API-family paths returned 403 with the free-model/OpenCode-client restriction in Python and Node. Standard current-release v1.19.0 header formats and the public default coding prompt also failed. A separate fresh isolated v1.18.35 official-client control with the saved key returned 403 too; this does not establish how the existing live instance or a newly installed v1.19.0 client would behave. No new client was installed.

The newer client's public source fetches authenticated provider configuration from `https://opencode.ai/console/api/config`. That endpoint returned 200 with the saved key and included both selected models. Provider-authorized endpoint/header/model-option overrides were tested in memory and still received 403. Private configuration was never printed or saved. A documented keyless free-model control was explicitly labelled diagnostic-only and also returned 403; no production routing was changed to anonymous access. The key can therefore authenticate for configuration retrieval, but accepted free inference with it remains unverified. No accepted header/body recipe or exact server-side rejection check has been established. Tool round trips remained untested because inference was rejected. Existing app processes, provider/model/instruction files, encrypted keys and deployment selection were preserved. The remaining issue requires a provider-supported access clarification or an independently verified current client baseline; do not remove the bundled engine or claim API-only support from these negative checks.

Merge registration and offline checks passed on 2026-10-12. Its key is entered with `scripts/Setup-Keys.cmd` in the local masked **Merge Gateway** field. Each saved provider shows **Saved: ******** (leave blank to keep)** beneath its empty editable field; providers without a key show **No key saved yet**. The indicator uses file presence only and never decrypts a saved key or puts masking characters into the editable field. Existing provider keys remain when their fields are blank. The unauthenticated catalog returns 401, so account-specific model/vendor availability and real replies/tool calls still require the Merge key and a live test. No charged Merge request was made during registration. Close the old app normally and reopen through the custom shortcut to load the prepared category.

## Compaction validation

On 2026-10-14, the signed desktop setup successfully compacted the existing GLM mining thread and continued real Merge requests with tool calls/results. The installed-backend offline check also verifies the same-thread model state and a native terminal echo using mock inference. Synthetic native protocol checks verified the real ChatGPT checkpoint/portable-summary flow and the correction for invalid optional custom-tool IDs. Compaction uses ChatGPT plan usage at its fixed trusted origin; external provider credentials never authenticate that checkpoint request. See `docs/PROVIDERS.md` for the encrypted local summary cache and failure behavior.

## References

- [Electron ASAR integrity](https://www.electronjs.org/docs/latest/tutorial/asar-integrity)
- [Windows packaged desktop command launcher](https://learn.microsoft.com/en-us/powershell/module/appx/invoke-commandindesktoppackage)
- [Chromium private-pipe implementation](https://chromium.googlesource.com/chromium/src/+/lkgr/content/browser/devtools/devtools_agent_host_impl.cc)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Merge API compatibility and authentication](https://docs.merge.dev/merge-gateway/api-overview)
- [Merge GLM-5.3 Flash model details](https://docs.merge.dev/merge-gateway/models/details/zai-glm-5-3-flash)
- [StepFun Step 5 model specifications and reasoning controls](https://platform.stepfun.ai/docs/en/guides/models/step-5-preview)
- [OpenCode-maintained Step 5 provider metadata](https://raw.githubusercontent.com/anomalyco/models.dev/dev/providers/opencode/models/step-5-preview-free.toml)
- [OpenCode current model endpoint table](https://opencode.ai/v2/docs/console/models/)
- [OpenCode inference API and API-family endpoint paths](https://opencode.ai/v2/docs/console/api/inference/)
- [OpenCode v1.19.0 authenticated provider configuration loader](https://github.com/anomalyco/opencode/blob/v1.19.0/packages/core/src/plugin/provider/opencode.ts)
- [Step 5 provider-specific context/output rows](https://models.dev/models/stepfun/step-5-preview/)
