"""Assemble the guarded local deployment without changing the installed app."""
from pathlib import Path
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--output', help='Prepare an inactive .local folder for the next launch')
parser.add_argument('--check', action='store_true', help='Verify the selected deployment without rebuilding')
parser.add_argument('--no-select', action='store_true', help='Stage files without changing the next-launch selection')
args = parser.parse_args()
selection = ROOT / '.local/deployment-path.txt'
target = args.output or (selection.read_text().strip() if selection.exists() else '.local/deployment')
DEPLOY = (ROOT / target).resolve()
if not DEPLOY.is_relative_to((ROOT / '.local').resolve()) or DEPLOY == (ROOT / '.local').resolve():
    raise RuntimeError('Deployment output must remain inside this project .local folder')
if args.check:
    raise SystemExit(subprocess.run([sys.executable, str(DEPLOY / 'launcher.py'), '--check']).returncode)
sys.path.insert(0, str(ROOT / 'src/gateway'))
from provider_registry import PROVIDERS, MODELS
from model_profiles import load_profiles
PROFILE_SETTINGS, PROFILES = load_profiles(ROOT / 'config')

# Refuse to replace a live helper's code, key paths or rollback state.
def require_inactive():
    if os.name != 'nt': raise RuntimeError('This deployment targets Windows')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    for name in ('Activation-State.json', 'Gateway-State.json'):
        path = DEPLOY / 'support' / name
        if not path.exists(): continue
        pid = json.loads(path.read_text()).get('helper_pid')
        if not pid: continue
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() != 87: raise RuntimeError('Cannot verify local helper is stopped')
            continue
        try:
            status = ctypes.c_uint()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(status)) or status.value == 259:
                raise RuntimeError('Local deployment is active; close its app before rebuilding')
        finally: kernel.CloseHandle(handle)

require_inactive()
manifest = json.loads((DEPLOY / 'Deployment.json').read_text())
for name,expected in manifest['installed_file_hashes'].items():
    with (Path(manifest['source_app']) / name).open('rb') as handle:
        assert hashlib.file_digest(handle,'sha256').hexdigest() == expected, 'Installed build changed; review compatibility first'
overlay = json.loads((DEPLOY / 'Provider-Overlay.json').read_text())
entry_path = 'webview/assets/' + overlay['filename']
with (Path(manifest['source_app']) / 'resources/app.asar').open('rb') as handle:
    size,header_size = struct.unpack('<II',handle.read(8))
    assert size == 4 and 8 <= header_size <= 32 * 1024 * 1024
    header = handle.read(header_size)
    payload_size,string_size = struct.unpack('<II',header[:8])
    assert payload_size <= header_size - 4 and string_size <= header_size - 8
    tree = json.loads(header[8:8+string_size])['files']
    for part in entry_path.split('/'):
        item = tree[part]
        if 'files' in item: tree = item['files']
    assert not item.get('unpacked') and int(item['offset']) >= 0 and item['size'] >= 0
    handle.seek(8 + header_size + int(item['offset']))
    data = handle.read(item['size']); assert len(data) == item['size']
assert hashlib.sha256(data).hexdigest() == overlay['original_source_sha256']
source = data.decode('utf-8'); helper = (ROOT / 'src/ui/settings-bridge.js').read_text(encoding='utf-8') + '\n' + (ROOT / 'src/ui/provider-picker.js').read_text(encoding='utf-8')
picker = {
    'providers': [{'id': 'openai', 'label': 'ChatGPT'}] + [
        {'id': provider_id, 'label': provider['label'], 'defaultModel': provider['default_model'],'enabled':provider.get('enabled',True)}
        for provider_id, provider in PROVIDERS.items()
    ],
    'models': {model_id: provider_id for provider_id,p in PROVIDERS.items() for model_id in p['models']},
    'disabledModels': [mid for p in PROVIDERS.values() for mid,route in p['models'].items() if not route.get('enabled',True)],
}
helper = 'const gatewayProviderConfig = ' + json.dumps(picker).replace('<', '\\u003c') + ';\n' + helper
marker = 'function b8e(e){'
assert source.count(marker) == 1
updated = source.replace(marker,helper + '\nfunction b8e(e){e=gatewayPickerMenuProps(e);',1)
# Add a native settings group only in this exact known source.
settings_name = 'settings-page-6c4c55bd9144.js'
with (Path(manifest['source_app']) / 'resources/app.asar').open('rb') as handle:
    item = tree[settings_name]
    handle.seek(8 + header_size + int(item['offset']))
    settings_bytes = handle.read(item['size'])
