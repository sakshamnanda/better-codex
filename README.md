# better-codex

Windows Codex desktop custom providers, using the original installed signed app and its normal profile.

## What was changed

- A local inference gateway chooses the provider from each request's model ID. ChatGPT uses its normal signed-in service; Nemotron uses OpenRouter; Space Bunny uses the genuine isolated OpenCode client. Models remain independent between chats.
- Merge Gateway adds `zai/glm-5.3-flash` through its OpenAI-compatible Responses endpoint, with a separate Merge key. Replies and Codex tool use have been verified in the signed desktop setup; each account still needs model access and credit.
- The original model/effort controls gain ChatGPT, OpenRouter, Merge Gateway and OpenCode Zen categories. A version-checked static UI resource is supplied in memory over private inherited pipes. Package files, signatures, security fuses and permissions remain intact. There is no debugging network port.
- A Windows package-context launcher starts the actual installed executable. Backed-up user settings point to the local gateway and dynamic model discovery while it runs. Closing the app restores ordinary settings; manual rollback is also provided.
- Codex retains tool execution, approvals, project instructions and chat history. The OpenCode helper returns data-only tool requests; it does not execute the caller's shell commands itself. Cross-provider history is normalized, and private native authentication is not sent to external providers.
- For external models, `/compact` creates a genuine ChatGPT checkpoint and one tool-free portable summary using your ChatGPT sign-in, while retaining the selected external model. The summary is Windows-encrypted locally; external continuation receives text rather than opaque native state. Native ChatGPT manual and automatic compaction use the ordinary native stream without requiring a portable summary. The saved transcript and native rollback checkpoint remain intact.

This is a tested local customization, not an official provider-picker extension. Updates require a compatibility review; source/hash guards refuse unknown builds.

## Use

Use the **Codex (Custom Providers)** desktop shortcut for provider support. The existing ordinary Codex shortcut remains available. Provider/model/effort switching needs no restart after launch.

The custom Desktop and Start menu shortcuts target Windows PowerShell with the project launcher arguments and the distinct `BetterCodex.CustomProviders` shortcut identity. To create or repair them without launching the app, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/Install-Shortcuts.ps1`. Existing shortcuts are backed up under `.local/shortcut-backups/`. If an older pinned Start tile opens ordinary Codex, unpin it and pin **Codex (Custom Providers)** from Start search again. Pin the custom shortcut entry rather than the running app's ordinary taskbar identity. Close the ordinary app before launching the custom setup; the launch guard preserves any open window.

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/Select-Deployment.ps1 -Mode Launch -Preflight` verifies the selected launcher/build and reports whether Codex is still running, without changing configuration or processes.

For rollback, close Codex and run `scripts/Rollback.cmd`. Sign-in and chat databases are retained. Select a ChatGPT model before continuing an external-model chat through the ordinary launcher.

Open **Settings -> Better Codex -> Providers** or **Models**. Provider cards have native enable switches; **Edit** opens a themed popup for their URL and default model. **API keys** expands directly on the provider card. ChatGPT keeps the app's sign-in; the verified OpenCode endpoint stays fixed.

Models are grouped by provider and searchable by name or API ID. **Edit** and **Add model** open native popups for capabilities and reasoning options. Each model has an enable switch. Disabling retains configuration, instructions and encrypted keys, while hiding disabled models from the picker and blocking new requests. Running responses keep their original settings. Another enabled model becomes the default when available.

New models/presets default to **From provider**. Enter an API model ID or OpenRouter `@preset/slug`; leaving the new ID field fetches metadata. **Refresh metadata** repeats the read; routine edits retain saved limits. Unknown values stay blank; use **Customize** for missing limits or overrides. **Provider default** sends no reasoning override when exact levels are unavailable. Published limits are ceilings, not guarantees for every account or routed endpoint.

Each provider supports up to 16 named key profiles. Use **Add API key**, name the profile, enter its key, then choose **Active API key**. Blank replacement fields retain saved keys, which stay encrypted with Windows DPAPI. Selection is provider-wide, with no automatic rotation or fallback.

Settings save automatically after a short typing pause. Keys and existing provider URLs wait for blur; changed destinations still require confirmation. Incomplete entries stay unsaved. Finish new providers/models with their **Add** action; X discards an unfinished model. Failed saves show **Retry**, preserve the draft and keep the last working setup. Native dialogs, search and menus inherit app themes and keyboard behavior; the original settings-change guard protects unsaved edits.

Automatic saves publish verified settings for new requests without waiting for idle chats. Each response pins its routes, instructions, credential folder and engine through the private relay hop. OpenCode changes prepare a separate engine first; the old engine closes after its last request. **Retry apply** appears only while saved changes remain unapplied. Earlier deployments and encrypted rollback data remain available.

