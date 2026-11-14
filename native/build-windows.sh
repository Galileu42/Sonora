#!/bin/sh
set -eu
cd "$(dirname "$0")"
zig rc /FO sonora.res sonora.rc
zig cc -target x86_64-windows-gnu -municode -Wl,--subsystem,windows \
    -O2 -s launcher.c sonora.res -o ../Sonora/Sonora.exe
rm sonora.res
