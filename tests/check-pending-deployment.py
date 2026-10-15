"""Next-launch selection refuses active apps and stale settings; fixtures only."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parent.parent
ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
with tempfile.TemporaryDirectory(dir=root/'.local',prefix='pending-check-') as directory:
    project=Path(directory);script=project/'scripts/windows/Select-Deployment.ps1'
    script.parent.mkdir(parents=True);shutil.copyfile(root/'scripts/windows/Select-Deployment.ps1',script)
    local=project/'.local';old=local/'old';new=local/'new'
    source=project/'config';(source/'instructions').mkdir(parents=True)
    for folder in (old,new):
        (folder/'gateway/keys').mkdir(parents=True);(folder/'instructions').mkdir()
        (folder/'Deployment.json').write_text(json.dumps({'source_app':'owned-build-fixture'}))
        (folder/'Launch-Installed-Codex.ps1').write_text("'launched' | Set-Content (Join-Path $PSScriptRoot 'launched'); exit 0")
        (folder/'Check-Closed.ps1').write_text("param([string]$InstalledApp)\nif(Test-Path (Join-Path $PSScriptRoot 'blocked')) {exit 2}; exit 0")
        (folder/'launcher.py').write_text("from pathlib import Path\nraise SystemExit(7 if (Path(__file__).parent/'refuse').exists() else 0)\n")
        (folder/'gateway/keys/fixture.dpapi').write_bytes(b'owned-dummy-ciphertext-fixture')
    for name,value in [('providers.json',{}),('models.json',{'models':[]}),('instructions.json',{'default':'default.md','models':{}})]:
        raw=json.dumps(value);(source/name).write_text(raw);(new/name).write_text(raw)
    for path in (source/'instructions/default.md',new/'instructions/default.md'):path.write_text('Owned instruction fixture')
    selected=local/'deployment-path.txt';pending=local/'pending-deployment.txt'
    selected.write_text('.local/old');pending.write_text('.local/new')
    def run(*args):
        return subprocess.run([str(ps),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),*args],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    (old/'blocked').touch();assert run().returncode==2
    assert selected.read_text()=='.local/old' and pending.exists() and not (new/'launched').exists()
    (old/'blocked').unlink();(new/'refuse').touch();assert run().returncode==7
    assert selected.read_text()=='.local/old' and pending.exists()
    (new/'refuse').unlink();result=run();assert result.returncode==0,result.stderr
    assert selected.read_text().replace('\\','/')=='.local/new' and not pending.exists()
    assert (local/'previous-code-deployment.txt').read_text()=='.local/old' and (new/'launched').exists()
    # A later key edit must win over the older staged copy.
    selected.write_text('.local/old');pending.write_text('.local/new')
    (old/'gateway/keys/fixture.dpapi').write_bytes(b'newer-owned-dummy-ciphertext')
    result=run();assert result.returncode==0,result.stderr
    assert selected.read_text()=='.local/old' and not pending.exists() and (old/'launched').exists()
    assert (old/'gateway/keys/fixture.dpapi').read_bytes()==b'newer-owned-dummy-ciphertext'
    pending.write_text('.local/new');assert run('-Mode','Rollback').returncode==0
    assert not pending.exists() and selected.read_text()=='.local/old'
    # Code updates compare the latest data snapshot's keys, not stale keys in
    # the reusable code/runtime folder, then retire only the snapshot pointer.
    settings=local/'settings-owned';(settings/'gateway/keys').mkdir(parents=True)
    (settings/'gateway/keys/fixture.dpapi').write_bytes(b'latest-owned-fixture')
    (new/'gateway/keys/fixture.dpapi').write_bytes(b'latest-owned-fixture')
    settings_pointer=local/'settings-path.txt';settings_pointer.write_text('.local/settings-owned')
    pending.write_text('.local/new');result=run();assert result.returncode==0,result.stderr
    assert selected.read_text().replace('\\','/')=='.local/new' and not settings_pointer.exists()
    assert (local/'previous-settings-path.txt').read_text()=='.local/settings-owned'
print('PASS: next-launch update waits for app closure, verifies helper, retains previous selection and refuses stale key/settings copies. No installed app, real credentials or process was used.')
