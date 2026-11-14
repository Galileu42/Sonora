#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 - <<'PY'
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from sys import path

path.insert(0, "Sonora")
from updater import FILES

with ZipFile("Sonora_Windows.zip", "w", ZIP_DEFLATED) as archive:
    for name in sorted(FILES):
        source = Path("Sonora", name)
        archive.write(source, source.as_posix())
PY
cd native
trap 'rm -f setup.res setup_payload.zip' EXIT
cp ../Sonora_Windows.zip setup_payload.zip
zig rc /FO setup.res setup.rc
zig cc -target x86_64-windows-gnu -municode -Wl,--subsystem,windows \
    -O2 -s setup.c setup.res -o ../Sonora_Setup.exe
