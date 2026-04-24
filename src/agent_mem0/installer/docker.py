"""Docker installation, detection, and Desktop launch.

All Docker-related subprocess calls are encapsulated here.
wizard.py and qdrant.py call these functions — never run Docker
commands directly (except qdrant.py for Qdrant-specific container ops).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path

from agent_mem0.installer.output import console
from agent_mem0.installer.progress import InstallProgress


def is_installed() -> bool:
    """Check if Docker is installed (but maybe not running).

    On macOS, checks /Applications/Docker.app.
    Also checks if ``docker`` CLI is on PATH.
    """
    if shutil.which("docker"):
        return True
    if platform.system().lower() == "darwin":
        return Path("/Applications/Docker.app").exists()
    return False


def is_ready() -> bool:
    """Check if Docker daemon is running and responsive."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install_cmd() -> list[str]:
    """Return the install command for Docker on the current platform."""
    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        return ["brew", "install", "--cask", "docker"]
    if system == "linux":
        return ["sh", "-c", "curl -fsSL https://get.docker.com | sh"]
    if system == "windows" and shutil.which("winget"):
        return ["winget", "install", "--id", "Docker.DockerDesktop",
                "-e", "--accept-source-agreements"]
    return ["docker", "--version"]


def launch_desktop(tracker: InstallProgress) -> None:
    """Launch Docker Desktop and wait for it to be ready."""
    system = platform.system().lower()
    if system == "darwin":
        subprocess.run(
            ["open", "-a", "Docker"],
            capture_output=True, timeout=10,
        )
    elif system == "linux":
        subprocess.Popen(
            ["systemctl", "start", "docker"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    # Wait for Docker to be ready (up to 60 seconds)
    for i in range(60):
        time.sleep(1)
        if i % 5 == 4:
            tracker.update_description(f"等待 Docker 就绪... ({i + 1}s)")
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                tracker.print("[green]  ✓ Docker 已就绪[/green]")
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    tracker.print("[yellow]  ⚠ Docker 未能在 60s 内就绪，请手动启动[/yellow]")
