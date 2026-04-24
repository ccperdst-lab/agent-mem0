"""Status command: show agent-mem0 system status."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_mem0.config import CONFIG_PATH, load_config
from agent_mem0.installer.registry import load_registry

console = Console()


def _check_qdrant(config: dict) -> tuple[str, str]:
    """Check Qdrant connectivity. Returns (status_icon, message)."""
    vs = config.get("vector_store", {})
    mode = vs.get("mode", "docker")

    if mode == "local":
        path = Path(vs.get("path", "")).expanduser()
        if path.exists():
            return "✅", f"Local ({path})"
        return "⚠️", f"Local (目录不存在: {path})"

    host = vs.get("host", "localhost")
    port = vs.get("port", 6333)
    try:
        import urllib.request
        url = f"http://{host}:{port}/healthz"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                return "✅", f"Docker ({host}:{port})"
    except Exception:
        pass
    return "❌", f"Docker ({host}:{port}) - 无法连接"


def _check_project_setup() -> tuple[str, str]:
    """Check if current directory has been set up."""
    mcp_path = Path.cwd() / ".mcp.json"
    if not mcp_path.exists():
        return "❌", "未配置"

    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        if "agent-memory" in servers:
            args = servers["agent-memory"].get("args", [])
            project = ""
            for i, a in enumerate(args):
                if a == "--project" and i + 1 < len(args):
                    project = args[i + 1]
            return "✅", f"已配置 (project: {project})"
    except (json.JSONDecodeError, ValueError):
        pass
    return "⚠️", "mcp.json 存在但配置异常"


def _count_memories(config: dict, project: str) -> tuple[int, int]:
    """Count memories for project and global. Returns (project_count, global_count)."""
    try:
        from mem0 import Memory
        from agent_mem0.config import build_mem0_config

        mem0_config = build_mem0_config(config, project)
        memory = Memory.from_config(mem0_config)

        project_mems = memory.get_all(filters={"user_id": project})
        global_mems = memory.get_all(filters={"user_id": "global"})

        p_count = len(project_mems.get("results", [])) if isinstance(project_mems, dict) else len(project_mems)
        g_count = len(global_mems.get("results", [])) if isinstance(global_mems, dict) else len(global_mems)
        return p_count, g_count
    except Exception:
        return -1, -1


def show_status() -> None:
    """Display agent-mem0 system status."""
    console.print(Panel.fit("[bold cyan]🧠 Agent Mem0 Status[/bold cyan]", border_style="cyan"))

    # Config
    if not CONFIG_PATH.exists():
        console.print("[red]✗ 全局配置未找到。请运行 agent-mem0 install[/red]")
        return

    config = load_config()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("项目", style="bold")
    table.add_column("状态")

    # Qdrant
    qdrant_icon, qdrant_msg = _check_qdrant(config)
    table.add_row("Qdrant", f"{qdrant_icon} {qdrant_msg}")

    # LLM
    llm = config.get("llm", {})
    table.add_row("LLM", f"{llm.get('provider', '?')} ({llm.get('model', '?')})")

    # Embedder
    emb = config.get("embedder", {})
    table.add_row("Embedder", f"{emb.get('provider', '?')} ({emb.get('model', '?')})")

    # Project setup
    proj_icon, proj_msg = _check_project_setup()
    table.add_row("当前项目", f"{proj_icon} {proj_msg}")

    console.print(table)

    # Memory count (only if project is set up and Qdrant is reachable)
    if proj_icon == "✅" and qdrant_icon == "✅":
        # Extract project name
        mcp_path = Path.cwd() / ".mcp.json"
        try:
            data = json.loads(mcp_path.read_text(encoding="utf-8"))
            args = data["mcpServers"]["agent-memory"]["args"]
            project = args[args.index("--project") + 1]
            p_count, g_count = _count_memories(config, project)
            if p_count >= 0:
                console.print(f"\n记忆统计: {project}={p_count} 条, global={g_count} 条")
        except Exception:
            pass

    # Registered projects
    _show_registered_projects()


def _check_project_mcp(project_path: Path) -> str:
    """Check if a project has valid agent-memory MCP config. Returns status icon."""
    mcp_path = project_path / ".mcp.json"
    if not mcp_path.exists():
        return "⚠️"
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
        if "agent-memory" in data.get("mcpServers", {}):
            return "✅"
    except (json.JSONDecodeError, ValueError):
        pass
    return "⚠️"


def _show_registered_projects() -> None:
    """Display all registered projects and their status."""
    registry = load_registry()
    projects = registry.get("projects", {})

    if not projects:
        console.print("\n[dim]无已注册项目[/dim]")
        return

    console.print("\n[bold]已注册项目:[/bold]")
    proj_table = Table(box=None, padding=(0, 2))
    proj_table.add_column("项目名", style="cyan")
    proj_table.add_column("路径")
    proj_table.add_column("状态")

    for name, info in sorted(projects.items()):
        path = Path(info.get("path", ""))
        if not path.exists():
            icon = "❌ 路径不存在"
        else:
            mcp_icon = _check_project_mcp(path)
            icon = f"{mcp_icon} MCP {'正常' if mcp_icon == '✅' else '缺失'}"
        # Truncate long paths
        path_str = str(path)
        if len(path_str) > 45:
            path_str = "..." + path_str[-42:]
        proj_table.add_row(name, path_str, icon)

    console.print(proj_table)