Routine saves create only a small data snapshot: configuration, instructions, encrypted keys and the pinned credential writer. They reuse the verified code/UI/engine assets without invoking the deployment builder or copying vendor packages. Existing model metadata is retained; adding a model or explicitly choosing **Refresh metadata** fetches it. Unchanged keys do not spawn an encryption process. Key-only edits need no UI reload. A full build and installed-app hash verification remain required for code updates and startup.

After adding models or changing their capabilities, click **Refresh models** in Better Codex settings. It refreshes this helper's verified metadata cache and reloads the UI. The same backend keeps its chats, agents and terminal sessions. The launcher uses dynamic model discovery instead of the startup-only `model_catalog_json` manager. Cache updates retain authentication identity/version, require this helper's catalog tag, back up metadata with Windows encryption, and refuse unrelated or concurrent cache changes. Original cache data is restored on close only while this helper still owns it.

**Refresh models** sits beside **Add model** in the Models list header and stays available when the provider list is empty. It is disabled while draft edits are unsaved. The footer shows saving/error status, discard for unsaved edits and retry only when needed; navigation uses the app's ordinary settings sidebar and close control, with no custom Back button.

An older already-running helper needs one update activation to load this code and the dynamic manager; reloading its renderer cannot replace Python code or the static manager. After activation, adding models needs only Add model followed by Refresh models. Code/build changes remain refused by live apply. Editing metadata does not establish provider access or compatibility.

Active deployment folders stay in place until their session closes, because their key suppliers and rollback state reference them. The launcher reads the ignored `.local/deployment-path.txt` selection for the next launch. Preparing a replacement does not change the running app or its settings.

## Model-wide instructions

Edit the Markdown files in `config/instructions/` and map exact model IDs to them in `config/instructions.json`. The shared default and selected model profile are supplied on every request, across all projects/chats using this launcher. Original project/user instructions and Codex permissions remain in place. The profile is not added to stored chat history; switching models selects its matching profile for the next request. These are editable starter preferences, not a guarantee of identical model behavior.

Profiles load from the verified deployment at service startup. After changing them, close the custom-provider app, rebuild and relaunch. See `docs/PROVIDERS.md` for profile mapping and manual model registration. Do not put secrets in instruction files; these source files are tracked by Git.

## Layout

| Path | Purpose |
| --- | --- |
| `src/desktop/` | Signed-app launcher, reversible settings and in-memory UI delivery |
| `src/gateway/` | Provider registry, routing, protocol adapters and encrypted-key form |
| `src/ui/` | Provider menu, retaining native callbacks and effort sliders |
| `config/` | Public provider definitions and desktop model/effort metadata |
| `scripts/` | Build, launch, rollback and key setup; Windows implementation in `windows/` |
| `tests/` | Offline picker, routing/credential isolation, cache and rollback checks |
| `docs/SETUP.md` | Setup, limits, validation and migration notes |
| `docs/PROVIDERS.md` | Adding models or providers using the shared registry |
| `.local/` | Ignored deployment, vendor dependencies, encrypted keys, backups and scratch output |

API keys stay DPAPI-encrypted and local. Runtime data, logs, backups, profiles, vendor binaries and generated app JavaScript are ignored by Git. The repository is local; no remote or upload is configured.

Committed configuration contains public model metadata and short starter instruction templates. Embedded native prompt exports and personal instruction customizations are local configuration, not publication assets. The local catalogue retains its native templates; review local configuration changes before adding them to a public commit.

## Local checks

```powershell
python scripts/build-deployment.py
python tests/check-overlay-cache.py
python tests/check-api-settings.py
python tests/check-model-metadata.py
python tests/check-live-settings.py
python tests/check-catalog-refresh.py
python tests/check-catalog-runtime.py
python tests/check-rollback.py
python tests/check-provider-registry.py
python tests/check-model-profiles.py
python tests/check-opencode-relay.py
python tests/check-delegation-tools.py
python tests/check-tool-compatibility.py
python tests/check-retired-tool-history.py
python tests/check-cross-chat-context.py
python tests/check-provider-errors.py
python tests/check-compaction.py
python tests/check-compaction-runtime.py
python tests/check-native-client-tools.py
node tests/check-picker.cjs
node tests/check-settings-layout.cjs
python scripts/build-deployment.py --check
```

The build script reads the signed archive, assembles the selected `.local/` deployment from source and generates guarded hashes. It never writes to WindowsApps or the live configuration, and refuses to rebuild an active local deployment. It requires the ignored local deployment manifest generated for this machine. Edit `src/` and `config/`, then build; files under `.local/` are generated or private, not editable project source. `--check` verifies the selected deployment without rebuilding or restarting it.

`python tests/check-opencode-engine-local.py` additionally exercises the verified OpenCode binary against a localhost mock with a dummy key. It creates its own isolated data directory and confirms only data-only relays are offered; it makes no external inference requests.

See [tool compatibility](docs/TOOL-COMPATIBILITY.md) for MCP discovery, native text-tool translation, subagent recovery and remaining ChatGPT tunnel/hosted-tool limits.
