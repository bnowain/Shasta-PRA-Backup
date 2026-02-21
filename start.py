"""Launch the Shasta PRA Backup web application."""

import os
import signal
import subprocess
import sys
import time

import uvicorn
from app.config import PORT


def kill_port(port: int):
    """Kill all processes listening on the given port (Windows).

    Uses netstat to find PIDs bound to the port, then os.kill() and
    taskkill as fallback.  Also detects orphan uvicorn workers whose
    parent socket PIDs no longer match a live process (common after
    unclean shutdowns on Windows).
    """
    my_pid = os.getpid()

    def _get_pids_from_netstat():
        """Return set of PIDs that netstat reports as LISTENING on the port."""
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return set()
        pids = set()
        for line in result.stdout.splitlines():
            if f"127.0.0.1:{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                if pid.isdigit() and int(pid) != my_pid:
                    pids.add(int(pid))
        return pids

    def _get_live_python_pids():
        """Return set of all live python PIDs via tasklist."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python*", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return set()
        pids = set()
        for line in result.stdout.strip().splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2 and parts[1].isdigit():
                pid = int(parts[1])
                if pid != my_pid:
                    pids.add(pid)
        return pids

    netstat_pids = _get_pids_from_netstat()
    if not netstat_pids:
        return

    # Netstat can show ghost PIDs (process exited but socket lingers).
    # Cross-reference with live python processes to find the real ones.
    live_pids = _get_live_python_pids()
    real_pids = netstat_pids & live_pids
    ghost_pids = netstat_pids - live_pids

    if ghost_pids:
        print(f"  Ghost sockets on port {port} (will clear on their own): "
              f"{', '.join(str(p) for p in sorted(ghost_pids))}")

    if not real_pids:
        return

    print(f"  Killing {len(real_pids)} process(es) on port {port}: "
          f"{', '.join(str(p) for p in sorted(real_pids))}")

    # Strategy 1: os.kill (fastest)
    for pid in real_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    time.sleep(1)

    # Strategy 2: taskkill /F /T for survivors
    remaining = _get_pids_from_netstat() & _get_live_python_pids()
    remaining.discard(my_pid)
    if remaining:
        for pid in remaining:
            os.system(f'taskkill /F /T /PID {pid} >nul 2>&1')

        for _ in range(10):
            still = _get_pids_from_netstat() & _get_live_python_pids()
            still.discard(my_pid)
            if not still:
                break
            time.sleep(0.5)

    print("  Port cleared.")


if __name__ == "__main__":
    kill_port(PORT)
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, reload=True)
