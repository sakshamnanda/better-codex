param([switch]$WaitForClose)
$ErrorActionPreference = 'Stop'
$setupRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$pythonPath = Join-Path (Split-Path (Get-Command python -ErrorAction Stop).Source -Parent) 'pythonw.exe'
$manifest = Get-Content -LiteralPath (Join-Path $setupRoot 'Deployment.json') -Raw | ConvertFrom-Json
$package = Get-AppxPackage -Name 'OpenAI.Codex' -ErrorAction Stop | Where-Object { (Join-Path $_.InstallLocation 'app') -eq $manifest.source_app }
if (@($package).Count -ne 1) { throw 'Exact registered Codex installation was not found; no changes made' }
if (!$WaitForClose) {
    & (Join-Path $setupRoot 'Check-Closed.ps1') -InstalledApp $manifest.source_app
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
$arguments = '-u "' + (Join-Path $setupRoot 'packaged_launcher.py') + '"'
if ($WaitForClose) { $arguments += ' --wait-for-close' }
Invoke-CommandInDesktopPackage -PackageFamilyName $package.PackageFamilyName -AppId 'App' -Command $pythonPath -Args $arguments -PreventBreakaway
Write-Output 'Starting your installed Codex with reversible provider support. Its signed files are preserved.'
