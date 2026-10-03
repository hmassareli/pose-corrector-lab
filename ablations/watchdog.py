#!/usr/bin/env python3
"""Watchdog: if overnight_hard dies before phase=done, restart it."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ABL = Path(__file__).resolve().parent
EXP = ABL / "competition_20260728"
MARKER = EXP / "overnight_status.json"
LOCK = EXP / "watchdog.lock"


def phase() -> str:
    if not MARKER.is_file():
        return "missing"
    try:
        return str(json.loads(MARKER.read_text(encoding="utf-8")).get("phase") or "")
    except Exception:
        return "bad"


def overnight_alive() -> bool:
    # crude: look for run_overnight_hard in process list via WMIC/powershell is heavy;
    # instead check lock heartbeat mtime updated by child... we just try start if phase not done
    # and no recent train log activity.
    return False


def main() -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    print("[watchdog] start", flush=True)
    while True:
        p = phase()
        if p == "done":
            print("[watchdog] competition done — exiting", flush=True)
            return
        # If no python overnight_hard running, restart
        try:
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run_overnight_hard' } | Select-Object -ExpandProperty ProcessId",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            alive = bool(out.strip())
        except Exception:
            alive = False
        if not alive and p != "done":
            print(f"[watchdog] restart overnight_hard (phase={p})", flush=True)
            subprocess.Popen(
                [sys.executable, "-u", str(ABL / "run_overnight_hard.py")],
                cwd=str(LAB),
                stdout=open(EXP / "logs" / "watchdog_child.log", "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
            )
        time.sleep(300)


if __name__ == "__main__":
    main()
