param([ValidateSet('Launch','Rollback','Keys')][string]$Mode = 'Launch', [switch]$Preflight)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$selection = Join-Path $projectRoot '.local\deployment-path.txt'
$target = '.local\deployment'
if (Test-Path -LiteralPath $selection) { $target = (Get-Content -LiteralPath $selection -Raw).Trim() }
$deployment = [IO.Path]::GetFullPath((Join-Path $projectRoot $target))
$localRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot '.local')).TrimEnd('\') + '\'
if (!$deployment.StartsWith($localRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Deployment must remain inside this project local folder' }
# A code update is selected only on a normal launch after the old app closes.
# Keep the live settings selection untouched while its helper is still serving.
$pendingPath = Join-Path $projectRoot '.local\pending-deployment.txt'
$settingsPath = Join-Path $projectRoot '.local\settings-path.txt'
$settings = $deployment
if (Test-Path -LiteralPath $settingsPath) {
    $settings = [IO.Path]::GetFullPath((Join-Path $projectRoot (Get-Content -LiteralPath $settingsPath -Raw).Trim()))
    if ((Split-Path $settings -Parent).TrimEnd('\') -ne $localRoot.TrimEnd('\')) { throw 'Settings must remain beside the verified runtime' }
}
if ($Mode -eq 'Rollback' -and (Test-Path -LiteralPath $pendingPath)) { Remove-Item -LiteralPath $pendingPath }
if ($Mode -eq 'Launch' -and !$Preflight -and (Test-Path -LiteralPath $pendingPath)) {
    $pending = [IO.Path]::GetFullPath((Join-Path $projectRoot (Get-Content -LiteralPath $pendingPath -Raw).Trim()))
    if ((Split-Path $pending -Parent).TrimEnd('\') -ne $localRoot.TrimEnd('\')) { throw 'Pending update must be a sibling managed deployment' }
    $manifest = Get-Content -LiteralPath (Join-Path $deployment 'Deployment.json') -Raw | ConvertFrom-Json
    & (Join-Path $deployment 'Check-Closed.ps1') -InstalledApp $manifest.source_app
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    & python (Join-Path $pending 'launcher.py') --check
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    $unchanged = $true
    foreach ($name in @('providers.json','models.json','instructions.json')) {
        if ((Get-FileHash -LiteralPath (Join-Path $projectRoot "config\$name")).Hash -ne (Get-FileHash -LiteralPath (Join-Path $pending $name)).Hash) { $unchanged = $false }
    }
    $oldKeys = @(Get-ChildItem -LiteralPath (Join-Path $settings 'gateway\keys') -File)
    if ($oldKeys.Count -ne @(Get-ChildItem -LiteralPath (Join-Path $pending 'gateway\keys') -File).Count) { $unchanged = $false }
    foreach ($key in $oldKeys) {
        $copy = Join-Path $pending "gateway\keys\$($key.Name)"
        if (!(Test-Path -LiteralPath $copy) -or (Get-FileHash -LiteralPath $key.FullName).Hash -ne (Get-FileHash -LiteralPath $copy).Hash) { $unchanged = $false }
    }
    $instructions = Get-Content -LiteralPath (Join-Path $projectRoot 'config\instructions.json') -Raw | ConvertFrom-Json
    $profiles = @($instructions.default) + @($instructions.models.PSObject.Properties | ForEach-Object { $_.Value })
    foreach ($profile in $profiles) {
        if ((Get-FileHash -LiteralPath (Join-Path $projectRoot "config\instructions\$profile")).Hash -ne (Get-FileHash -LiteralPath (Join-Path $pending "instructions\$profile")).Hash) { $unchanged = $false }
    }
    if ($unchanged) {
        Copy-Item -LiteralPath $selection -Destination (Join-Path $projectRoot '.local\previous-code-deployment.txt') -Force
        $temporary = $selection + '.pending.tmp'
        [IO.File]::WriteAllText($temporary,(Join-Path '.local' (Split-Path $pending -Leaf)),(New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $temporary -Destination $selection -Force
        $deployment = $pending
        if (Test-Path -LiteralPath $settingsPath) {
            Copy-Item -LiteralPath $settingsPath -Destination (Join-Path $projectRoot '.local\previous-settings-path.txt') -Force
            Remove-Item -LiteralPath $settingsPath
        }
    } else { Write-Output 'Saved settings changed since the queued update; retaining the current selection.' }
    Remove-Item -LiteralPath $pendingPath
}
switch ($Mode) {
    'Launch' {
        if ($Preflight) { & python (Join-Path $deployment 'launcher.py') --preflight }
        else { & (Join-Path $deployment 'Launch-Installed-Codex.ps1') }
    }
    'Rollback' { & python (Join-Path $deployment 'launcher.py') --rollback }
    'Keys' { & (Join-Path $settings 'gateway\Provider-Credentials.ps1') -Mode Setup }
}
if ($LASTEXITCODE) { exit $LASTEXITCODE }
