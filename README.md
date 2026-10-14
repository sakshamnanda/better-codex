# better-codex

Windows Codex desktop custom providers, using the original installed signed app and its normal profile.

## What was changed

- A local inference gateway chooses the provider from each request's model ID. ChatGPT uses its normal signed-in service; Nemotron uses OpenRouter; Space Bunny uses the genuine isolated OpenCode client. Models remain independent between chats.
- Merge Gateway adds `zai/glm-5.3-flash` through its OpenAI-compatible Responses endpoint, with a separate Merge key. Its registration/offline checks are complete; real provider verification needs that key.
- The original model/effort controls gain ChatGPT, OpenRouter and OpenCode Zen categories. A version-checked static UI resource is supplied in memory over private inherited pipes. Package files, signatures, security fuses and permissions remain intact. There is no debugging network port.
- A Windows package-context launcher starts the actual installed executable. Two backed-up user settings point to the local gateway and model catalog while it runs. Closing the app restores ordinary settings; manual rollback is also provided.
- Codex retains tool execution, approvals, project instructions and chat history. The OpenCode helper returns data-only tool requests; it does not execute the caller's shell commands itself. Cross-provider history is normalized, and private native authentication is not sent to external providers.

This is a tested local customization, not an official provider-picker extension. Updates require a compatibility review; source/hash guards refuse unknown builds.

## Use

Use the **Codex (Custom Providers)** desktop shortcut for provider support. The existing ordinary Codex shortcut remains available. Provider/model/effort switching needs no restart after launch.

The custom Desktop and Start menu shortcuts target Windows PowerShell with the project launcher arguments and the distinct `BetterCodex.CustomProviders` shortcut identity. To create or repair them without launching the app, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/Install-Shortcuts.ps1`. Existing shortcuts are backed up under `.local/shortcut-backups/`. If an older pinned Start tile opens ordinary Codex, unpin it and pin **Codex (Custom Providers)** from Start search again. Pin the custom shortcut entry rather than the running app's ordinary taskbar identity. Close the ordinary app before launching the custom setup; the launch guard preserves any open window.

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/Select-Deployment.ps1 -Mode Launch -Preflight` verifies the selected launcher/build and reports whether Codex is still running, without changing configuration or processes.

For rollback, close Codex and run `scripts/Rollback.cmd`. Sign-in and chat databases are retained. Select a ChatGPT model before continuing an external-model chat through the ordinary launcher.

Open **Settings → Better Codex** for **Providers**, **API keys** and **Models**. These sections are also available in the model menu. Edit compatible provider URLs/defaults, replace masked keys or add/edit external model IDs, token limits and effort metadata. Blank key fields keep the saved DPAPI-encrypted keys. ChatGPT sign-in and the verified OpenCode endpoint remain managed by their original clients.

In **API keys**, each provider supports up to 16 named key profiles. The original key appears as **Default**. Use **Add Merge Gateway API key**, name the new profile and enter its key, then choose **Active API key**. Existing profiles remain stored; only the selected profile is used for that provider. Save and relaunch when ready to apply the selection. This is a provider-wide choice for all its models/chats, with no automatic key rotation or fallback.

Better Codex uses the app's actual settings page, grouped rows, text inputs, rounded dropdown buttons and radio/checkbox menus. Theme colors and keyboard behavior come from those native components. The native scroll container holds the editor while the footer keeps Save accessible in short windows. In **Models**, choose a provider first: only its models appear; **Edit** reveals limits and effort options. **Add model** adds to that provider. Model-menu shortcuts navigate to this same Settings page. Unsaved edits use the app's original settings-change guard.

**Save for next launch** validates the configuration and stages a fresh verified deployment. Close and reopen **Codex (Custom Providers)** when ready to apply it. The running service and chats keep their current configuration. Prior deployments and their encrypted keys/rollback state remain available; the next-launch predecessor is recorded in each new deployment's `support/Previous-Settings-Deployment.txt`. Editing metadata does not establish provider access or compatibility; use the provider's published limits and verify a new model before relying on it.

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

## Local checks

```powershell
python scripts/build-deployment.py
python tests/check-overlay-cache.py
python tests/check-api-settings.py
python tests/check-rollback.py
python tests/check-provider-registry.py
python tests/check-model-profiles.py
python tests/check-opencode-relay.py
python tests/check-delegation-tools.py
python tests/check-tool-compatibility.py
python tests/check-retired-tool-history.py
python tests/check-cross-chat-context.py
python tests/check-native-client-tools.py
node tests/check-picker.cjs
node tests/check-settings-layout.cjs
python scripts/build-deployment.py --check
```

The build script reads the signed archive, assembles the selected `.local/` deployment from source and generates guarded hashes. It never writes to WindowsApps or the live configuration, and refuses to rebuild an active local deployment. It requires the ignored local deployment manifest generated for this machine. Edit `src/` and `config/`, then build; files under `.local/` are generated or private, not editable project source. `--check` verifies the selected deployment without rebuilding or restarting it.

`python tests/check-opencode-engine-local.py` additionally exercises the verified OpenCode binary against a localhost mock with a dummy key. It creates its own isolated data directory and confirms only data-only relays are offered; it makes no external inference requests.

See [tool compatibility](docs/TOOL-COMPATIBILITY.md) for MCP discovery, native text-tool translation, subagent recovery and remaining ChatGPT tunnel/hosted-tool limits.
