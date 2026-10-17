# Native UI design audit

The Better Codex in-app settings and model controls were compared with the
installed Windows app's own bundled UI source on 2026-10-16. The reference is
the **Add website** dialog, plus the app's settings sections and shared controls.
This is a source-based design contract, not a claim of visual testing in every
possible theme.

## Findings and changes

| Evidence | Finding | Implementation |
| --- | --- | --- |
| Add website uses a compact dialog with stacked labels and inputs | Reusing settings rows inside a wide popup produced a different layout | Compact native dialog; native FieldStack and full-width default input variant |
| Native dialog sections use large spacing between form fields | A plain scroll wrapper omitted native spacing between the heading and first field | Native section wraps the scroll region and footer; long forms retain scrolling |
| Native selectors and footers use shared controls | Fixed-width selector triggers and toolbar-sized popup buttons differed from the reference | Full-width native dropdown buttons; medium popup actions; primary Add, secondary Cancel and destructive Delete |
| Native settings pages use a shared section header/content layout | Custom headings and a text disclosure arrow duplicated the design | Native settings section component, ghost button and chevron |
| Native control styles reference semantic color/spacing variables | Hard-coded colors would conflict with custom themes | No literal colors, inline color styles or native-style overrides in overlay UI source |

The existing native model picker and effort slider callbacks are preserved.
API keys remain expandable directly on provider cards. Autosave, sensitive-field
blur handling, new-model cancellation, confirmation prompts and per-chat state
are retained. Creation forms support normal form submission and disabled Add
buttons until required values are supplied.

**Add API key** opens a separate compact native form for the profile name and
masked key. It does not create a profile or change the active key until Add is
chosen. Cancel/X clears the temporary key; successful creation uses the normal
encrypted autosave path. Existing profiles stay in the provider's inline section.

## Reference and verification

The reference module is `settings-6e80d258418b.js`, SHA-256
`0ef9fdc55d761bb6ef121967d158a949b99a954deed722985c2a08602ba64abb`.
Shared primitives come from `app-shared-737655e1fb23.js`, SHA-256
`a1daa891e89a395b8db399ff6eaa365f12a86880c3d8cf891caf4ccbcb9eebf5`.
The builder also verifies the original settings, initial-app and general-settings
modules before importing controls. Unknown builds remain refused.

Run against a verified staged deployment:

```powershell
$env:BETTER_CODEX_TEST_DEPLOYMENT = (Get-Content .local/crud-test-deployment.txt -Raw).Trim()
python tests/check-native-design.py
node tests/check-settings-layout.cjs
node tests/check-picker.cjs
```

These checks compare native source/spacing/theme contracts, render the component
structure with a small offline harness, verify label associations and preserve
save/cancel behavior. They do not automate the live desktop or change its theme.
The signed package, authentication profile and chat databases are untouched.
The standalone legacy Windows key form follows Windows controls; this audit
covers the in-app UI.
