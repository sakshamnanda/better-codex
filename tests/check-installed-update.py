"""Read-only regression against reviewed public archive assets; no app or requests."""
from pathlib import Path
import copy
import hashlib
import json
import os
import re
import struct
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'src/desktop'))
from build_compatibility import UPDATED_PACKAGE, UPDATED_HASHES, UPDATED_ASSETS, build_updated_overlay, replace_once, require_known_build
deployment = root / os.environ.get('BETTER_CODEX_TEST_DEPLOYMENT', (root / '.local/deployment-path.txt').read_text().strip())
manifest = json.loads((deployment / 'Deployment.json').read_text())
assert Path(manifest['source_app']).parent.name == UPDATED_PACKAGE
assert manifest['installed_file_hashes'] == UPDATED_HASHES
for name, expected in UPDATED_HASHES.items():
    with (Path(manifest['source_app']) / name).open('rb') as handle:
        assert hashlib.file_digest(handle, 'sha256').hexdigest() == expected
with (Path(manifest['source_app']) / 'resources/app.asar').open('rb') as handle:
    _, size = struct.unpack('<II', handle.read(8))
    header = handle.read(size)
    assets = json.loads(header[8:8+struct.unpack('<II', header[:8])[1]])['files']['webview']['files']['assets']['files']
    def read(name):
        entry = assets[name]
        handle.seek(8 + size + int(entry['offset']))
        return handle.read(entry['size'])
    original = {name: read(name) for name in UPDATED_ASSETS}

overlay = json.loads((deployment / 'Provider-Overlay.json').read_text())
primary = (deployment / 'Provider-Overlay.source.js').read_text(encoding='utf-8')
settings = (deployment / 'Better-Codex-Settings.source.js').read_text(encoding='utf-8')
# Every injected import must be an actual export of the exact reviewed bundle.
imports = settings[:settings.index('const __vite__mapDeps')]
for names, module in re.findall(r'import \{([^}]+)\} from "\./([^\"]+)";', imports):
    source = original[module].decode('utf-8')
    exports = source[source.rfind('export{'):]
    for alias in re.findall(r'([\w$]+) as [\w$]+', names):
        assert re.search(r' as ' + re.escape(alias) + r'[,}]', exports), alias
assert primary.count('e=gatewayPickerMenuProps(e);') == 1
assert 'const React = Pf();' in primary and 'Hs.dispatchHostMessage' in primary
assert '{const li=wi;' in settings and 'li=t(ce(),1)' in settings
assert 'R(()=>gatewaySetSelection' in settings
assert 'onSelectComplete:h,onSelectPower:g,onSelectServiceTier:_' in primary
assert 'initialPowerSelectionId:i' in primary and 'onConfirmCurrentSelection:m' in primary

def refused(action):
    try:
        action()
    except RuntimeError:
        return
    raise AssertionError('Unknown or altered integration was accepted')

picker = {'providers': [], 'models': {}, 'disabledModels': []}
changed = copy.deepcopy(manifest)
changed['installed_file_hashes']['resources/app.asar'] = '0' * 64
refused(lambda: require_known_build(changed))
refused(lambda: build_updated_overlay(root, changed, dict(overlay), original.__getitem__, picker))
changed = copy.deepcopy(manifest)
changed['source_app'] = str(Path(manifest['source_app']).parent.parent / 'unknown-package/app')
refused(lambda: require_known_build(changed))
refused(lambda: build_updated_overlay(root, changed, dict(overlay), original.__getitem__, picker))
for name in original:
    modified = {**original, name: original[name] + b'\n'}
    refused(lambda: build_updated_overlay(root, manifest, dict(overlay), modified.__getitem__, picker))
refused(lambda: replace_once('duplicate duplicate', 'duplicate', 'replacement'))
print('PASS: exact updated package/assets and real native exports verified; picker callbacks, dirty navigation and native aliases retained; unknown builds and changed sources refused.')
