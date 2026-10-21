# Adding providers and models

`config/providers.json` is the shared routing registry. The gateway, picker categories, provider defaults, credential form and OpenCode engine use it. `config/models.json` holds the desktop catalog, including each model's context limit, supported efforts and default effort. Keep provider secrets out of both files. Optional boolean `enabled` flags on providers and their model route entries default to `true`; disabling keeps configuration and metadata.

## Pasted images

Checked on 2026-10-20, inline PNG, JPEG, WebP and GIF inputs are enabled for Experiential GLM Flash, NanoGPT GLM Flash Uncensored, Arnict GLM Flash Abliterated, all three Routeway GLM Flash entries, and LayerCloud GLM Flash, GPT-6 Astra and GPT-5.6 Sol. The gateway validates inline data before reading provider credentials and converts Responses `input_image` parts to Chat Completions `image_url` parts. Text/image order and detail are preserved; native `original` detail maps to `high` for Chat Completions.

Sources: [Experiential catalog](https://api.experientiallabs.ai/api/models/glm-5.3-flash-abliterated), [NanoGPT detailed catalog](https://nano-gpt.com/api/v1/models?detailed=true), [Arnict Flash](https://arnict.com/models/glm-5.3-flash-abliterated), [Routeway catalog](https://api.routeway.ai/v1/models), and the LayerCloud model pages linked below. Routeway's documented Flex suffix uses the same cybersecurity model capabilities.

Arnict full GLM, LayerCloud full GLM and DeepSeek, and OpenRouter Nemotron remain text-only according to their public metadata. Merge and OpenCode metadata require authentication; private OpenRouter presets cannot be confirmed from a public catalog, so their capabilities stay unchanged. Videos, native file IDs and remote attachment URLs remain unsupported. Offline checks cover both relay hops and credential isolation; live image inference and desktop paste behavior still need verification after the next launch.

## Edit settings inside the app

Experiential Labs registers [GLM 5.3 Flash Uncensored](https://platform.experientiallabs.ai/models/glm-5.3-flash-uncensored) through `https://api.experientiallabs.ai/v1/chat/completions`. It uses the `glm-5.3-flash-abliterated` alias documented on the provider's [uncensored models page](https://www.experientiallabs.ai/uncensored), keeping Routeway's existing ID and chats intact. Both spellings resolve to the same model in the [public catalog](https://api.experientiallabs.ai/api/models/glm-5.3-flash-abliterated). Checked on 2026-10-19, the catalog reports a 1,048,576-token context, 131,072-token output limit, low/high/max reasoning and a max default. These values use Customize. Add a separate key under **Providers → Experiential Labs → API keys**. The route reuses the GLM profile and text/function-tools bridge; inline image inputs are forwarded; video remains unavailable. Live replies, streaming and tools still need verification with an Experiential Labs key.

LayerCloud also registers [GPT-6 Astra (Jailbroken)](https://ai.layercloud.org/pricing/openai-gpt-6-astra-jailbreak) as `openai/gpt-6-astra:jailbreak` and [GPT-5.6 Sol (Jailbroken)](https://ai.layercloud.org/pricing/openai-gpt-5-6-sol-jailbreak) as `openai/gpt-5.6-sol:jailbreak`, using the same LayerCloud endpoint and key. Their public Markdown pages, checked on 2026-10-19, report 1,050,000-token contexts and 128,000-token output limits. Astra publishes low/medium/high/xhigh/max reasoning; Sol also supports none. Low is the initial local selection; neither page publishes a default. Both reuse `chatgpt.md` and the text/function-tools bridge, with inline image input enabled. Live compatibility remains unverified. The original `gpt-6-astra` and `gpt-5.6-sol` models keep ChatGPT authentication and routing.

LayerCloud registers [DeepSeek V4.1 Flash (Jailbreak)](https://ai.layercloud.org/pricing/deepseek-deepseek-v4-1-flash-jailbreak) as `deepseek/deepseek-v4.1-flash:jailbreak`, [GLM 5.3 (Jailbroken)](https://ai.layercloud.org/pricing/zai-glm-5-3-jailbreak) as `zai/glm-5.3:jailbreak` and [GLM 5.3 Flash (Uncensored)](https://ai.layercloud.org/pricing/zai-glm-5-3-flash-uncensored) as `zai/glm-5.3-flash:uncensored`, through `https://ai.layercloud.org/v1/chat/completions`. Add a separate key under **Providers → LayerCloud → API keys**. Their public Markdown pages, checked on 2026-10-19, report context/output limits of 1,048,576/943,718 tokens for DeepSeek, 1,310,720/262,144 for GLM and 1,310,720/131,072 for GLM Flash. All publish low/high/max reasoning; low is the initial local selection because no default is published. Limits use Customize; the model-list API requires authentication. The routes reuse the existing DeepSeek and GLM instruction profiles and text/function-tools bridge. GLM Flash forwards inline image input; video remains unavailable. Live replies, streaming, tools and reasoning behavior still need verification with a LayerCloud key.

Routeway also registers [GLM 5.3 Flash Cybersecurity](https://routeway.ai/models/glm-5.3-flash-cybersecurity) with standard and **Flex** picker entries. Choose **GLM 5.3 Flash Cybersecurity (Flex)** to send `glm-5.3-flash-cybersecurity:flex`; Routeway documents this [model suffix as equivalent to `service_tier: "flex"`](https://docs.routeway.ai/guides/chat-completions/service-tiers). Both entries use the existing Routeway key and GLM instruction profile. Its public catalog, checked on 2026-10-19, reports a 1,000,000-token context and default/flex tiers. Exact reasoning levels and an output maximum are absent, so both use **Provider default** reasoning and a configurable local 32,768-token output cap. The bridge exposes text, inline images and function tools. The suffix remains intact through both relay hops; live Flex billing and capacity still need verification with a Routeway key.

Routeway registers [GLM 5.3 Flash Uncensored](https://routeway.ai/models/glm-5.3-flash-uncensored) as `glm-5.3-flash-uncensored` through `https://api.routeway.ai/v1/chat/completions`. Add a separate Routeway key under **Providers → Routeway → API keys**. Its [public catalog](https://api.routeway.ai/v1/models), checked on 2026-10-19, reports a 262,144-token context and none/minimal/low/medium/high/xhigh reasoning levels. Low is the initial selection; it is a local choice. The catalog omits an output maximum, so Customize uses a local 32,768-token output cap, which can be adjusted and is not a published provider limit. The route reuses the GLM instruction profile and text/function-tools bridge. Inline image input is enabled. [Routeway documents streaming, tool calls and reasoning controls](https://docs.routeway.ai/api-reference/ChatCompletions/completions); live behavior still needs verification with a Routeway key. Existing NanoGPT and Arnict routes retain their own IDs and credentials.

Arnict uses its [Chat Completions endpoint](https://arnict.com/docs/chat-completions) with a separate Arnict key under **Providers → Arnict → API keys**. Create a key in the [Arnict dashboard](https://arnict.com/dashboard/keys). The registered [GLM 5.3 Flash Abliterated](https://arnict.com/models/glm-5.3-flash-abliterated) (`zai/glm-5.3-flash-uncensored`) and [GLM 5.3 Abliterated](https://arnict.com/models/glm-5.3-abliterated) (`zai/glm-5.3-uncensored`) use the published 1,048,576-token context and 131,072-token output limits. Both expose low/high/max reasoning, initially low; Arnict does not publish a default. Limits use Customize because its model-list API does not promise detailed capabilities. Both reuse the GLM instruction profile and the function-tools bridge. Flash also forwards inline images; the full GLM model remains text-only and video is unavailable. Live replies, tool support and reasoning behavior still need verification with an Arnict key. NanoGPT's distinct `z-ai/` model IDs and keys remain separate.

NanoGPT is registered with its [OpenAI-compatible Chat Completions endpoint](https://docs.nano-gpt.com/) and defaults to `z-ai/glm-5.3-flash-uncensored`. Its [detailed public catalog](https://nano-gpt.com/api/v1/models?detailed=true) reports a 1,048,576-token context window, 32,768-token output limit and low/high reasoning; low is the initial selection. These verified values use Customize because the basic catalog omits limits and efforts. This route supports text, inline images and client function tools. Add a NanoGPT API key under **Providers → NanoGPT → API keys**. Model IDs must be unique across providers.

NanoGPT's `z-ai/glm-5.3-flash-cybersecurity` entry is retired. Its metadata and GLM instruction mapping remain available for existing history, but the model is hidden from the picker and cannot receive new requests. The active uncensored variant uses the same GLM 5.3 Flash instruction profile.

In **Models → Edit**, NanoGPT models have **Upstream provider** and **Service tier** dropdowns. **Load providers and tiers** reads public model-specific provider IDs and the detailed catalog's `supported_service_tiers`; unavailable providers cannot be selected. **Automatic** sends no override. Selections apply to that model across chats; other services do not receive them. Selecting a provider uses pay-as-you-go billing and bypasses subscription coverage. Provider limits, supported efforts and availability may differ; loading options does not change saved limits. [NanoGPT provider selection](https://docs.nano-gpt.com/api-reference/miscellaneous/provider-selection).

Service tiers are offered only when reported by the detailed model catalog. Flex requests lower-cost, variable-capacity processing; Fast/Priority requests higher-priority capacity at the applicable rate. A forced provider may ignore a tier it does not support. Saved choices remain visible after reopening; load options again to check current support. [NanoGPT service tiers](https://docs.nano-gpt.com/api-reference/endpoint/chat-completion#service-tiers-priority).

Open **Settings → Better Codex**:

- **Providers:** **Edit** opens a native popup for the URL/default model; **Add provider** opens creation. The enable switch saves automatically. Disabling retains models and keys but hides models from the picker and blocks new inference before credential reads. Running responses keep their old settings. ChatGPT stays built in; existing protocols and the OpenCode endpoint stay fixed. Changed external destinations require confirmation.
- **API keys on each provider card:** expand **API keys**, store up to 16 named profiles and choose **Active API key**. **Add API key** creates another named profile. Saved indicators show `********`; blank replacement fields retain the saved key. New/replacement keys save after blur. Incomplete new profiles stay unsaved. Editors are scoped by provider/profile ID. Plaintext is never read back, written to source configuration or passed on a command line. The private renderer pipe sends new values to the local Windows DPAPI writer over standard input. Legacy key shortcuts navigate to Providers.
- **Models:** select a provider and search its names/API IDs. Enable switches save automatically. Disabled models remain editable but leave the picker/routing; another enabled default is chosen when available. **Edit** and **Add model** use native dialogs. New models/presets start with **From provider** and blank limits. Leaving a new API ID field fetches metadata; **Refresh metadata** explicitly repeats it. **Customize** enables manual limits/reasoning choices. Finish creation with **Add model**; X discards an unfinished entry without losing other edits. Existing IDs/provider assignments stay fixed to preserve chats/instructions. Metadata discovery does not test inference or grant access.

Changes save automatically after a 400 ms pause. Keys and existing provider URLs wait for blur; destination confirmation remains. Required fields must be complete. Saves are serialized; a completed save cannot overwrite a newer draft or clear a key typed during that save. Failures retain the local draft/key for **Retry** and keep the last working setup active. Creation still uses **Add**. **Refresh models** is a separate catalog/UI refresh; there is no ordinary Save and apply button.

Metadata discovery uses read-only provider HTTPS APIs: OpenRouter's model catalog and a preset's designated version, Merge's account-scoped model/vendor catalog, and OpenCode's authenticated configuration endpoint. Presets retain their `@preset/slug` route; fixed fallback models use the lowest reported common limits and effort intersection. An alias must have an exact catalog entry. Dynamic presets without resolvable metadata require Customize. Private preset prompts, provider keys and account identifiers are never returned to the settings page. [OpenRouter preset metadata](https://openrouter.ai/docs/api/api-reference/presets/get-a-preset), [OpenRouter model metadata](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties), [Merge model metadata](https://docs.merge.dev/merge-gateway/api-overview/models/list).

Exact effort levels are used only when reported. If absent, **Provider default** sends no reasoning or OpenCode variant override; it does not disable thinking. You can use Customize to select verified effort levels. A reported default is retained; when only levels are reported, the editor explains its initial first-level selection. Automatic output limits are ceilings: the relay clamps an explicit caller cap but otherwise leaves the provider's output default intact. Published limits can still exceed what a particular key/vendor route serves. Missing context/output limits block an automatic save rather than silently assigning 1M/4096; manual limits remain available.

These sections render with the actual native settings page, grouped rows, text fields and dropdown/radio/checkbox menu components. They inherit app themes and keyboard/focus behavior. Native dialogs scroll their forms separately from their footer actions, and the original unsaved-settings guard protects navigation. The required native control modules are checked against exact source hashes before import; unknown builds are refused.

**Models** has a provider selector and a heading showing ownership; only that provider's models appear below it. Each row shows its exact API ID; **Edit** opens its capability popup. **Refresh models** and **Add model** sit together in that heading. Add is scoped to the selected provider; refresh updates the whole native picker catalog without fetching provider metadata. The refresh control remains available if all external providers were removed. Unsaved drafts disable refresh to protect edits. Settings use the original sidebar/close navigation, with no custom Back button. For example, the configured `zai/glm-5.3-flash` belongs to **Merge Gateway**; it is not listed under OpenRouter unless a separate compatible OpenRouter model route is registered.

Automatic saving, in the live-enabled helper, uses registry/instruction and exact-build hash checks before preparing a new ignored deployment with encrypted keys copied from the selected setup. It atomically publishes a request-settings snapshot without draining active chats. Each response keeps its original routes, profiles, credential folder and OpenCode engine. An authenticated private relay header binds the inner hop to that same snapshot, even when settings change between the hops. The header never goes to a provider, is never recorded in diagnostics, and expired snapshots are rejected. New requests use the new settings; deleting a model rejects future requests for it without cancelling a response already running. Existing deployment files remain unchanged. New OpenCode credentials or model metadata prepare an isolated engine first; old engines close after their last pinned response. **Retry apply** appears only for unapplied saved changes and retries them after a validation/publication failure. Helpers lacking the reload hook save for the next launch. Live apply refuses code/build changes rather than importing new code into a running helper.

For new models/capability changes, click **Refresh models** after saving. The upgraded launcher removes its managed static catalog override and serves the verified native/custom metadata through dynamic discovery. The refresh updates only a cache that bears this helper's catalog tag and matching version/authentication identity; other sessions' caches and unknown formats are refused. Metadata backups are Windows-encrypted, concurrent writes are checked before publication, and close restores the original cache only if this helper still owns the current entry. Refresh models reloads the UI so its native model query reads the new cache. It does not restart the backend, alter sign-in, interrupt agents or discard terminal sessions. A pinned-backend localhost check verified a new context limit, both chat IDs, retained old-model selection and an existing native PTY after refresh.

Routine settings saves use `.local/settings-*` data snapshots and `.local/settings-path.txt`; the reusable code/runtime selection remains `.local/deployment-path.txt`. Snapshot hashes cover configuration, instructions and the credential writer, and bind to the already verified runtime checksum manifest. They cannot replace runtime code or the installed-build identity. Startup still verifies the full runtime/installed build before loading a saved data snapshot. A code update folds the latest saved keys/configuration into the new runtime and retains the old snapshot pointer for rollback.

Settings saves do not copy the OpenCode executable or vendor tree. Replacement engines keep writable config/data/cache directories isolated and reference the pinned vendor tree through one NTFS directory junction. A hash manifest verifies all vendor files before their first use in a helper process. A matching root dependency lock prevents the official client's installer from rematerializing packages; the relay imports the verified module directly. Inactive-key edits do not replace an engine; an active OpenCode credential/model change may still need engine preparation. Offline checks use the actual pinned engine with a dummy key and localhost inference, and verify shared vendor contents remain unchanged.

Older helpers already running with a static catalog need one update activation before this path is available. The static manager cannot be replaced by `config/batchWrite` or a renderer-only reload; helper code updates are kept separate from subsequent model additions. Signed files, native authentication, approvals and project instructions remain intact.

For two Merge Gateway accounts, keep the original key under **Default** (or rename it), add a second named key, and select the desired account in **Active API key**. In a live-enabled helper, changing Active API key automatically switches subsequent requests. This selection is provider-wide, so all Merge models/chats use that chosen key; it is not a per-chat key override or automatic retry/rotation. Other providers keep their own selection. The private ignored `gateway/keys/Profiles.json` stores profile IDs/names and the active ID, never key values. Each slot has its own DPAPI-encrypted file; default slots retain the original filenames for compatibility. The legacy key-setup form replaces the provider's currently active slot. Previous deployments retain their full key/profile snapshot for rollback.

The native settings sidebar module is customized in memory only after its exact source hash matches. No signed package file is changed. Only the owned app renderer's default `app://-` context can invoke the bounded settings actions; plugin/browser frames cannot invoke them. Rollback deployments remain local, and `support/Previous-Settings-Deployment.txt` records each staged setup's predecessor. No live inference or app restart is performed by the settings editor itself.

## Add a model to an existing provider

1. Add its catalog metadata to `config/models.json`, using a compatible existing entry as the starting point. Set the actual model ID, label, context limit and supported/default efforts. Do not invent effort support.
2. Add the same model ID under that provider's `models` in `config/providers.json`. Set a bounded `output_limit`. For a genuine OpenCode model with verified effort variants, set `send_variant: true`; otherwise leave it unset. Update `default_model` if desired.
3. After closing the project-based custom-provider app, run `python scripts/build-deployment.py` and the local checks in the README. Launch with `scripts/Launch.cmd` and test a fresh chat before relying on the new route.

The picker categories, gateway allowlist, supported effort validation and OpenCode context limits follow the configuration. Model IDs must be globally unique; a model ID may route to only one provider.

## Model-wide instruction profiles

`config/instructions.json` maps exact model IDs to Markdown filenames under `config/instructions/`. Every request gets the shared `default` profile plus its mapped model profile. An unmapped model gets the shared default. This applies across projects and simultaneous chats through the custom launcher; directory-based `AGENTS.md` remains in the original request context. Preferences defer to explicit project/user instructions and Codex permissions.

Example mapping entry under `models`:

```json
"nvidia/nemotron-3-ultra-550b-a55b:free": "nemotron.md"
```

Edit `nemotron.md` to give Nemotron its own guidance. To separate two ChatGPT models, create another Markdown file and change only that model ID's mapping. No project `AGENTS.md` file is swapped or rewritten. Profiles are loaded at startup, included once per desktop request, and not appended to stored history. Files must remain inside the instructions folder, with at most 32 KiB each and 48 KiB combined. The loader validates both limits before deployment; files are never silently truncated. Keep them focused; never include keys or private tokens.

After editing, close the custom-provider app and run `python scripts/build-deployment.py`, then relaunch through the custom desktop shortcut. One relaunch loads new profile content; switching among configured models afterward needs no restart. Changes to source files do not silently modify an already-running deployment.

Each request's local `support/Mixed-Results.json` event records `model_profile_bytes` and `model_profile_sha256` for the loaded profile text. Compare this with the deployed profile files to confirm which snapshot was supplied, without logging instruction text or credentials. Delivery of a profile does not guarantee that a model follows every rule; original user/project instructions may also take precedence.

Every external route also receives a shared project-workflow rule after its model preferences. It directs the model to read the current project's applicable `AGENTS.md` files and required referenced files, including `@path` imports and project rulebooks, before substantive work. It requires a fresh read on model/project switches and when instruction content changes or is lost during compaction; an unchanged confirmed read for that same model/project can be reused between tool calls. Before finishing, the model must check the project's required checks, commits and authorized handoffs. Chat replies are not automatically sent to a manager. This shared rule applies to existing and future external providers without copying project-specific rules into model profiles. It does not read files behind Codex's permissions or grant messaging authorization; following it still depends on the model.

## Manual example: GLM 5.3 Flash on OpenRouter

GLM has **not** been registered by this example. OpenRouter's public catalog checked on 2026-10-11 lists `z-ai/glm-5.3-flash` as paid, with a 1,048,576-token context and reasoning efforts `low`, `high`, `max` (default `max`). The `:free` variant was absent from that current API catalog, despite a public model page existing. Check the current public catalog before adding it: [OpenRouter models API](https://openrouter.ai/api/v1/models), [model page](https://openrouter.ai/z-ai/glm-5.3-flash), [reasoning metadata documentation](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens). No charged request is needed to read that metadata.

1. In `config/providers.json`, add an entry to the existing `openrouter.models` object:

   ```json
   "z-ai/glm-5.3-flash": {"output_limit": 16384}
   ```

   Keep the existing Nemotron entry and OpenRouter endpoint. The output cap includes reasoning; larger caps can cost more. The provider's default model need not change.

2. In the `models` array in `config/models.json`, copy the whole existing Nemotron object to a **new** object. Keep its Codex tool/workspace fields, then change these fields:

   ```json
   "slug": "z-ai/glm-5.3-flash",
   "display_name": "GLM 5.3 Flash (OpenRouter)",
   "description": "GLM 5.3 Flash through OpenRouter; paid model, compatibility not yet tested.",
   "context_window": 1048576,
   "max_context_window": 1048576,
   "default_reasoning_level": "max",
   "supported_reasoning_levels": [
     {"effort": "low", "description": "Low reasoning effort"},
     {"effort": "high", "description": "High reasoning effort"},
     {"effort": "max", "description": "Maximum reasoning effort"}
   ],
   "supports_reasoning_effort_updates": true,
   "input_modalities": ["text"]
   ```

   This is a field fragment, not a complete model object. Enable image input only when the provider publishes image support and the adapter handles it; native file attachments remain unsupported. Recheck effort metadata rather than copying Nemotron's effort levels.

3. Create `config/instructions/glm-5.3-flash.md` with your GLM-specific guidance. Add this entry under `models` in `config/instructions.json`:

   ```json
   "z-ai/glm-5.3-flash": "glm-5.3-flash.md"
   ```

   This step is optional if the shared default is sufficient.

4. Close the custom-provider app normally. From the `better-codex` directory, run:

   ```powershell
   python scripts/build-deployment.py
   python tests/check-provider-registry.py
   python tests/check-model-profiles.py
   node tests/check-picker.cjs
   python scripts/build-deployment.py --check
   ```

   Reopen with **Codex (Custom Providers)**. Select **OpenRouter**, then **GLM 5.3 Flash**. It uses the existing encrypted OpenRouter key; no new key is needed. Verify a real reply and a harmless Codex tool call before relying on it. Responses compatibility and effort behavior must be tested; catalog registration alone is not proof they work. Selecting the paid model and sending messages can incur OpenRouter charges.

## Add a provider using an existing adapter

In **Settings → Better Codex → Providers**, choose **Add provider**. Give it a unique ID, display name, full HTTPS inference URL and either **Responses** or **Chat Completions**. Save it, then add its keys and models in the corresponding settings sections. Empty providers can be saved but cannot be selected in a chat until they have a model. OpenCode Zen retains its separately verified client adapter; adding a generic provider does not add a new protocol or authentication scheme.

Provider/model popups have **Delete provider** and **Delete model**; expanded key editors have **Delete API key**. Confirmed deletions save automatically. Removing the active key selects another remaining usable profile; deleting the last key leaves no credential and never falls back to anonymous access. Blank replacement fields still preserve retained keys. A removed provider's keys are removed from the fresh deployment copy, while old encrypted rollback copies remain.

Removing a model or provider hides its models from the catalog and removes their routes. Existing chats keep their model IDs and need an explicit replacement selected before continuing. Metadata and instruction files are retained for history and an explicit re-add; retired model IDs cannot be reassigned to another provider. ChatGPT cannot be deleted. Removing a default model chooses the first remaining model for future selections; it does not change existing chats.

After saving model additions or removals, use **Refresh models** for a renderer reload. Neither apply nor refresh requires idle chats. Metadata publication uses its own short lock, preserving cache ownership and concurrent-write checks. They never cancel work or restart the backend. Installing changed helper code is a separate update activation; a renderer reload cannot replace running Python code.

Add a new top-level provider entry and its model catalog entries:

```json
{
  "example": {
    "label": "Example Provider",
    "adapter": "responses",
    "endpoint": "https://api.example.com/v1/responses",
    "default_model": "example-model-id",
    "models": {
      "example-model-id": {"output_limit": 4096}
    }
  }
}
```

Merge this entry with the existing providers; this is a placeholder, not a working service. Rebuild, then run `scripts/Setup-Keys.cmd`. The encrypted local key form automatically includes configured providers.

The existing `responses` adapter requires compatible streaming Responses events and bearer authentication. `chat_completions` uses the existing text/function-tools bridge. Matching a protocol name alone does not establish compatibility: verify actual replies, tool calls, effort behavior and cross-provider history. Native authentication remains restricted to ChatGPT; external requests use fresh provider-only headers and reject unknown models, nonportable input and redirects.

The `opencode` adapter is restricted to the genuine OpenCode Zen client. It keeps its isolated data directories and data-only relay tools, while Codex executes actual workspace tools through its own approvals.

## A different protocol or authentication scheme

Add a small adapter under `src/gateway/` and connect it in `provider_relay.py`; extend registry validation for that specific protocol. OAuth or extra required headers need explicit, verified implementation. Never bypass validation or forward native account headers. Keep desktop launch/rollback and UI code independent of provider protocol details.

The live-enabled helper stages immutable settings and publishes them for new requests while old responses continue. Model additions use Refresh models for the native picker; code/build changes still require update activation. Switching configured providers/models in chats needs no restart.

## Context-limit errors and compaction

External models automatically compact at 128,000 tokens, or the existing lower threshold for smaller context windows. Native ChatGPT thresholds stay unchanged. After the observed 41K baseline, this leaves about 87K tokens for ongoing work. Compaction still preserves the native checkpoint and its verified portable summary.

Shared external-model guidance asks models to reuse unchanged reads, search before reading focused sections, check freshness after changes and retrieve missing evidence from truncated output. Native `exec_command` and `write_stdin` calls default to 2,000 output tokens when the advertised schema supports that optional field and the model omits it. Explicit limits are preserved, so the model can request more detail when needed. Codex handles truncation through its normal tool output; the gateway does not remove saved messages, instructions or tool results, cache file contents, or rewrite commands. Shared gateway instructions are inserted once across both relay hops.

Offline checks: `python tests/check-token-efficiency.py`, `python tests/check-context-budget.py` and `python tests/check-compaction-runtime.py`. The runtime check uses mocked inference, a verbose terminal fixture and multiple turns after compaction to check the 128K trigger, output bounds and continued work without repeated checkpoints.

An authenticated Merge GLM request can fail with `context_length_exceeded` even when the model catalogue advertises a larger window. Treat the serving request's rejection as authoritative; changing keys or effort does not shorten the history. The gateway preserves that known error code through both relays and records only bounded, fixed diagnostic vocabulary, parameter names and size counts. It never stores the raw upstream error body.

The verified Windows backend uses `compaction_trigger` requests and requires a real `compaction` output with `encrypted_content`. Compaction now uses your signed-in ChatGPT **GPT-6.1 Sol** as the checkpoint model, including when an external model is selected. It then makes one bounded, tool-free request to that same trusted native origin for a portable text summary. This uses ChatGPT plan usage; it does not switch provider keys or charge an external provider. The selected chat model remains unchanged.

The actual server-issued encrypted checkpoint remains in Codex's normal history, so the native app can consume it after rollback. The portable summary is protected with Windows DPAPI in ignored `.local/context-cache`, identified by a checkpoint hash; raw checkpoint/auth values are not stored there. External requests replace only a verified checkpoint with its portable text summary and receive fresh provider-only credentials. Native authentication and opaque checkpoint state never cross to an external endpoint. New model/project instructions still apply after compaction, including the required AGENTS.md workflow.

Checkpoint completion is withheld until its portable summary is verified and stored. A missing, corrupt or failed summary rejects continuation instead of silently discarding context. Unknown checkpoints created outside Better Codex need compaction again through the compatible helper. Compaction summarizes working context; it does not edit project files or delete the saved transcript. Optional IDs on plain native input items are omitted to avoid cross-provider prefix validation (including functions translated to custom/search calls). Call IDs, actual tool results and encrypted native items remain intact.

Offline checks: `python tests/check-compaction.py` and `python tests/check-compaction-runtime.py`. The latter uses the installed backend with mocked inference and a harmless local echo, verifying compaction and tool use in the same external-model thread. The helper source hashes and installed build remain guarded; stage a fresh deployment for code changes rather than editing a running helper.
