param(
    [ValidateSet('Setup', 'Token')][string]$Mode = 'Setup',
    [ValidatePattern('^[a-z][a-z0-9_-]{0,63}$')][string]$Provider
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Management\Microsoft.PowerShell.Management.psd1') -ErrorAction Stop
$keyDirectory = Join-Path $PSScriptRoot 'keys'
$providers = Get-Content -LiteralPath (Join-Path (Split-Path $PSScriptRoot -Parent) 'providers.json') -Raw | ConvertFrom-Json
$entries = @($providers.PSObject.Properties | ForEach-Object { @{Id=$_.Name;Label=$_.Value.label} })

if ($Mode -eq 'Token') {
    try {
        if (-not $Provider -or $Provider -notin @($entries.Id)) { throw 'Configured provider required' }
        $keyPath = Join-Path $keyDirectory ($Provider + '.dpapi')
        if (-not (Test-Path -LiteralPath $keyPath)) { throw 'Key missing' }
        $secureKey = ConvertTo-SecureString ((Get-Content -LiteralPath $keyPath -Raw).Trim())
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        try {
            $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
            if ([string]::IsNullOrWhiteSpace($token) -or $token.Contains("`r") -or $token.Contains("`n")) { throw 'Invalid key' }
            [Console]::Write($token)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
            $token = $null
            $secureKey.Dispose()
        }
        exit 0
    } catch {
        [Console]::Error.WriteLine('Provider credential unavailable. Run Provider-Credentials.ps1 in Setup mode to enter your key locally.')
        exit 1
    }
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = 'Desktop custom provider keys'
$form.Size = New-Object Drawing.Size(540, (185 + 55 * $entries.Count))
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$notice = New-Object Windows.Forms.Label
$notice.Text = 'Saved keys are indicated below. Type a new key only to replace it. Blank fields keep the encrypted key already saved for that provider.'
$notice.Location = New-Object Drawing.Point(20, 15)
$notice.Size = New-Object Drawing.Size(495, 45)
$form.Controls.Add($notice)
$keyBoxes = @{}
$row = 0
foreach ($entry in $entries) {
    $label = New-Object Windows.Forms.Label
    $label.Text = $entry.Label + ' API key'
    $label.Location = New-Object Drawing.Point(20, (70 + 55 * $row))
    $label.Size = New-Object Drawing.Size(150, 22)
    $form.Controls.Add($label)
    $box = New-Object Windows.Forms.TextBox
    $box.Location = New-Object Drawing.Point(175, (67 + 55 * $row))
    $box.Size = New-Object Drawing.Size(325, 25)
    $box.UseSystemPasswordChar = $true
    $box.MaxLength = 4096
    $form.Controls.Add($box)
    $keyBoxes[$entry.Id] = $box
    $savedPath = Join-Path $keyDirectory ($entry.Id + '.dpapi')
    $hasSavedKey = (Test-Path -LiteralPath $savedPath -PathType Leaf) -and (Get-Item -LiteralPath $savedPath).Length -gt 0
    $saved = New-Object Windows.Forms.Label
    $saved.Location = New-Object Drawing.Point(175, (94 + 55 * $row))
    $saved.Size = New-Object Drawing.Size(325, 18)
    if ($hasSavedKey) {
        $saved.Text = 'Saved: ******** (leave blank to keep)'
        $saved.ForeColor = [Drawing.Color]::DarkGreen
    } else {
        $saved.Text = 'No key saved yet'
        $saved.ForeColor = [Drawing.Color]::DimGray
    }
    $form.Controls.Add($saved)
    $row++
}
$status = New-Object Windows.Forms.Label
$status.Location = New-Object Drawing.Point(20, (65 + 55 * $entries.Count))
$status.Size = New-Object Drawing.Size(495, 24)
$form.Controls.Add($status)
$save = New-Object Windows.Forms.Button
$save.Text = 'Save encrypted keys'
$save.Location = New-Object Drawing.Point(210, (100 + 55 * $entries.Count))
$save.Size = New-Object Drawing.Size(160, 30)
$form.Controls.Add($save)
$cancel = New-Object Windows.Forms.Button
$cancel.Text = 'Cancel'
$cancel.Location = New-Object Drawing.Point(385, (100 + 55 * $entries.Count))
$cancel.Size = New-Object Drawing.Size(115, 30)
$cancel.DialogResult = 'Cancel'
$form.Controls.Add($cancel)
$form.CancelButton = $cancel
$save.Add_Click({
    try {
        foreach ($providerId in @($entries.Id)) {
            $plainText = $keyBoxes[$providerId].Text.Trim()
            if ($plainText.Contains("`r") -or $plainText.Contains("`n")) { throw 'Keys must be single-line values.' }
        }
        New-Item -ItemType Directory -Path $keyDirectory -Force | Out-Null
        foreach ($providerId in @($entries.Id)) {
            $plainText = $keyBoxes[$providerId].Text.Trim()
            if ($plainText.Length -gt 0) {
                $secureKey = ConvertTo-SecureString $plainText -AsPlainText -Force
                try {
                    $encrypted = ConvertFrom-SecureString $secureKey
                    $keyPath = Join-Path $keyDirectory ($providerId + '.dpapi')
                    $temporary = $keyPath + '.' + [guid]::NewGuid() + '.tmp'
                    try {
                        [IO.File]::WriteAllText($temporary, $encrypted, [Text.Encoding]::ASCII)
                        Move-Item -LiteralPath $temporary -Destination $keyPath -Force
                    } finally {
                        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
                    }
                } finally { $secureKey.Dispose() }
            }
            $keyBoxes[$providerId].Clear()
        }
        $plainText = $null
        $encrypted = $null
        $form.DialogResult = 'OK'
        $form.Close()
    } catch { $status.Text = 'Could not save keys. Check your user-folder access and try again.' }
})
[void]$form.ShowDialog()
$form.Dispose()
