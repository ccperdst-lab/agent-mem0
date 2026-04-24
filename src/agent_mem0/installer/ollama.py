"""Ollama installation, detection, path resolution, and service management.

All Ollama-related subprocess calls are encapsulated here.
wizard.py calls these functions — never runs Ollama commands directly.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

from agent_mem0.installer.output import console
from agent_mem0.installer.progress import InstallProgress


def detect() -> bool:
    """Check if Ollama is installed (on PATH)."""
    return shutil.which("ollama") is not None


def install_cmd() -> list[str]:
    """Return the install command for Ollama on the current platform."""
    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        return ["brew", "install", "ollama"]
    if system == "linux":
        return ["sh", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"]
    if system == "windows" and shutil.which("winget"):
        return ["winget", "install", "--id", "Ollama.Ollama", "-e",
                "--accept-source-agreements"]
    # Fallback — will fail gracefully, wizard prints manual instructions
    return ["ollama", "--version"]


def resolve_path() -> str | None:
    """Find Ollama binary path, even if not on current PATH.

    On Windows, winget installs to a user-specific directory that may
    not be on PATH until the terminal is restarted. This function
    checks common install locations.
    """
    found = shutil.which("ollama")
    if found:
        return found

    if platform.system().lower() != "windows":
        return None

    # Common winget / manual install locations on Windows
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Ollama" / "ollama.exe",
        Path(os.environ.get("USERPROFILE", ""))
        / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def pull_cmd(model: str, *, ollama_bin: str = "ollama") -> list[str]:
    """Return the command to pull an Ollama model."""
    return [ollama_bin, "pull", model]


def ensure_ready(
    tracker: InstallProgress,
    *,
    ollama_bin: str = "ollama",
) -> None:
    """Ensure Ollama service is running with retries."""
    # First check if already running
    try:
        result = subprocess.run(
            [ollama_bin, "list"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            tracker.print("[green]  ✓ Ollama 服务已就绪[/green]")
            return
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Start the service
    tracker.update_description("启动 Ollama 服务...")
    try:
        subprocess.Popen(
            [ollama_bin, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        tracker.print(
            "[yellow]  ⚠ Ollama 命令未找到，"
            "可能需要重启终端刷新 PATH[/yellow]",
        )
        return

    # Wait with retries (up to 15 seconds)
    for i in range(15):
        time.sleep(1)
        tracker.update_description(f"等待 Ollama 就绪... ({i + 1}s)")
        try:
            result = subprocess.run(
                [ollama_bin, "list"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                tracker.print("[green]  ✓ Ollama 服务已就绪[/green]")
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    tracker.print("[yellow]  ⚠ Ollama 服务可能未完全就绪，继续尝试...[/yellow]")
