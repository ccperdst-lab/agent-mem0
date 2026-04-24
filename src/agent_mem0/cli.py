"""CLI entry point for agent-mem0."""

from __future__ import annotations

import click
from rich.console import Console

from agent_mem0 import __version__

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="agent-mem0")
def main() -> None:
    """agent-mem0: Cross-session memory for AI Agent tools."""
    from agent_mem0.config import CONFIG_PATH, load_config, setup_no_proxy

    if CONFIG_PATH.exists():
        try:
            config = load_config()
            setup_no_proxy(config)
        except Exception:
            pass  # config not yet available (e.g., first install)


@main.command()
def install() -> None:
    """Global installation wizard: configure providers, storage, and CLAUDE.md rules."""
    from agent_mem0.installer.wizard import run_install_wizard

    run_install_wizard()


@main.command()
@click.option("--name", default=None, help="Project name (default: current directory name)")
def setup(name: str | None) -> None:
    """Project-level setup: install MCP config and Skill for the current project."""
    from agent_mem0.installer.setup import run_setup

    run_setup(project_name=name)


@main.command()
def status() -> None:
    """Show agent-mem0 system status."""
    from agent_mem0.installer.status import show_status

    show_status()


@main.command()
@click.option("--purge", is_flag=True, default=False, help="Also remove user memory data and Docker container")
@click.option("--force", "-f", is_flag=True, default=False, help="Skip confirmation prompt")
def uninstall(purge: bool, force: bool) -> None:
    """Remove agent-mem0 config and artifacts. Use --purge to also delete memory data."""
    from agent_mem0.installer.uninstall import run_uninstall

    run_uninstall(purge=purge, force=force)


@main.command()
@click.option("--project", required=True, help="Locked project name for this MCP Server instance")
def serve(project: str) -> None:
    """Start MCP Server (stdio mode). Usually called by Claude Code, not manually."""
    from agent_mem0.server.mcp_server import run_server

    run_server(project=project)


if __name__ == "__main__":
    main()
