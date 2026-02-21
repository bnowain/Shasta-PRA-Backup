"""Launch the Shasta PRA Backup web application."""

import subprocess
import sys

import uvicorn
from app.config import PORT


def kill_port(port: int):
    """Kill any process currently listening on the given port (Windows)."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if f"127.0.0.1:{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True, timeout=5,
                )
                print(f"  Killed PID {pid} on port {port}")
    except Exception as e:
        print(f"  Port cleanup skipped: {e}")


if __name__ == "__main__":
    kill_port(PORT)
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, reload=True)
