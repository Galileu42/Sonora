param([switch]$InstallPython)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'

function Install-ToolsFromZip($url, $names) {
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ("Sonora-" + [Guid]::NewGuid())
    New-Item -ItemType Directory -Path $temporary | Out-Null
    try {
        $archive = Join-Path $temporary 'package.zip'
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
        $expanded = Join-Path $temporary 'expanded'
        Expand-Archive -LiteralPath $archive -DestinationPath $expanded
        foreach ($name in $names) {
            $found = Get-ChildItem -LiteralPath $expanded -Recurse -File -Filter $name | Select-Object -First 1
            if (-not $found) { throw "Arquivo ausente no pacote: $name" }
            Copy-Item -LiteralPath $found.FullName -Destination (Join-Path $PSScriptRoot "tools\$name") -Force
        }
    } finally {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}

# Windows PowerShell 5.1 can turn native stderr into a terminating
# NativeCommandError when redirected with ErrorActionPreference=Stop.
function Invoke-NativeResult($program, [string[]]$arguments) {
    $ErrorActionPreference = 'Continue'
    $lines = @(& $program @arguments 2>&1 | ForEach-Object { $_.ToString() })
    return @{ Code = $LASTEXITCODE; Output = $lines }
}

try {
    Write-Host 'Preparando o Sonora para Windows...'
    $probe = 'import sys, tkinter; sys.exit(sys.version_info < (3, 10) or sys.maxsize < 2**32)'
    $localPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    $venv = Join-Path $PSScriptRoot '.venv'
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    $checked = if (Test-Path -LiteralPath $venvPython -PathType Leaf) { Invoke-NativeResult $venvPython @('-I', '-c', $probe) }
    if (-not $checked -or $checked.Code -ne 0) {
        $created = $false
        $diagnostics = @()
        $candidates = @($localPython, 'py.exe', 'python.exe')
        foreach ($command in $candidates) {
            $available = Get-Command $command -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $available -or $available.Source -like '*\Microsoft\WindowsApps\python.exe') { continue }
            $prefix = @()
            if ($command -eq 'py.exe') { $prefix += '-3' }
            $tested = Invoke-NativeResult $available.Source ($prefix + @('-I', '-c', $probe))
            if ($tested.Code -ne 0) {
                $diagnostics += $tested.Output
                continue
            }
            Write-Host "Usando Python em $($available.Source)"
            $made = Invoke-NativeResult $available.Source ($prefix + @('-I', '-m', 'venv', '--clear', $venv))
            if ($made.Code -eq 0) { $created = $true; break }
            $diagnostics += $made.Output
        }
        if (-not $created -and $InstallPython) {
            if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
                $diagnostics | ForEach-Object { Write-Host $_ }
                throw 'O WinGet nao esta disponivel. Instale o Python 3.13 de 64 bits pelo site python.org.'
            }
            Write-Host 'Instalando Python 3.13 de 64 bits pelo WinGet...'
            $installed = Invoke-NativeResult 'winget.exe' @('install', '--id', 'Python.Python.3.13', '--exact',
                '--source', 'winget', '--scope', 'user', '--architecture', 'x64', '--silent',
                '--accept-package-agreements', '--accept-source-agreements')
            $installed.Output | ForEach-Object { Write-Host $_ }
            if (Test-Path -LiteralPath $localPython -PathType Leaf) {
                $made = Invoke-NativeResult $localPython @('-I', '-m', 'venv', '--clear', $venv)
                $created = $made.Code -eq 0
                $diagnostics += $made.Output
            }
        }
        if (-not $created) {
            $diagnostics | ForEach-Object { Write-Host $_ }
            throw 'Nao foi possivel preparar o Python de 64 bits com Tcl/Tk.'
        }
    }
    $checked = Invoke-NativeResult $venvPython @('-I', '-c', $probe)
    if ($checked.Code -ne 0) {
        $checked.Output | ForEach-Object { Write-Host $_ }
        throw 'O Python preparado pelo Sonora nao conseguiu carregar o Tcl/Tk.'
    }
    Write-Host 'Instalando o yt-dlp...'
    $engine = Invoke-NativeResult $venvPython @('-I', '-m', 'pip', 'install', '--upgrade', 'yt-dlp[default]')
    $engine.Output | ForEach-Object { Write-Host $_ }
    if ($engine.Code -ne 0) { throw 'Falha ao instalar o yt-dlp.' }

    New-Item -ItemType Directory -Path 'tools' -Force | Out-Null
    $ffmpeg = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    $systemPair = $ffmpeg -and (Test-Path -LiteralPath (Join-Path (Split-Path $ffmpeg.Source) 'ffprobe.exe'))
    $localPair = (Test-Path -LiteralPath 'tools\ffmpeg.exe') -and (Test-Path -LiteralPath 'tools\ffprobe.exe')
    if (-not ($localPair -or $systemPair)) {
        Write-Host 'Baixando FFmpeg e FFprobe (cerca de 110 MB)...'
        Install-ToolsFromZip 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' @('ffmpeg.exe', 'ffprobe.exe')
    }

    $deno = Get-Command deno.exe -ErrorAction SilentlyContinue
    $denoOk = $false
    if ($deno) {
        $versionLine = & $deno.Source --version | Select-Object -First 1
        if ($versionLine -match '^deno ([0-9]+\.[0-9]+\.[0-9]+)') {
            $denoOk = [version]$Matches[1] -ge [version]'2.3.0'
        }
    }
    if (-not ((Test-Path -LiteralPath 'tools\deno.exe') -or $denoOk)) {
        Write-Host 'Baixando Deno para consultar os formatos do YouTube...'
        Install-ToolsFromZip 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip' @('deno.exe')
    }
    Set-Content -LiteralPath '.pronto' -Value 'Sonora' -Encoding Ascii
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    throw
}
