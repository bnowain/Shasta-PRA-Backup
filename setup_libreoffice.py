"""Download and install LibreOffice Portable for document preview conversion."""

import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent / "tools"
LO_DIR = TOOLS_DIR / "LibreOffice"
SOFFICE_EXE = LO_DIR / "App" / "libreoffice" / "program" / "soffice.exe"

# LibreOffice Portable from PortableApps.com (stable release)
LO_URL = "https://download3.portableapps.com/portableapps/LibreOfficePortable/LibreOfficePortablePrevious_24.8.4.paf.exe"
INSTALLER_NAME = "LibreOfficePortable.paf.exe"


def main():
    if SOFFICE_EXE.exists():
        print(f"LibreOffice already installed at {SOFFICE_EXE}")
        verify()
        return

    TOOLS_DIR.mkdir(exist_ok=True)
    installer = TOOLS_DIR / INSTALLER_NAME

    # Download using curl (built into Windows 10/11, avoids Python SSL issues)
    if not installer.exists():
        print(f"Downloading LibreOffice Portable (~400 MB)...")
        print(f"  URL: {LO_URL}")
        result = subprocess.run(
            ["curl", "-L", "-o", str(installer), "--progress-bar", LO_URL],
            timeout=600,
        )
        if result.returncode != 0 or not installer.exists():
            print("Download failed. Try downloading manually:")
            print(f"  {LO_URL}")
            print(f"  Save to: {installer}")
            sys.exit(1)
        print("  Download complete.")
    else:
        print(f"Installer already downloaded at {installer}")

    # Extract using the PortableApps installer in silent mode
    print(f"Installing to {LO_DIR}...")
    result = subprocess.run(
        [str(installer), "/DESTINATION=" + str(LO_DIR), "/SILENT"],
        timeout=300,
    )
    if result.returncode != 0:
        print(f"Installer returned code {result.returncode}")
        print("Try running the installer manually:")
        print(f"  {installer}")
        sys.exit(1)

    # Clean up installer
    installer.unlink(missing_ok=True)

    verify()


def verify():
    if SOFFICE_EXE.exists():
        result = subprocess.run(
            [str(SOFFICE_EXE), "--headless", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        print(f"Verified: {result.stdout.strip()}")
        print(f"Path: {SOFFICE_EXE}")
    else:
        print(f"ERROR: soffice.exe not found at expected path: {SOFFICE_EXE}")
        # Try to find it
        for p in LO_DIR.rglob("soffice.exe"):
            print(f"  Found at: {p}")
        sys.exit(1)


if __name__ == "__main__":
    main()
