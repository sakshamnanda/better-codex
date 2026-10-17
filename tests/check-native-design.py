"""Compare the overlay's design contract with pinned native UI source, read-only."""
from pathlib import Path
import hashlib
import json
import os
import re
import struct

root=Path(__file__).resolve().parent.parent
deployment=root/os.environ.get('BETTER_CODEX_TEST_DEPLOYMENT',(root/'.local/deployment-path.txt').read_text().strip())
manifest=json.loads((deployment/'Deployment.json').read_text())
with (Path(manifest['source_app'])/'resources/app.asar').open('rb') as handle:
    _,size=struct.unpack('<II',handle.read(8));header=handle.read(size)
    assets=json.loads(header[8:8+struct.unpack('<II',header[:8])[1]])['files']['webview']['files']['assets']['files']
    def read(name):
        item=assets[name];handle.seek(8+size+int(item['offset']))
        return handle.read(item['size'])
    reference=read('settings-6e80d258418b.js')
    assert hashlib.sha256(reference).hexdigest()=='0ef9fdc55d761bb6ef121967d158a949b99a954deed722985c2a08602ba64abb'
    native=reference.decode()
    for token in ('size:`compact`','spacing:`large`','text-sm font-medium text-default select-none','as:`form`','type:`submit`,color:`primary`'):
        assert token in native,'Native dialog contract changed'
    shared=read('app-shared-737655e1fb23.js')
    assert hashlib.sha256(shared).hexdigest()=='a1daa891e89a395b8db399ff6eaa365f12a86880c3d8cf891caf4ccbcb9eebf5'
    assert b'SNi as MT' in shared and b'flex flex-col gap-2' in shared
    styles=read('app-shared-9a94b907ed47.css').decode()
    for token in ('._body_1rxrl_2{padding-inline:calc(var(--spacing',
                  '._largeSection_1rxrl_2{padding-top:calc(var(--spacing',
                  '.bg-primary-soft{background-color:var(--color-background-primary-soft)'):
        assert token in styles,'Native spacing/theme contract changed'

ui=(root/'src/ui/api-settings.js').read_text(encoding='utf-8')
build=(root/'scripts/build-deployment.py').read_text(encoding='utf-8')
for token in ('MT as GatewayFieldStack','xT as GatewaySettingsSection','gatewayInitializeSettingsSection();'):
    assert token in build
for token in ('e(DialogLayout.Provider,{value:true}', 'variant:inDialog?`default`:`settings`',
              'e(GatewayFieldStack', 'e(GatewaySettingsSection.Header', 'className:inDialog?`w-full`:`max-w-64`'):
    assert token in ui
for path in (root/'src/ui').glob('*.js'):
    source=path.read_text(encoding='utf-8')
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla)\(',source),path.name
    assert not re.search(r'(?:bg|text|border|ring)-(?:black|white|gray|slate|red|blue|orange)(?:\b|-)',source),path.name
    assert not re.search(r'\bstyle\s*:|color-scheme|!bg-|!text-|!border-',source),path.name
print('PASS: pinned Add website reference, native form/section/spacing bindings and semantic theme colors across all overlay UI source. No package edits or app restart.')
