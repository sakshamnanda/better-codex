param([string]$FixtureDirectory)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$bridge = Join-Path $PSScriptRoot 'Select-Deployment.ps1'
$powerShellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$selection = (Get-Content -LiteralPath (Join-Path $projectRoot '.local\deployment-path.txt') -Raw).Trim()
$deployment = [IO.Path]::GetFullPath((Join-Path $projectRoot $selection))
$localRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot '.local')).TrimEnd('\') + '\'
if (-not $deployment.StartsWith($localRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid managed deployment.' }
$manifest = Get-Content -LiteralPath (Join-Path $deployment 'Deployment.json') -Raw | ConvertFrom-Json
$iconPath = Join-Path $manifest.source_app 'ChatGPT.exe'
if ((Get-FileHash -LiteralPath $iconPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.installed_file_hashes.'ChatGPT.exe') { throw 'Installed build changed; shortcuts were preserved.' }
if ([IntPtr]::Size -ne 8) { throw 'Use 64-bit Windows PowerShell for this installation.' }

# File metadata only. No window/process identity, package registration or pin
# database is changed; the user repins this distinct shortcut in Start.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class BetterCodexShortcutProperties {
    [StructLayout(LayoutKind.Sequential, Pack=4)] public struct Key { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Explicit, Size=24)] public struct Value {
        [FieldOffset(0)] public ushort vt;
        [FieldOffset(8)] public IntPtr text;
    }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface Store {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, out Key key);
        [PreserveSig] int GetValue(ref Key key, out Value value);
        [PreserveSig] int SetValue(ref Key key, ref Value value);
        [PreserveSig] int Commit();
    }
    [DllImport("shell32.dll", CharSet=CharSet.Unicode, PreserveSig=true)]
    static extern int SHGetPropertyStoreFromParsingName(string path, IntPtr bind, uint flags, ref Guid iid, out Store store);
    [DllImport("ole32.dll")] static extern int PropVariantClear(ref Value value);
    public static void SetIdentity(string path) {
        Guid iid = typeof(Store).GUID;
        Store store;
        Marshal.ThrowExceptionForHR(SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, 2, ref iid, out store));
        Value value = new Value { vt=31, text=Marshal.StringToCoTaskMemUni("BetterCodex.CustomProviders") };
        try {
            Key key = new Key { fmtid=new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid=5 };
            Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref value));
            Marshal.ThrowExceptionForHR(store.Commit());
        } finally { PropVariantClear(ref value); Marshal.FinalReleaseComObject(store); }
    }
}
'@
$shortcutShell = New-Object -ComObject WScript.Shell
$shellExplorer = New-Object -ComObject Shell.Application
$arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $bridge + '" -Mode Launch'
$directories = @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))
if ($FixtureDirectory) {
    $fixture = [IO.Path]::GetFullPath($FixtureDirectory)
    if (-not $fixture.StartsWith($localRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Fixture must stay in the project local folder.' }
    New-Item -ItemType Directory -Path $fixture -Force | Out-Null
    $directories = @($fixture)
}
$backup = Join-Path $localRoot ('shortcut-backups\' + [guid]::NewGuid())
foreach ($directory in $directories) {
    $path = Join-Path $directory 'Codex (Custom Providers).lnk'
    $backupPath = $null
    if (Test-Path -LiteralPath $path) {
        $previous = $shortcutShell.CreateShortcut($path)
        $oldLauncher = Join-Path $projectRoot 'scripts\Launch.cmd'
        if ($previous.TargetPath -ne $oldLauncher -and -not ($previous.TargetPath -eq $powerShellPath -and $previous.Arguments -eq $arguments)) { throw 'Unrelated shortcut with this name was preserved.' }
        New-Item -ItemType Directory -Path $backup -Force | Out-Null
        $backupPath = Join-Path $backup ((Split-Path $directory -Leaf) + '.lnk')
        Copy-Item -LiteralPath $path -Destination $backupPath
    }
    try {
        $shortcut = $shortcutShell.CreateShortcut($path)
        $shortcut.TargetPath = $powerShellPath
        $shortcut.Arguments = $arguments
        $shortcut.WorkingDirectory = $projectRoot
        $shortcut.IconLocation = $iconPath + ',0'
        $shortcut.Description = 'Codex with Better Codex provider support'
        $shortcut.WindowStyle = 7
        $shortcut.Save()
        [BetterCodexShortcutProperties]::SetIdentity($path)
        $verified = $shortcutShell.CreateShortcut($path)
        $folder = $shellExplorer.Namespace($directory)
        $item = $folder.ParseName('Codex (Custom Providers).lnk')
        if ($verified.TargetPath -ne $powerShellPath -or $verified.Arguments -ne $arguments -or $verified.WorkingDirectory -ne $projectRoot -or $item.ExtendedProperty('System.AppUserModel.ID') -ne 'BetterCodex.CustomProviders') { throw 'Shortcut verification failed.' }
    } catch {
        if ($backupPath) { Copy-Item -LiteralPath $backupPath -Destination $path -Force }
        throw
    }
}
Write-Output 'Verified custom shortcuts: direct PowerShell launcher and distinct BetterCodex.CustomProviders identity. Existing shortcuts backed up; app/package/settings unchanged.'