settings_hash = '85008a9eb0c855ef91e788c41ccd844fc344e4852d318ed7bce9a2dfd5ef587c'
assert hashlib.sha256(settings_bytes).hexdigest() == settings_hash, 'Settings source changed; customization refused'
settings_source = settings_bytes.decode('utf-8')
# Verify every native control module before binding its exports. The installed
# archive guard also covers their original theme styles and dependency graph.
native_hashes = {
    'app-initial-b8e1c8014bb4.js':'799331dde54905c4df5e360f23a9621141759e2c0acb230aeab909f9904b646f',
    'app-shared-737655e1fb23.js':'a1daa891e89a395b8db399ff6eaa365f12a86880c3d8cf891caf4ccbcb9eebf5',
    'general-settings-161845fad443.js':'03b2b04b597e74d0d7e6ba820f558eec8ffafca553d2876aa0fbac82b2e4de06',
}
with (Path(manifest['source_app']) / 'resources/app.asar').open('rb') as handle:
    for filename,expected in native_hashes.items():
        item=tree[filename];handle.seek(8+header_size+int(item['offset']))
        assert hashlib.sha256(handle.read(item['size'])).hexdigest()==expected, 'Native settings controls changed; customization refused'
native_imports = '''import {_S as GatewayRow,lS as GatewayGroup,$T as GatewaySwitch,GT as GatewayDropdown,qT as GatewayMenu,Ck as GatewayButton,IT as GatewayDialog,OT as GatewayDialogContent,K9 as GatewayChevron,MT as GatewayFieldStack,jT as GatewayDialogHeader,kT as GatewayDialogFooter,AT as GatewayDialogHeading,zT as GatewayDialogTitle,RT as GatewayDialogSubtitle} from "./app-shared-737655e1fb23.js";
import {xT as GatewaySettingsSection,ST as gatewayInitializeSettingsSection,MA as GatewayDropdownButton,lEn as GatewayInput,Met as GatewaySearch,Net as gatewayInitializeSearch,YA as GatewaySettingsPage,irt as GatewayDirtySettings,ert as gatewayInitializeDirtySettings} from "./app-initial-b8e1c8014bb4.js";
import {s as gatewayInitializeSettingsControls} from "./general-settings-161845fad443.js";
'''
settings_source = native_imports + settings_source
group_marker = ':n.map(e=>(0,Q.jsxs)(tt,{title:'
item_marker = 'e.sections.map(e=>{if(e.slug===`teams`'
assert settings_source.count(group_marker) == settings_source.count(item_marker) == 1
sections = [{'slug':'better-codex-' + slug, 'label':label} for slug,label in [('providers','Providers'),('models','Models')]]
group = {'key':'better-codex','heading':{'id':'betterCodex.settings','defaultMessage':'Better Codex'},'sections':sections}
settings_source = settings_source.replace(group_marker,':([...n,' + json.dumps(group) + ']).map(e=>(0,Q.jsxs)(tt,{title:',1)
settings_source = settings_source.replace(item_marker,'e.sections.map(e=>{if(e.slug.startsWith(`better-codex-`))return(0,Q.jsx)(vt,{label:e.label,"aria-label":e.label,"data-settings-panel-slug":e.slug,isActive:a===e.slug,hideLabel:S?j:void 0,weightClassName:`font-normal`,onClick:()=>o(e.slug)},e.slug);if(e.slug===`teams`',1)
# Render our editor inside the original settings layout, retaining its navigation
# callbacks and unsaved-change guard. No modal or DOM replacement is used here.
replacements = {
    'function ri(){let e=(0,ci.c)(138)': 'function ri(){let[gatewaySelection,gatewaySetSelection]=(0,li.useState)(null);let e=(0,ci.c)(138)',
    'let F=_e,ve;': 'let F=_e;(0,li.useEffect)(()=>{let navigate=(section,provider)=>F(()=>gatewaySetSelection({slug:`better-codex-`+section,provider}));globalThis.gatewaySettingsNavigate=navigate;let pending=globalThis.gatewaySettingsPending;if(pending){delete globalThis.gatewaySettingsPending;navigate(pending.section,pending.provider)}return()=>{if(globalThis.gatewaySettingsNavigate===navigate)delete globalThis.gatewaySettingsNavigate}},[F]);let ve;',
    'let y=v,b=ne(f)': '(0,li.useEffect)(()=>gatewaySetSelection(null),[u.pathname,u.search]);let y=v,b=ne(f)',
    'let Ke=h==null?We:`plugins-settings`': 'let Ke=gatewaySelection?.slug??(h==null?We:`plugins-settings`)',
    'onSelect:qe,onSelectPlugin:U,onSelectTeam:Le': 'onSelect:(slug,...args)=>{if(slug.startsWith(`better-codex-`)){F(()=>gatewaySetSelection({slug,provider:null}))}else{gatewaySetSelection(null);qe(slug,...args)}},onSelectPlugin:(...args)=>{gatewaySetSelection(null);U(...args)},onSelectTeam:(...args)=>{gatewaySetSelection(null);Le(...args)}',
    'let W=`${u.key}:${de?.navigationKey??0}`': 'if(gatewaySelection)Pe=(0,$.jsx)(globalThis.gatewaySettingsComponent,{section:gatewaySelection.slug.slice(13),provider:gatewaySelection.provider},gatewaySelection.slug);let W=`${u.key}:${de?.navigationKey??0}`',
}
for before, after in replacements.items():
    assert settings_source.count(before) == 1, 'Known settings layout changed; customization refused'
    settings_source = settings_source.replace(before,after,1)
