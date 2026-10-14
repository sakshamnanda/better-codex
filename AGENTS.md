# Project instructions

- Keep the installed Windows package and sign-in/profile safe. Do not modify protected package files, ACLs, certificates or Electron security fuses.
- Use version/source hashes to refuse unknown builds. Do not disable checks to make a patch apply.
- Never print or commit provider keys, native tokens, profile snapshots, private configuration, live URLs/capabilities or chat databases. Local state/vendor/generated artifacts must remain ignored.
- Native authentication may go only to its fixed trusted ChatGPT origin. External requests use provider-only credentials and portable context.
- Preserve the original model selection callbacks, per-chat model state, effort controls, Codex permissions and project instructions.
- Do not move/delete an active deployment. Stage a verified replacement and switch the next launch; preserve its rollback state until it closes.
- Prefer standard-library code and small meaningful offline checks. Avoid live inference or app restarts unless required by the current request.
- Do not publish, push or add a Git remote without a user request.
