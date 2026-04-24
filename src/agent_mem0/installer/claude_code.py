"""Claude Code integration: CLAUDE.md rules injection and MCP config."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_mem0.installer.output import console

MARKER_START = "<!-- agent-mem0-start -->"
MARKER_END = "<!-- agent-mem0-end -->"


def _load_template() -> str:
    """Load the global memory rules template via importlib.resources."""
    try:
        from importlib import resources
        ref = resources.files("agent_mem0") / "templates" / "claude_global_memory_rules.md"
        return ref.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, TypeError):
        return _FALLBACK_TEMPLATE


_FALLBACK_TEMPLATE = """\
# Agent Memory（由 agent-mem0 管理）

**⚠ 以下是强制执行的工具调用规则，不是建议。每一条都必须在指定时机执行对应的 tool call，没有例外。如果你发现自己准备回复用户但还没有执行下面要求的 tool call，立即停下来先执行。**

## 规则 1：Session 首次响应前 — 必须 memory_search

**触发时机**：收到本 session 第一条用户消息时，在生成任何回复文本之前。

**执行动作**：调用 `memory_search`，query 使用用户消息的关键词。

**自检**：如果你正在写本 session 的第一条回复，但还没有调用过 `memory_search`，你正在违反规则。立即调用。

## 规则 2：涉及历史/上下文时 — 必须 memory_search

**触发条件**（任一成立即触发）：
- 用户消息含"之前"、"上次"、"继续"、"还记得"、"我们不是..."等引用历史的词
- 用户的问题涉及项目的业务逻辑、架构、历史决策
- 用户提到某个技术方案或决策
- 你对当前项目上下文有任何不确定

**唯一豁免**：纯通用技术问答（语法、标准库 API）且与当前项目完全无关。有疑问就搜。

## 规则 3：每轮回复结束前 — 必须评估并执行 memory_add

**触发时机**：每一轮回复的最后一步，在回复文本完成之后、提交之前。

**执行流程**：
1. 回顾本轮对话，检查是否发生了以下任一情况：
   - 做出了技术决策（选型、架构变更、方案确定）
   - 完成了重要功能或修复
   - 用户表达了偏好、习惯或工作方式
   - 发现了重要问题、Bug 或临时方案
   - 确定了重要的业务逻辑或规则
   - 用户明确要求记住某些信息
2. 如果命中任一条：调用 `memory_add` 写入
3. 如果确实没有命中任何条目：可以跳过，但这应该是少数情况

**不要写入**的：通用技术知识、单次调试细节、代码本身（代码在 git 里）。

**project 参数**：
- 与当前项目相关 → 使用当前项目名
- 与用户个人偏好/习惯相关 → `project="global"`

**自检**：如果你的回复中涉及了决策、完成了功能、或用户表达了偏好，但你没有调用 `memory_add`，你正在违反规则。在回复末尾补上 tool call。
"""


def inject_claude_md_rules(
    claude_md_path: Path | None = None, *, quiet: bool = False,
) -> None:
    """Append or update agent-mem0 memory rules in global CLAUDE.md."""
    if claude_md_path is None:
        claude_md_path = Path("~/.claude/CLAUDE.md").expanduser()

    claude_md_path.parent.mkdir(parents=True, exist_ok=True)

    template = _load_template()
    block = f"\n{MARKER_START}\n{template}\n{MARKER_END}\n"

    if claude_md_path.exists():
        content = claude_md_path.read_text(encoding="utf-8")

        if MARKER_START in content and MARKER_END in content:
            # Update existing block
            start = content.index(MARKER_START)
            end = content.index(MARKER_END) + len(MARKER_END)
            new_content = content[:start].rstrip("\n") + block + content[end + 1:]
            claude_md_path.write_text(new_content, encoding="utf-8")
            if not quiet:
                console.print("[green]✓ 全局 CLAUDE.md 记忆规则已更新[/green]")
        else:
            # Append new block
            if not content.endswith("\n"):
                content += "\n"
            content += block
            claude_md_path.write_text(content, encoding="utf-8")
            if not quiet:
                console.print("[green]✓ 全局 CLAUDE.md 记忆规则已写入[/green]")
    else:
        claude_md_path.write_text(block.lstrip("\n"), encoding="utf-8")
        if not quiet:
            console.print("[green]✓ 全局 CLAUDE.md 已创建并写入记忆规则[/green]")


def write_project_mcp_json(project_dir: Path, project_name: str) -> None:
    """Write or merge .mcp.json for the project (Claude Code project-level MCP config)."""
    mcp_path = project_dir / ".mcp.json"

    mcp_entry = {
        "command": sys.executable,
        "args": ["-m", "agent_mem0", "serve", "--project", project_name],
    }

    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            existing = {}
    else:
        existing = {}

    if "mcpServers" not in existing:
        existing["mcpServers"] = {}

    existing["mcpServers"]["agent-memory"] = mcp_entry

    mcp_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    console.print(f"[green]✓ 项目 MCP 配置已写入 {mcp_path}[/green]")


def write_project_skill(project_dir: Path) -> None:
    """Write /agent-memory:init Skill to the project."""
    skill_dir = project_dir / ".claude" / "skills" / "agent-memory"
    skill_path = skill_dir / "SKILL.md"
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Load from package resources, fallback to inline
    try:
        from importlib import resources
        ref = resources.files("agent_mem0") / "templates" / "skill.md"
        content = ref.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, TypeError):
        content = _FALLBACK_SKILL

    skill_path.write_text(content, encoding="utf-8")
    console.print(f"[green]✓ Skill 已安装到 {skill_path}[/green]")


_FALLBACK_SKILL = """\
---
name: agent-memory:init
description: AI 分析当前项目结构并生成项目级 CLAUDE.md
trigger: /agent-memory:init
---

# /agent-memory:init

分析当前项目，生成项目级 CLAUDE.md。

## 执行步骤

### Step 1: 扫描项目

分析以下文件（如果存在）：
- go.mod / package.json / pom.xml / requirements.txt / pyproject.toml → 语言和依赖
- 目录结构（ls 顶层和关键子目录）→ 架构模式
- docker-compose.yml / Dockerfile / k8s/ → 基础设施
- Makefile / justfile → 构建方式
- README.md → 已有文档
- .env.example → 环境变量

### Step 2: 生成项目 CLAUDE.md

在 .claude/CLAUDE.md 写入（如已有内容则在开头追加项目信息段落）：

```markdown
# 项目上下文

- **project**: <项目名，从 .claude/mcp.json 的 args 中获取，或使用目录名>
- **技术栈**: <检测到的语言、框架、数据库等>
- **架构**: <目录结构推断的架构模式>
- **核心功能**: <从 README 或代码推断的主要功能>
- **构建/运行**: <从 Makefile 或 package.json 推断的命令>
- **测试**: <测试框架和运行方式>
```

### Step 3: 确认

将生成的内容展示给用户，等待用户确认或修改后再写入文件。
"""
