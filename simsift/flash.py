"""
flash.py - Download and flash SimSift firmware from GitHub Releases.
"""

import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
import json
from pathlib import Path

REPO = "EspilonOrg/Espilon-SimSift"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
BOARDS = ("t-call", "t-sim7070g")


def _latest_release() -> dict:
    req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API error {e.code}: {e.reason}")
    except OSError as e:
        raise RuntimeError(f"Network error: {e}")


def _find_asset(release: dict, board: str) -> tuple[str, str]:
    """Return (name, download_url) for the matching board binary."""
    for asset in release.get("assets", []):
        name = asset["name"]
        if f"-{board}-" in name and name.endswith(".bin"):
            return name, asset["browser_download_url"]
    tag = release.get("tag_name", "?")
    raise RuntimeError(
        f"No binary for board '{board}' in release {tag}. "
        f"Available: {[a['name'] for a in release.get('assets', [])]}"
    )


def _esptool() -> str:
    tool = shutil.which("esptool.py") or shutil.which("esptool")
    if not tool:
        raise RuntimeError(
            "esptool not found. Install it with:  pip install esptool"
        )
    return tool


def run(board: str, port: str, baud: int = 460800) -> None:
    from .ui import console, info, ok, error

    info(f"Fetching latest release from [accent]github.com/{REPO}[/] ...")
    try:
        release = _latest_release()
    except RuntimeError as e:
        error(str(e))
        sys.exit(1)

    tag = release.get("tag_name", "unknown")
    info(f"Latest release: [accent]{tag}[/]")

    try:
        name, url = _find_asset(release, board)
    except RuntimeError as e:
        error(str(e))
        sys.exit(1)

    info(f"Downloading [accent]{name}[/] ...")
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            urllib.request.urlretrieve(url, tmp_path)
        except OSError as e:
            error(f"Download failed: {e}")
            sys.exit(1)

    ok(f"Downloaded {tmp_path.stat().st_size // 1024} KB")

    try:
        tool = _esptool()
    except RuntimeError as e:
        error(str(e))
        tmp_path.unlink(missing_ok=True)
        sys.exit(1)

    info(f"Flashing [accent]{board}[/] on [accent]{port}[/] at {baud} baud ...")
    console.print()

    cmd = [
        tool,
        "--chip", "esp32",
        "--port", port,
        "--baud", str(baud),
        "write_flash",
        "--flash_mode", "dio",
        "--flash_freq", "40m",
        "--flash_size", "detect",
        "0x10000", str(tmp_path),
    ]

    ret = subprocess.run(cmd)
    tmp_path.unlink(missing_ok=True)

    if ret.returncode != 0:
        error("Flash failed.")
        sys.exit(ret.returncode)

    console.print()
    ok(f"[accent]{board}[/] flashed successfully with firmware [accent]{tag}[/]")
