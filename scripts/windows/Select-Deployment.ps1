param([ValidateSet('Launch','Rollback','Keys')][string]$Mode = 'Launch')
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$selection = Join-Path $projectRoot '.local\deployment-path.txt'
$target = '.local\deployment'
if (Test-Path -LiteralPath $selection) { $target = (Get-Content -LiteralPath $selection -Raw).Trim() }
$deployment = [IO.Path]::GetFullPath((Join-Path $projectRoot $target))
$localRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot '.local')).TrimEnd('\') + '\'
if (!$deployment.StartsWith($localRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Deployment must remain inside this project local folder' }
switch ($Mode) {
    'Launch' { & (Join-Path $deployment 'Launch-Installed-Codex.ps1') }
    'Rollback' { & python (Join-Path $deployment 'launcher.py') --rollback }
    'Keys' { & (Join-Path $deployment 'gateway\Provider-Credentials.ps1') -Mode Setup }
}
if ($LASTEXITCODE) { exit $LASTEXITCODE }
