#!/usr/bin/env bash
# Stop (pause) a running batch: the run-batch.sh loop AND the headless claude sessions it started.
# Killing only the script leaves its sessions, and on Windows its loop, running. Progress is in the
# store, so running scripts/run-batch.sh again resumes where it stopped.
cd "$(dirname "$0")/.."
if command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe -NoProfile -Command '
    $p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "run-batch\.sh|claude.* -p .*/(find-profs|discover|positions|profile|draft|scale)" -and $_.Name -ne "powershell.exe" -and $_.CommandLine -notmatch "stop-batch" }
    $p | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; "stopped $($_.Name) $($_.ProcessId)" } catch {} }
    "stopped $(@($p).Count) processes"'
else
  pkill -f "run-batch.sh" || true
  pkill -f "claude -p /(find-profs|discover|positions|profile|draft|scale)" || true
fi
rm -f data/batch.lock
