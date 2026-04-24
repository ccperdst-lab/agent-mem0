"""Qdrant detection, installation, and management."""

from __future__ import annotations

import platform
import shutil
import subprocess

from rich.console import Console
from rich.prompt import Confirm, Prompt

console = Console()


def detect_docker() -> bool:
    """Check if Docker is installed and running."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def install_docker() -> bool:
    """Install Docker based on OS and architecture."""
    system = platform.system().lower()
    arch = platform.machine().lower()

    console.print(f"\n[yellow]检测到系统: {system} ({arch})[/yellow]")

    if system == "darwin":
        if shutil.which("brew"):
            console.print("[cyan]通过 Homebrew 安装 Docker...[/cyan]")
            result = subprocess.run(["brew", "install", "--cask", "docker"], capture_output=True, text=True)
            if result.returncode == 0:
                console.print("[green]✓ Docker 安装成功，请启动 Docker Desktop[/green]")
                return True
        console.print("[yellow]请从 https://docker.com 下载安装 Docker Desktop[/yellow]")
        return False

    elif system == "linux":
        console.print("[cyan]通过官方脚本安装 Docker...[/cyan]")
        result = subprocess.run(
            ["sh", "-c", "curl -fsSL https://get.docker.com | sh"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("[green]✓ Docker 安装成功[/green]")
            return True
        console.print(f"[red]安装失败: {result.stderr}[/red]")
        return False

    else:
        console.print(f"[yellow]不支持自动安装 Docker on {system}，请手动安装: https://docker.com[/yellow]")
        return False


def detect_qdrant_container() -> bool:
    """Check if a Qdrant container is already running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "ancestor=qdrant/qdrant", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def start_qdrant_docker(port: int = 6333, data_path: str = "~/.local/share/agent-mem0") -> bool:
    """Start Qdrant Docker container with volume mapping for data persistence."""
    if detect_qdrant_container():
        console.print(f"[green]✓ Qdrant 容器已在运行 (port {port})[/green]")
        return True

    # Ensure data directory exists
    from pathlib import Path
    storage_path = Path(data_path).expanduser() / "qdrant_storage"
    storage_path.mkdir(parents=True, exist_ok=True)

    console.print(f"[cyan]启动 Qdrant Docker 容器 (port {port})...[/cyan]")
    result = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", "agent-mem0-qdrant",
            "-p", f"{port}:6333",
            "-v", f"{storage_path}:/qdrant/storage",
            "--restart", "unless-stopped",
            "qdrant/qdrant",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print("[green]✓ Qdrant 容器已启动[/green]")
        return True

    # Container name conflict - try to start existing stopped container
    if "already in use" in result.stderr:
        restart = subprocess.run(
            ["docker", "start", "agent-mem0-qdrant"],
            capture_output=True,
            text=True,
        )
        if restart.returncode == 0:
            console.print("[green]✓ Qdrant 容器已重新启动[/green]")
            return True

    console.print(f"[red]启动失败: {result.stderr}[/red]")
    return False


def configure_qdrant() -> dict:
    """Interactive Qdrant configuration."""
    console.print("\n[bold]选择 Qdrant 存储模式[/bold]")
    console.print("  1. Docker [green](默认，推荐)[/green]")
    console.print("  2. Local（纯 Python，无需 Docker）")

    choice = Prompt.ask("选择", default="1")
    mode = "local" if choice == "2" else "docker"

    config: dict = {"provider": "qdrant", "mode": mode, "collection_name": "agent_mem0"}

    default_data_path = "~/.local/share/agent-mem0"

    if mode == "docker":
        config["host"] = Prompt.ask("Qdrant 地址", default="localhost")
        config["port"] = int(Prompt.ask("Qdrant 端口", default="6333"))
        config["data_path"] = Prompt.ask("数据持久化路径", default=default_data_path)
    else:
        config["data_path"] = Prompt.ask("数据持久化路径", default=default_data_path)

    return config
