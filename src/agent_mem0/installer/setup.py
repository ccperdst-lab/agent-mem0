"""Project-level setup: MCP config + Skill installation."""

from __future__ import annotations

from pathlib import Path

from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from agent_mem0.config import CONFIG_DIR, CONFIG_PATH
from agent_mem0.installer.claude_code import write_project_mcp_json, write_project_skill
from agent_mem0.installer.output import console
from agent_mem0.installer.registry import register_project


def run_setup(project_name: str | None = None) -> None:
    """Run project-level setup."""
    project_dir = Path.cwd()

    # Check if install has been run
    if not CONFIG_PATH.exists():
        console.print(f"[red]✗ 未找到全局配置文件 {CONFIG_DIR}/config.yaml[/red]")
        console.print("  请先运行 [cyan]agent-mem0 install[/cyan] 完成全局安装")
        raise SystemExit(1)

    # Detect or confirm project name
    if project_name is None:
        default_name = project_dir.name
        console.print(f"\n检测到项目目录: [cyan]{default_name}[/cyan]")
        if Confirm.ask("使用此名称作为项目标识?", default=True):
            project_name = default_name
        else:
            project_name = Prompt.ask("输入自定义项目名")

    console.print(f"\n[bold]项目: {project_name}[/bold]")
    console.print(f"目录: {project_dir}\n")

    # Write .claude/mcp.json
    write_project_mcp_json(project_dir, project_name)

    # Write .claude/skills/agent-memory/SKILL.md
    write_project_skill(project_dir)

    # Register project in global registry
    register_project(project_name, project_dir)

    # Done
    console.print(Panel.fit(
        f"[bold green]✓ 项目 '{project_name}' 记忆系统已就绪[/bold green]\n\n"
        "启动 Claude Code 后输入 [cyan]/agent-memory:init[/cyan] 生成项目上下文",
        border_style="green",
    ))
