$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$launcher = Join-Path $PSScriptRoot 'Sonora.exe'
if (-not (Test-Path -LiteralPath $launcher)) { throw 'Extraia o ZIP completo do Sonora.' }
$icon = Join-Path $PSScriptRoot 'assets\sonora.ico'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

public static class SonoraShortcut {
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    private struct PropertyKey {
        public Guid Format;
        public uint Id;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Variant {
        public ushort Type, Reserved1, Reserved2, Reserved3;
        public IntPtr Pointer, Extra;
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),
        InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface PropertyStore {
        void GetCount(out uint count);
        void GetAt(uint index, out PropertyKey key);
        void GetValue(ref PropertyKey key, out Variant value);
        void SetValue(ref PropertyKey key, ref Variant value);
        void Commit();
    }

    public static void SetAppId(string path, string appId) {
        Type shellLink = Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046"));
        object shortcut = Activator.CreateInstance(shellLink);
        var value = new Variant { Type = 31, Pointer = Marshal.StringToCoTaskMemUni(appId) };
        try {
            var file = (IPersistFile)shortcut;
            file.Load(path, 2);
            var store = (PropertyStore)shortcut;
            var key = new PropertyKey { Format = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), Id = 5 };
            store.SetValue(ref key, ref value);
            store.Commit();
            file.Save(path, true);
        } finally {
            Marshal.FreeCoTaskMem(value.Pointer);
            Marshal.FinalReleaseComObject(shortcut);
        }
    }
}
'@

$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @('DesktopDirectory', 'Programs')) {
    $directory = [Environment]::GetFolderPath($folder)
    if (-not $directory) { throw "Pasta de atalhos indisponivel: $folder" }
    $path = Join-Path $directory 'Sonora.lnk'
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $launcher
    $shortcut.Arguments = ''
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.Description = 'Sonora - Audio e video do YouTube'
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Save()
    [SonoraShortcut]::SetAppId($path, 'Sonora.Windows.Desktop')
}
Set-Content -LiteralPath '.atalhos-v3' -Value 'Sonora' -Encoding Ascii
