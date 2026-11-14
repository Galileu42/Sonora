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

try {
    Write-Host 'Preparando o Sonora para Windows...'
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        $probe = 'import sys, tkinter; sys.exit(sys.version_info < (3, 10))'
        $created = $false
        foreach ($command in @('py.exe', 'python.exe')) {
            if (Get-Command $command -ErrorAction SilentlyContinue) {
                $arguments = @()
                if ($command -eq 'py.exe') { $arguments += '-3' }
                & $command @arguments -c $probe 2>$null
                if ($LASTEXITCODE -eq 0) {
                    & $command @arguments -m venv .venv
                    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar o ambiente Python.' }
                    $created = $true
                    break
                }
            }
        }
        if (-not $created) {
            throw 'Instale o Python 3.10 ou superior com Tcl/Tk pelo https://www.python.org/downloads/windows/ e execute este arquivo novamente.'
        }
    }

    Write-Host 'Instalando o yt-dlp...'
    & '.\.venv\Scripts\python.exe' -m pip install --upgrade "yt-dlp[default]"
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar o yt-dlp.' }

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
    exit 1
}
