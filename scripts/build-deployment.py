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
source = data.decode(); helper = (ROOT / 'src/ui/provider-picker.js').read_text()
picker = {
    'providers': [{'id': 'openai', 'label': 'ChatGPT'}] + [
        {'id': provider_id, 'label': provider['label'], 'defaultModel': provider['default_model']}
        for provider_id, provider in PROVIDERS.items()
    ],
    'models': {model_id: model['provider'] for model_id, model in MODELS.items()},
}
helper = 'const gatewayProviderConfig = ' + json.dumps(picker).replace('<', '\\u003c') + ';\n' + helper
marker = 'function b8e(e){'
assert source.count(marker) == 1
updated = source.replace(marker,helper + '\nfunction b8e(e){e=gatewayPickerMenuProps(e);',1)
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
overlay['overlay_source_sha256'] = hashlib.sha256(updated.encode()).hexdigest()
(DEPLOY / 'Provider-Overlay.json').write_text(json.dumps(overlay,indent=2))
checks = {}
for path in sorted(DEPLOY.iterdir()):
    if path.suffix in {'.py','.ps1','.cmd','.js'} or path.name in {'Deployment.json','Provider-Overlay.json','models.json','providers.json','instructions.json'}:
        checks[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
for directory in ('gateway','opencode-engine'):
    for path in sorted((DEPLOY / directory).iterdir()):
        if path.is_file(): checks[path.relative_to(DEPLOY).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
for name in PROFILES:
    checks['instructions/' + name] = hashlib.sha256((DEPLOY / 'instructions' / name).read_bytes()).hexdigest()
(DEPLOY / 'Helper-Checksums.json').write_text(json.dumps(checks,indent=2))
temporary = selection.with_suffix('.tmp')
temporary.write_text(DEPLOY.relative_to(ROOT).as_posix())
temporary.replace(selection)
print('Local deployment assembled and hashes generated; installed files/profile unchanged.')
