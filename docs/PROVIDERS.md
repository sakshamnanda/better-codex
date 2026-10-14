# Adding providers and models

`config/providers.json` is the shared routing registry. The gateway, picker categories, provider defaults, credential form and OpenCode engine use it. `config/models.json` holds the desktop catalog, including each model's context limit, supported efforts and default effort. Keep provider secrets out of both files.

## Edit settings inside the app

Open **Settings → Better Codex**, or the **Better Codex** section of the model menu:

- **Providers:** edit an existing compatible provider's HTTPS API URL and default model. Changing destinations requires confirmation because that provider's key will go to the new URL. Protocols are shown, not silently changed. ChatGPT authentication and the genuine OpenCode client's endpoint are fixed.
- **API keys:** store up to 16 named profiles per provider and choose **Active API key**. Existing single keys appear as **Default** and remain encrypted without migration/re-encryption. Use **Add [provider] API key** to enter another key and give it a distinct name. Saved values appear as `********`; leave replacements blank to retain them. New unsaved rows can be discarded, while stored profiles are retained. Plaintext is never read back into the page, written to source configuration or passed on a command line. The private renderer pipe sends new values to a local Windows DPAPI encryption process over standard input.
- **Models:** new models/presets start with **From provider**, with blank limits rather than copied values. Enter an API ID or OpenRouter `@preset/slug`; leaving the ID field fetches metadata, and **Refresh metadata** repeats the read. Saving verifies automatic values server-side using the provider's selected credential, including pending named-key changes. **Customize** enables manual limits and reasoning choices when metadata is unavailable or you want overrides. Existing entries retain their manual settings. IDs/provider assignments remain fixed to preserve chats/profile mappings; unmapped models inherit the shared instruction profile. Reading metadata does not test inference or grant model access.

Metadata discovery uses read-only provider HTTPS APIs: OpenRouter's model catalog and a preset's designated version, Merge's account-scoped model/vendor catalog, and OpenCode's authenticated configuration endpoint. Presets retain their `@preset/slug` route; fixed fallback models use the lowest reported common limits and effort intersection. An alias must have an exact catalog entry. Dynamic presets without resolvable metadata require Customize. Private preset prompts, provider keys and account identifiers are never returned to the settings page. [OpenRouter preset metadata](https://openrouter.ai/docs/api/api-reference/presets/get-a-preset), [OpenRouter model metadata](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties), [Merge model metadata](https://docs.merge.dev/merge-gateway/api-overview/models/list).

Exact effort levels are used only when reported. If absent, **Provider default** sends no reasoning or OpenCode variant override; it does not disable thinking. You can use Customize to select verified effort levels. A reported default is retained; when only levels are reported, the editor explains its initial first-level selection. Automatic output limits are ceilings: the relay clamps an explicit caller cap but otherwise leaves the provider's output default intact. Published limits can still exceed what a particular key/vendor route serves. Missing context/output limits block an automatic save rather than silently assigning 1M/4096; manual limits remain available.

These sections render with the actual native settings page, grouped rows, text fields and dropdown/radio/checkbox menu components. They inherit app themes and keyboard/focus behavior. The native page scrolls its editor content separately from its Save footer, and the original unsaved-settings guard protects navigation. The required native control modules are checked against exact source hashes before import; unknown builds are refused.

**Models** has a provider selector and a heading showing ownership; only that provider's models appear below it. Each row shows its exact API ID; **Edit** reveals its capability fields. The add button is scoped to that provider. For example, the configured `zai/glm-5.3-flash` belongs to **Merge Gateway**; it is not listed under OpenRouter unless a separate compatible OpenRouter model route is registered.

**Save for next launch** uses the same registry/instruction and exact-build hash checks as the launcher. It updates the public source registry/catalog and prepares a new ignored deployment with encrypted keys copied from the currently selected setup. Keys are replaced only in that new folder. Failed saves retain the previous selection and restore this save's source edits; an already-running deployment is never rebuilt or removed. Close and reopen through the custom launcher to apply a saved change. Provider/model switching after launch still needs no restart.

For two Merge Gateway accounts, keep the original key under **Default** (or rename it), add a second named key, and select the desired account in **Active API key**. Save and relaunch to apply it. This selection is provider-wide, so all Merge models/chats use that chosen key; it is not a per-chat key override or automatic retry/rotation. Other providers keep their own selection. The private ignored `gateway/keys/Profiles.json` stores profile IDs/names and the active ID, never key values. Each slot has its own DPAPI-encrypted file; default slots retain the original filenames for compatibility. The legacy key-setup form replaces the provider's currently active slot. Previous deployments retain their full key/profile snapshot for rollback.

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

   This is a field fragment, not a complete model object. Keep text-only input for this gateway until attachments are tested. Recheck effort metadata rather than copying Nemotron's effort levels.

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

Changing the configuration prepares the next launch; this project does not hot-reload a running service. Switching among configured providers/models in chats needs no restart.

## Context-limit errors and compaction

An authenticated Merge GLM request can fail with `context_length_exceeded` even when the model catalogue advertises a larger window. Treat the serving request's rejection as authoritative; changing keys or effort does not shorten the history. The gateway preserves that known error code through both relays and records only bounded, fixed diagnostic vocabulary, parameter names and size counts. It never stores the raw upstream error body.

The verified Windows backend uses `compaction_trigger` requests and requires a real `compaction` output with `encrypted_content`. Compaction now uses your signed-in ChatGPT **GPT-6.1 Sol** as the checkpoint model, including when an external model is selected. It then makes one bounded, tool-free request to that same trusted native origin for a portable text summary. This uses ChatGPT plan usage; it does not switch provider keys or charge an external provider. The selected chat model remains unchanged.

The actual server-issued encrypted checkpoint remains in Codex's normal history, so the native app can consume it after rollback. The portable summary is protected with Windows DPAPI in ignored `.local/context-cache`, identified by a checkpoint hash; raw checkpoint/auth values are not stored there. External requests replace only a verified checkpoint with its portable text summary and receive fresh provider-only credentials. Native authentication and opaque checkpoint state never cross to an external endpoint. New model/project instructions still apply after compaction, including the required AGENTS.md workflow.

Checkpoint completion is withheld until its portable summary is verified and stored. A missing, corrupt or failed summary rejects continuation instead of silently discarding context. Unknown checkpoints created outside Better Codex need compaction again through the compatible helper. Compaction summarizes working context; it does not edit project files or delete the saved transcript. Optional IDs on plain native input items are omitted to avoid cross-provider prefix validation (including functions translated to custom/search calls). Call IDs, actual tool results and encrypted native items remain intact.

Offline checks: `python tests/check-compaction.py` and `python tests/check-compaction-runtime.py`. The latter uses the installed backend with mocked inference and a harmless local echo, verifying compaction and tool use in the same external-model thread. The helper source hashes and installed build remain guarded; stage a fresh deployment for code changes rather than editing a running helper.
