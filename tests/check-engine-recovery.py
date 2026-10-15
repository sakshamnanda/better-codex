"""Guarded recovery covers retired engines, never reused unrelated PIDs."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile

root=Path(__file__).resolve().parent.parent
ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
with tempfile.TemporaryDirectory(dir=root/'.local',prefix='engine-recovery-check-') as directory:
    folder=Path(directory);(folder/'support').mkdir()
    script=folder/'Stop-Provider-Service.ps1';shutil.copyfile(root/'scripts/windows/Stop-Provider-Service.ps1',script)
    state=folder/'support/Gateway-State.json'
    value={'helper_pid':99,'opencode_pid':11,'opencode_pids':[11,12,13,14]}
    wrapper=folder/'fixture.ps1'
    wrapper.write_text(r'''
$ErrorActionPreference = 'Stop'
$global:ownedStopped = @()
function Get-CimInstance {
    param($ClassName,$Filter)
    $number = [int]($Filter.Split('=')[-1].Trim())
    if ($number -eq 99) { return [pscustomobject]@{ProcessId=99;CommandLine=('"' + (Join-Path $PSScriptRoot 'launcher.py') + '"')} }
    if ($number -eq 14) { return $null }
    $owner = if ($number -eq 13) { 777 } else { 99 }
    if ($number -eq 11 -and (Test-Path (Join-Path $PSScriptRoot 'mismatch'))) { $owner=777 }
    return [pscustomobject]@{ProcessId=$number;ParentProcessId=$owner;ExecutablePath=(Join-Path $PSScriptRoot 'opencode-engine\opencode.exe')}
}
function Stop-Process { param($Id,$ErrorAction) $global:ownedStopped += [int]$Id }
try { & (Join-Path $PSScriptRoot 'Stop-Provider-Service.ps1') }
catch { $script:refused=$true }
@{stopped=$global:ownedStopped;refused=[bool]$script:refused} | ConvertTo-Json -Compress
''')
    def run():
        state.write_text(json.dumps(value))
        result=subprocess.run([str(ps),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(wrapper)],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout)
    result=run();assert result=={'stopped':[11,12,99],'refused':False},result
    (folder/'mismatch').touch();result=run()
    assert result=={'stopped':[],'refused':True} and state.exists(),result
print('PASS: recovery covers current/retired owned engines, skips dead or reused retired PIDs, and refuses an unrelated current PID before stopping anything. Mock processes only.')
