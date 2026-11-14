$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'Instalador do Sonora'
$progressPreference = 'SilentlyContinue'
$target = Join-Path $env:LOCALAPPDATA 'Programs\Sonora'
$data = Join-Path $env:LOCALAPPDATA 'Sonora'
$staging = Join-Path $PSScriptRoot 'stage'
$backup = Join-Path $PSScriptRoot 'backup'
$lock = $null
$transcript = $false
$applied = [Collections.Generic.List[object]]::new()

try {
    Write-Host 'Instalando o Sonora para esta conta do Windows...'
    New-Item -ItemType Directory -Path $data, $target -Force | Out-Null
    $log = Join-Path $data 'instalacao.log'
    Start-Transcript -LiteralPath $log -Force | Out-Null
    $transcript = $true
    $lock = [IO.File]::Open((Join-Path $data 'instance.lock'), 'OpenOrCreate', 'ReadWrite', 'ReadWrite')
    try {
        $lock.Lock(0, 1)
    } catch [IO.IOException] {
        throw 'Feche o Sonora, aguarde alguns segundos e execute o instalador novamente.'
    }
    Expand-Archive -LiteralPath (Join-Path $PSScriptRoot 'Sonora_Windows.zip') -DestinationPath $staging
    $payload = Join-Path $staging 'Sonora'
    $versionPattern = '(?m)^VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"\r?$'
    function Get-AppVersion($directory) {
        $contents = Get-Content -LiteralPath (Join-Path $directory 'updater.py') -Raw
        if ($contents -notmatch $versionPattern) { throw 'Versao do Sonora invalida.' }
        return [version]$Matches[1]
    }
    $version = Get-AppVersion $payload
    $copy = $true
    if (Test-Path -LiteralPath (Join-Path $target 'updater.py')) {
        $copy = (Get-AppVersion $target) -le $version
    }
    if ($copy) {
        foreach ($file in Get-ChildItem -LiteralPath $payload -Recurse -File) {
            $relative = $file.FullName.Substring($payload.Length + 1)
            $destination = Join-Path $target $relative
            $saved = Join-Path $backup $relative
            $existed = Test-Path -LiteralPath $destination -PathType Leaf
            New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
            if ($existed) {
                New-Item -ItemType Directory -Path (Split-Path $saved) -Force | Out-Null
                Copy-Item -LiteralPath $destination -Destination $saved -Force
            }
            $applied.Add(@{File=$destination; Backup=$saved; Existed=$existed})
            Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
        }
    }
    & (Join-Path $target 'Preparar.ps1') -InstallPython
    & (Join-Path $target 'Criar_Atalhos.ps1')
    $applied.Clear()
    Write-Host 'Sonora instalado. Abrindo o aplicativo...'
} catch {
    $message = $_.Exception.Message
    for ($index = $applied.Count - 1; $index -ge 0; $index--) {
        $item = $applied[$index]
        if ($item.Existed) {
            Copy-Item -LiteralPath $item.Backup -Destination $item.File -Force -ErrorAction Continue
        } else {
            Remove-Item -LiteralPath $item.File -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host $message -ForegroundColor Red
    if ($transcript) { Write-Host "Log completo: $log" }
    Read-Host 'Pressione Enter para fechar' | Out-Null
    exit 2
} finally {
    if ($lock) { $lock.Dispose() }
    if ($transcript) { Stop-Transcript | Out-Null }
    Remove-Item -LiteralPath $staging, $backup -Recurse -Force -ErrorAction SilentlyContinue
}
Start-Process -FilePath (Join-Path $target 'Sonora.exe') -WorkingDirectory $target
exit 0
