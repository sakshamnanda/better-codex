$ErrorActionPreference = 'Stop'
$setupRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$statePath = Join-Path $setupRoot 'support\Gateway-State.json'
if (!(Test-Path -LiteralPath $statePath)) { exit 0 }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$helper = Get-CimInstance Win32_Process -Filter "ProcessId = $($state.helper_pid)"
if ($helper) {
    $scripts = @((Join-Path $setupRoot 'provider_service.py'),(Join-Path $setupRoot 'launcher.py'),(Join-Path $setupRoot 'packaged_launcher.py'))
    if (!($scripts | Where-Object { $helper.CommandLine.Contains('"' + $_ + '"') })) { throw 'Recorded process no longer matches this provider helper; refusing to stop it' }
}
$engine = $null
if ($state.opencode_pid) { $engine = Get-CimInstance Win32_Process -Filter "ProcessId = $($state.opencode_pid)" }
if ($engine) {
    if ($engine.ExecutablePath -ne (Join-Path $setupRoot 'opencode-engine\opencode.exe') -or $engine.ParentProcessId -ne $state.helper_pid) { throw 'Recorded engine no longer matches the owned helper' }
    Stop-Process -Id $engine.ProcessId -ErrorAction SilentlyContinue
}
if ($helper) { Stop-Process -Id $helper.ProcessId -ErrorAction SilentlyContinue }
Remove-Item -LiteralPath $statePath
