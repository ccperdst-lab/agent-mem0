"""Qdrant detection, configuration, and container management.

Docker detection is delegated to docker.py. This module handles
only Qdrant-specific logic: interactive config, container lifecycle.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.prompt import Prompt

from agent_mem0.installer.output import console


def detect_qdrant_container() -> bool:
    """Check if a Qdrant container is already running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "ancestor=qdrant/qdrant",
             "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=5,
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def start_qdrant_container(
    port: int = 6333,
    *,
    data_path: str = "~/.local/share/agent-mem0",
) -> bool:
    """Create and start the Qdrant Docker container with volume mapping."""
    storage_path = Path(data_path).expanduser() / "qdrant_storage"
    storage_path.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", "agent-mem0-qdrant",
            "-p", f"{port}:6333",
            "-v", f"{storage_path}:/qdrant/storage",
            "--restart", "unless-stopped",
            "qdrant/qdrant",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        return True

    # Container name conflict — try restart
    if "already in use" in result.stderr:
        restart = subprocess.run(
            ["docker", "start", "agent-mem0-qdrant"],
            capture_output=True, text=True, timeout=15,
        )
        return restart.returncode == 0

    return False


def configure_qdrant() -> dict:
    """Interactive Qdrant configuration."""
    console.print("\n[bold]选择 Qdrant 存储模式[/bold]")
    console.print("  1. Docker [green](默认，推荐)[/green]")
    console.print("  2. Local（纯 Python，无需 Docker）")

    choice = Prompt.ask("选择", default="1")
    mode = "local" if choice == "2" else "docker"

    config: dict = {
        "provider": "qdrant",
        "mode": mode,
        "collection_name": "agent_mem0",
    }

    default_data_path = "~/.local/share/agent-mem0"

    if mode == "docker":
        config["host"] = Prompt.ask("Qdrant 地址", default="localhost")
        config["port"] = int(Prompt.ask("Qdrant 端口", default="6333"))
        config["data_path"] = Prompt.ask("数据持久化路径", default=default_data_path)
    else:
        config["data_path"] = Prompt.ask("数据持久化路径", default=default_data_path)

    return config
