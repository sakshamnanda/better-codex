param([string]$InstalledApp)
$ErrorActionPreference = 'Stop'
$appRoot = [IO.Path]::GetFullPath($InstalledApp).TrimEnd('\') + '\'
$running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($appRoot,[StringComparison]::OrdinalIgnoreCase) -and
    (($_.ExecutablePath -eq (Join-Path $InstalledApp 'ChatGPT.exe')) -or ($_.ExecutablePath -eq (Join-Path $InstalledApp 'Codex.exe')) -or ($_.ExecutablePath -eq (Join-Path $InstalledApp 'resources\codex.exe') -and $_.CommandLine.Contains('app-server')))
})
if ($running.Count) { Write-Output 'Close the installed Codex app and let its background tasks finish first. No changes were made.'; exit 2 }
exit 0
