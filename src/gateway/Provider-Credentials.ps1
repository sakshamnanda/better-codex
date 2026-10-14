param(
    [ValidateSet('Setup', 'Token', 'SaveJson', 'SaveProfiles')][string]$Mode = 'Setup',
    [ValidatePattern('^[a-z][a-z0-9_-]{0,63}$')][string]$Provider
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Management\Microsoft.PowerShell.Management.psd1') -ErrorAction Stop
$keyDirectory = Join-Path $PSScriptRoot 'keys'
$providers = Get-Content -LiteralPath (Join-Path (Split-Path $PSScriptRoot -Parent) 'providers.json') -Raw | ConvertFrom-Json
$entries = @($providers.PSObject.Properties | ForEach-Object { @{Id=$_.Name;Label=$_.Value.label} })

function Get-ProfileKeyPath([string]$providerId, [string]$profileId) {
    if ($providerId -notin @($entries.Id) -or $profileId -cnotmatch '^[a-z][a-z0-9_-]{0,63}$') { throw 'Invalid key profile' }
    $filename = $providerId + '.dpapi'
    if ($profileId -ne 'default') { $filename = $providerId + '--' + $profileId + '.dpapi' }
    return Join-Path $keyDirectory $filename
}
function Get-ActiveKeyPath([string]$providerId) {
    $profileId = 'default'
    $indexPath = Join-Path $keyDirectory 'Profiles.json'
    if (Test-Path -LiteralPath $indexPath) {
        $index = Get-Content -LiteralPath $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($index.version -ne 1) { throw 'Invalid profile index' }
        $entry = $index.providers.PSObject.Properties[$providerId].Value
        if ($null -ne $entry) {
            if ($null -eq $entry.profiles.PSObject.Properties[$entry.active]) { throw 'Active profile missing' }
            $profileId = $entry.active
        }
    }
    return Get-ProfileKeyPath $providerId $profileId
}

if ($Mode -eq 'SaveProfiles') {
    try {
        $inputText = [Console]::In.ReadToEnd()
        if ($inputText.Length -gt 65536) { throw 'Input too large' }
        $values = $inputText | ConvertFrom-Json
        $inputText = $null
        $index = @{version=1;providers=@{}}
        $indexPath = Join-Path $keyDirectory 'Profiles.json'
        if (Test-Path -LiteralPath $indexPath) {
            $previous = Get-Content -LiteralPath $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($previous.version -ne 1) { throw 'Invalid profile index' }
            foreach ($item in $previous.providers.PSObject.Properties) { $index.providers[$item.Name] = $item.Value }
        }
        foreach ($item in $values.PSObject.Properties) {
            if ($item.Name -notin @($entries.Id)) { throw 'Invalid provider' }
            $entry = $item.Value
            $profiles = @($entry.profiles)
            if ($profiles.Count -lt 1 -or $profiles.Count -gt 16) { throw 'Invalid profile count' }
            $labels = @{}; $names = @{}
            foreach ($profile in $profiles) {
                [void](Get-ProfileKeyPath $item.Name $profile.id)
                if ($names.ContainsKey($profile.id) -or $profile.label -isnot [string] -or $profile.label.Trim().Length -lt 1 -or $profile.label.Length -gt 80 -or $labels.ContainsKey($profile.label.Trim())) { throw 'Invalid profile name' }
                if ($profile.label.Contains("`r") -or $profile.label.Contains("`n") -or $profile.label.Contains([char]0)) { throw 'Invalid profile name' }
                if ($profile.key -isnot [string] -or $profile.key.Length -gt 4096 -or $profile.key.Contains("`r") -or $profile.key.Contains("`n") -or $profile.key.Contains([char]0)) { throw 'Invalid key' }
                $names[$profile.id] = $profile.label.Trim(); $labels[$profile.label.Trim()] = $true
                $path = Get-ProfileKeyPath $item.Name $profile.id
                if ($profile.key.Trim().Length -eq 0 -and -not (Test-Path -LiteralPath $path) -and $profile.id -ne 'default') { throw 'New profile key required' }
            }
            if (-not $names.ContainsKey($entry.active)) { throw 'Active profile missing' }
            $oldEntry = $index.providers[$item.Name]
            if ($null -ne $oldEntry) {
                foreach ($oldProfile in $oldEntry.profiles.PSObject.Properties) {
                    if (-not $names.ContainsKey($oldProfile.Name)) { throw 'Keep existing profiles' }
                }
            } elseif ((Test-Path -LiteralPath (Get-ProfileKeyPath $item.Name 'default')) -and -not $names.ContainsKey('default')) { throw 'Keep the saved default key' }
            $index.providers[$item.Name] = @{active=$entry.active;profiles=$names}
        }
        New-Item -ItemType Directory -Path $keyDirectory -Force | Out-Null
        foreach ($item in $values.PSObject.Properties) {
            foreach ($profile in @($item.Value.profiles)) {
                $plainText = $profile.key.Trim()
                if ($plainText.Length -eq 0) { continue }
                $secureKey = ConvertTo-SecureString $plainText -AsPlainText -Force
                try {
                    $encrypted = ConvertFrom-SecureString $secureKey
                    $keyPath = Get-ProfileKeyPath $item.Name $profile.id
                    $temporary = $keyPath + '.' + [guid]::NewGuid() + '.tmp'
                    try {
                        [IO.File]::WriteAllText($temporary,$encrypted,[Text.Encoding]::ASCII)
                        Move-Item -LiteralPath $temporary -Destination $keyPath -Force
                    } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
                } finally { $secureKey.Dispose() }
            }
        }
        $temporary = $indexPath + '.' + [guid]::NewGuid() + '.tmp'
        try {
            [IO.File]::WriteAllText($temporary,($index | ConvertTo-Json -Depth 8),(New-Object Text.UTF8Encoding($false)))
            Move-Item -LiteralPath $temporary -Destination $indexPath -Force
        } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
        $plainText = $null; $encrypted = $null; $values = $null
        exit 0
    } catch { [Console]::Error.WriteLine('Could not save encrypted key profiles. Previous selection was retained.'); exit 1 }
}

if ($Mode -eq 'SaveJson') {
    try {
        $inputText = [Console]::In.ReadToEnd()
        if ($inputText.Length -gt 65536) { throw 'Input too large' }
        $values = $inputText | ConvertFrom-Json
        $inputText = $null
        foreach ($item in $values.PSObject.Properties) {
            if ($item.Name -notin @($entries.Id) -or $item.Value -isnot [string] -or $item.Value.Length -gt 4096 -or $item.Value.Contains("`r") -or $item.Value.Contains("`n") -or $item.Value.Contains([char]0)) { throw 'Invalid key input' }
        }
        New-Item -ItemType Directory -Path $keyDirectory -Force | Out-Null
        foreach ($item in $values.PSObject.Properties) {
            $plainText = $item.Value.Trim()
            if ($plainText.Length -eq 0) { continue }
            $secureKey = ConvertTo-SecureString $plainText -AsPlainText -Force
            try {
                $encrypted = ConvertFrom-SecureString $secureKey
                $keyPath = Get-ActiveKeyPath $item.Name
                $temporary = $keyPath + '.' + [guid]::NewGuid() + '.tmp'
                try {
                    [IO.File]::WriteAllText($temporary,$encrypted,[Text.Encoding]::ASCII)
                    Move-Item -LiteralPath $temporary -Destination $keyPath -Force
                } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
            } finally { $secureKey.Dispose() }
        }
        $plainText = $null; $encrypted = $null; $values = $null
        exit 0
    } catch { [Console]::Error.WriteLine('Could not encrypt provider keys.'); exit 1 }
}

if ($Mode -eq 'Token') {
    try {
        if (-not $Provider -or $Provider -notin @($entries.Id)) { throw 'Configured provider required' }
        $keyPath = Get-ActiveKeyPath $Provider
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
    $savedPath = Get-ActiveKeyPath $entry.Id
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
                    $keyPath = Get-ActiveKeyPath $providerId
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