initializer='ui();export{ri as SettingsPage};'
assert settings_source.count(initializer)==1
settings_source=settings_source.replace(initializer,'ui();gatewayInitializeSettingsControls();gatewayInitializeDirtySettings();gatewayInitializeSearch();gatewayInitializeSettingsSection();\n'+(ROOT/'src/ui/api-settings.js').read_text(encoding='utf-8')+'\nexport{ri as SettingsPage};',1)
# Only known source types are copied; keys, state and vendor files stay local.
for source_dir, target_dir, suffixes in (
    (ROOT / 'src/desktop', DEPLOY, {'.py'}),
    (ROOT / 'src/gateway', DEPLOY / 'gateway', {'.py', '.ps1', '.ts'}),
    (ROOT / 'scripts/windows', DEPLOY, {'.ps1'}),
):
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in source_dir.iterdir():
        if path.is_file() and path.suffix in suffixes: shutil.copyfile(path, target_dir / path.name)
for name in ('models.json', 'providers.json', 'instructions.json'): shutil.copyfile(ROOT / 'config' / name, DEPLOY / name)
for name in PROFILES:
    target = DEPLOY / 'instructions' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'config/instructions' / name, target)
(DEPLOY / 'support').mkdir(exist_ok=True)
(DEPLOY / 'Launch Installed Codex.cmd').write_text('@echo off\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch-Installed-Codex.ps1"\nif errorlevel 1 pause\n')
(DEPLOY / 'Rollback.cmd').write_text('@echo off\npython "%~dp0launcher.py" --rollback\npause\n')
(DEPLOY / 'Provider-Overlay.source.js').write_text(updated,encoding='utf-8')
(DEPLOY / 'Better-Codex-Settings.source.js').write_text(settings_source,encoding='utf-8')
overlay['overlay_source_sha256'] = hashlib.sha256(updated.encode()).hexdigest()
overlay['additional_assets'] = [{'filename':settings_name,'original_source_sha256':settings_hash,
    'source_file':'Better-Codex-Settings.source.js','overlay_source_sha256':hashlib.sha256(settings_source.encode()).hexdigest()}]
(DEPLOY / 'Provider-Overlay.json').write_text(json.dumps(overlay,indent=2))
checks = {}
vendor=DEPLOY/'support/opencode-runtime/config/opencode/node_modules'
if not vendor.is_dir():raise RuntimeError('Verified engine dependencies must be staged for a runtime build')
vendor_checks={p.relative_to(vendor).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(vendor.rglob('*')) if p.is_file()}
(DEPLOY/'Vendor-Checksums.json').write_text(json.dumps(vendor_checks),encoding='utf8')
for path in sorted(DEPLOY.iterdir()):
    if path.suffix in {'.py','.ps1','.cmd','.js'} or path.name in {'Deployment.json','Provider-Overlay.json','models.json','providers.json','instructions.json','Vendor-Checksums.json'}:
        checks[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
for directory in ('gateway','opencode-engine'):
    for path in sorted((DEPLOY / directory).iterdir()):
        if path.is_file(): checks[path.relative_to(DEPLOY).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
for name in PROFILES:
    checks['instructions/' + name] = hashlib.sha256((DEPLOY / 'instructions' / name).read_bytes()).hexdigest()
(DEPLOY / 'Helper-Checksums.json').write_text(json.dumps(checks,indent=2))
if not args.no_select:
    temporary = selection.with_suffix('.tmp')
    temporary.write_text(DEPLOY.relative_to(ROOT).as_posix())
    temporary.replace(selection)
print('Local deployment assembled and hashes generated; installed files/profile unchanged.')
