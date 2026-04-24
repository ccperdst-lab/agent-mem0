"""Uninstall: remove all agent-mem0 artifacts."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm

from agent_mem0.config import AGENT_MEM0_HOME, CONFIG_PATH
from agent_mem0.installer.claude_code import MARKER_END, MARKER_START
from agent_mem0.installer.registry import load_registry

console = Console()


def run_uninstall(*, all_flag: bool = False, force: bool = False) -> None:
    """Main uninstall entry point."""
    # Gather info for confirmation
    config = _load_config_safe()
    registry = load_registry()
    projects = registry.get("projects", {})

    # Show what will be cleaned
    console.print("\n[bold red]即将清理以下 agent-mem0 产物:[/bold red]\n")

    if projects:
        console.print("[bold]已注册项目产物:[/bold]")
        for name, info in sorted(projects.items()):
            path = info.get("path", "")
            exists = Path(path).exists() if path else False
            status = "" if exists else " [dim](路径不存在，跳过)[/dim]"
            console.print(f"  • {name}: {path}{status}")
            if exists:
                console.print(f"    - {path}/.mcp.json (agent-memory entry)")
                console.print(f"    - {path}/.claude/skills/agent-memory/")
    else:
        console.print("[dim]  无已注册项目[/dim]")

    console.print(f"\n[bold]全局文件:[/bold]")
    console.print(f"  • ~/.claude/CLAUDE.md (agent-mem0 规则区块)")
    console.print(f"  • {AGENT_MEM0_HOME}/ (配置、日志、注册表)")

    console.print(f"\n[bold]Qdrant:[/bold]")
    console.print(f"  • agent_mem0 collection")

    if all_flag:
        console.print(f"\n[bold]Docker (--all):[/bold]")
        console.print(f"  • agent-mem0-qdrant 容器")

    console.print()

    # Confirm
    if not force:
        if not Confirm.ask("[bold red]确认卸载?[/bold red]", default=False):
            console.print("[dim]已取消[/dim]")
            return

    # Execute cleanup
    _clean_project_artifacts(projects)
    _clean_claude_md()
    _clean_qdrant_collection(config)
    if all_flag:
        _clean_docker_container()
    _clean_home_dir()

    console.print("\n[bold green]✓ agent-mem0 产物已清理完毕[/bold green]")
    console.print("[dim]如需卸载 Python 包: pip uninstall agent-mem0[/dim]")


def _load_config_safe() -> dict | None:
    """Load config without failing if it doesn't exist."""
    if not CONFIG_PATH.exists():
        return None
    try:
        from agent_mem0.config import load_config
        return load_config()
    except Exception:
        return None


def _clean_project_artifacts(projects: dict) -> None:
    """Remove MCP entries and skill directories from registered projects."""
    for name, info in sorted(projects.items()):
        path = Path(info.get("path", ""))
        if not path.exists():
            console.print(f"[dim]  跳过 {name}: 路径不存在 ({path})[/dim]")
            continue

        # Clean .mcp.json
        mcp_path = path / ".mcp.json"
        if mcp_path.exists():
            try:
                data = json.loads(mcp_path.read_text(encoding="utf-8"))
                servers = data.get("mcpServers", {})
                if "agent-memory" in servers:
                    del servers["agent-memory"]
                    if not servers:
                        # mcpServers is empty, delete the file
                        mcp_path.unlink()
                        console.print(f"  ✓ 删除 {mcp_path}")
                    else:
                        data["mcpServers"] = servers
                        mcp_path.write_text(
                            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8",
                        )
                        console.print(f"  ✓ 移除 {mcp_path} 中 agent-memory entry")
            except (json.JSONDecodeError, ValueError, OSError) as e:
                console.print(f"  [yellow]⚠ 清理 {mcp_path} 失败: {e}[/yellow]")

        # Clean skill directory
        skill_dir = path / ".claude" / "skills" / "agent-memory"
        if skill_dir.exists():
            try:
                shutil.rmtree(skill_dir)
                console.print(f"  ✓ 删除 {skill_dir}")
            except OSError as e:
                console.print(f"  [yellow]⚠ 删除 {skill_dir} 失败: {e}[/yellow]")


def _clean_claude_md() -> None:
    """Remove agent-mem0 marker block from global CLAUDE.md."""
    claude_md_path = Path("~/.claude/CLAUDE.md").expanduser()
    if not claude_md_path.exists():
        return

    try:
        content = claude_md_path.read_text(encoding="utf-8")
        if MARKER_START not in content or MARKER_END not in content:
            return

        start = content.index(MARKER_START)
        end = content.index(MARKER_END) + len(MARKER_END)

        # Remove the block and any surrounding blank lines
        before = content[:start].rstrip("\n")
        after = content[end:].lstrip("\n")

        new_content = before
        if after:
            new_content += "\n" + after
        new_content = new_content.strip()

        if new_content:
            claude_md_path.write_text(new_content + "\n", encoding="utf-8")
            console.print(f"  ✓ 移除 {claude_md_path} 中 agent-mem0 规则")
        else:
            # CLAUDE.md is now empty, delete it
            claude_md_path.unlink()
            console.print(f"  ✓ 删除 {claude_md_path} (已无内容)")
    except (OSError, ValueError) as e:
        console.print(f"  [yellow]⚠ 清理 CLAUDE.md 失败: {e}[/yellow]")


def _clean_qdrant_collection(config: dict | None) -> None:
    """Delete the agent_mem0 collection from Qdrant."""
    if config is None:
        console.print("  [dim]跳过 Qdrant collection 清理 (无配置)[/dim]")
        return

    vs = config.get("vector_store", {})
    host = vs.get("host", "localhost")
    port = vs.get("port", 6333)
    collection = vs.get("collection_name", "agent_mem0")

    try:
        import urllib.request
        url = f"http://{host}:{port}/collections/{collection}"
        req = urllib.request.Request(url, method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                console.print(f"  ✓ 删除 Qdrant collection: {collection}")
                return
    except Exception:
        pass
    console.print(f"  [yellow]⚠ 无法连接 Qdrant ({host}:{port})，请手动删除 collection: {collection}[/yellow]")


def _clean_docker_container() -> None:
    """Remove the agent-mem0-qdrant Docker container."""
    if not shutil.which("docker"):
        console.print("  [yellow]⚠ Docker 不可用，请手动删除 agent-mem0-qdrant 容器[/yellow]")
        return

    try:
        result = subprocess.run(
            ["docker", "rm", "-f", "agent-mem0-qdrant"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            console.print("  ✓ 删除 Docker 容器: agent-mem0-qdrant")
        else:
            # Container might not exist
            if "No such container" in result.stderr:
                console.print("  [dim]容器 agent-mem0-qdrant 不存在，跳过[/dim]")
            else:
                console.print(f"  [yellow]⚠ 删除容器失败: {result.stderr.strip()}[/yellow]")
    except (subprocess.TimeoutExpired, OSError) as e:
        console.print(f"  [yellow]⚠ 删除容器失败: {e}[/yellow]")


def _clean_home_dir() -> None:
    """Remove ~/.agent-mem0/ directory."""
    if not AGENT_MEM0_HOME.exists():
        return

    try:
        shutil.rmtree(AGENT_MEM0_HOME)
        console.print(f"  ✓ 删除 {AGENT_MEM0_HOME}/")
    except OSError as e:
        console.print(f"  [yellow]⚠ 删除 {AGENT_MEM0_HOME} 失败: {e}[/yellow]")
