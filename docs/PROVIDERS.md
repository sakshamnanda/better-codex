# Adding providers and models

`config/providers.json` is the shared routing registry. The gateway, picker categories, provider defaults, credential form and OpenCode engine use it. `config/models.json` holds the desktop catalog, including each model's context limit, supported efforts and default effort. Keep provider secrets out of both files.

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
