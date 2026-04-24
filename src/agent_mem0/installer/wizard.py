"""Install wizard: interactive global setup.

Two-phase design:
  Phase 1 — Interactive configuration (no progress bar, user makes choices)
  Phase 2 — Execution with a non-scrolling progress bar

This module is the orchestration layer. It calls functions from
ollama.py, docker.py, qdrant.py — never runs subprocess directly.
"""

from __future__ import annotations

from rich.panel import Panel

from agent_mem0.config import DEFAULT_CONFIG, save_config_from_template
from agent_mem0.installer import docker, ollama
from agent_mem0.installer.claude_code import inject_claude_md_rules
from agent_mem0.installer.output import console
from agent_mem0.installer.progress import InstallProgress, Step
from agent_mem0.installer.providers import (
    configure_embedder_provider,
    configure_llm_provider,
)
from agent_mem0.installer.qdrant import (
    configure_qdrant,
    detect_qdrant_container,
    start_qdrant_container,
)


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def run_install_wizard(
    *,
    use_default: bool = False,
    llm_model: str | None = None,
    embedder_model: str | None = None,
    qdrant_mode: str | None = None,
) -> None:
    """Run the interactive install wizard.

    Args:
        use_default: Skip all interactive prompts, use default config values.
        llm_model: Override the default LLM model name.
        embedder_model: Override the default embedder model name.
        qdrant_mode: Override the default Qdrant storage mode ("docker" or "local").
    """
    console.print(Panel.fit(
        "[bold cyan]🧠 Agent Mem0 安装引导[/bold cyan]\n"
        "为 AI Agent 工具配置跨 session 记忆系统",
        border_style="cyan",
    ))

    # ── Phase 1: Configuration ────────────────────────────────────
    if use_default:
        console.print("\n[dim]━━━ 使用默认配置 ━━━[/dim]\n")
        llm_config = _build_default_llm_config(model=llm_model)
        embedder_config = _build_default_embedder_config(model=embedder_model)
        qdrant_config = _build_default_qdrant_config(mode=qdrant_mode)
    else:
        console.print("\n[dim]━━━ 配置选项 ━━━[/dim]\n")
        llm_config = configure_llm_provider()
        embedder_config = configure_embedder_provider()
        qdrant_config = configure_qdrant()

    # ── Phase 2: Execution with progress bar ──────────────────────
    steps = _build_execution_plan(llm_config, embedder_config, qdrant_config)
    console.print(f"\n[dim]━━━ 安装组件（共 {len(steps)} 步）━━━[/dim]\n")

    tracker = InstallProgress(console)
    tracker.plan(steps)

    with tracker:
        _execute_plan(tracker, llm_config, embedder_config, qdrant_config, steps)

    # ── Done ──────────────────────────────────────────────────────
    console.print(Panel.fit(
        "[bold green]🎉 安装完成！[/bold green]\n\n"
        "下一步：\n"
        "  1. cd 到你的项目目录\n"
        "  2. 运行 [cyan]agent-mem0 setup[/cyan] 初始化项目记忆\n"
        "  3. 启动 Claude Code，输入 [cyan]/agent-memory:init[/cyan] 生成项目上下文",
        border_style="green",
    ))


# ------------------------------------------------------------------
# Default config builders (non-interactive mode)
# ------------------------------------------------------------------

def _build_default_llm_config(*, model: str | None = None) -> dict:
    """Build LLM config from defaults, with optional model override."""
    return {
        "provider": "ollama",
        "model": model or DEFAULT_CONFIG["llm"]["model"],
        "base_url": DEFAULT_CONFIG["llm"]["base_url"],
    }


def _build_default_embedder_config(*, model: str | None = None) -> dict:
    """Build embedder config from defaults, with optional model override."""
    return {
        "provider": "ollama",
        "model": model or DEFAULT_CONFIG["embedder"]["model"],
        "base_url": DEFAULT_CONFIG["embedder"]["base_url"],
    }


def _build_default_qdrant_config(*, mode: str | None = None) -> dict:
    """Build Qdrant config from defaults, with optional mode override."""
    vs = DEFAULT_CONFIG["vector_store"]
    resolved_mode = mode or vs["mode"]
    config: dict = {
        "provider": "qdrant",
        "mode": resolved_mode,
        "collection_name": vs["collection_name"],
        "data_path": vs["data_path"],
    }
    if resolved_mode == "docker":
        config["host"] = vs["host"]
        config["port"] = vs["port"]
    return config


# ------------------------------------------------------------------
# Execution plan
# ------------------------------------------------------------------

def _build_execution_plan(
    llm_config: dict,
    embedder_config: dict,
    qdrant_config: dict,
) -> list[Step]:
    """Build the list of execution steps based on user choices."""
    steps: list[Step] = []

    needs_ollama = (
        llm_config.get("provider") == "ollama"
        or embedder_config.get("provider") == "ollama"
    )

    # Ollama install (only if needed and not yet present)
    if needs_ollama and not ollama.detect():
        steps.append(Step("install_ollama", "安装 Ollama", weight=15))

    # Ollama service
    if needs_ollama:
        steps.append(Step("start_ollama", "启动 Ollama 服务", weight=5))

    # Model pulls (deduplicated)
    models_to_pull: list[str] = []
    if llm_config.get("provider") == "ollama":
        models_to_pull.append(llm_config.get("model", "qwen2.5:7b"))
    if embedder_config.get("provider") == "ollama":
        m = embedder_config.get("model", "nomic-embed-text")
        if m not in models_to_pull:
            models_to_pull.append(m)

    for model in models_to_pull:
        steps.append(Step(f"pull_{model}", f"拉取模型 {model}", weight=25))

    # Docker + Qdrant
    if qdrant_config.get("mode") == "docker":
        if not docker.is_ready():
            if docker.is_installed():
                steps.append(Step("launch_docker", "启动 Docker Desktop", weight=10))
            else:
                steps.append(Step("install_docker", "安装 Docker", weight=15))
                steps.append(Step("launch_docker", "启动 Docker Desktop", weight=10))
        steps.append(Step("pull_qdrant", "拉取 Qdrant 镜像", weight=10))
        steps.append(Step("start_qdrant", "启动 Qdrant 容器", weight=5))

    # Config & rules (always)
    steps.append(Step("save_config", "保存配置", weight=5))
    steps.append(Step("inject_rules", "写入 CLAUDE.md 记忆规则", weight=5))

    return steps


# ------------------------------------------------------------------
# Execution
# ------------------------------------------------------------------

def _execute_plan(
    tracker: InstallProgress,
    llm_config: dict,
    embedder_config: dict,
    qdrant_config: dict,
    steps: list[Step],
) -> None:
    """Execute every step in the plan while updating the progress bar."""
    step_keys = {s.key for s in steps}
    ollama_bin = "ollama"  # May be updated to absolute path after install

    # ── Install Ollama ────────────────────────────────────────────
    if "install_ollama" in step_keys:
        success, output = tracker.run_subprocess(
            ollama.install_cmd(), "install_ollama",
        )
        already_installed = (
            "已安装" in output or "already installed" in output.lower()
        )
        if success or already_installed:
            tracker.print("[green]  ✓ Ollama 安装成功[/green]")
        else:
            tracker.print(
                "[red]  ✗ Ollama 安装失败，"
                "请手动安装: https://ollama.ai[/red]",
            )
            _print_error_detail(tracker, output)

        # On Windows, winget installs may not be on current PATH
        resolved = ollama.resolve_path()
        if resolved:
            ollama_bin = resolved

    # ── Start Ollama ──────────────────────────────────────────────
    if "start_ollama" in step_keys:
        tracker.begin_step("start_ollama")
        ollama.ensure_ready(tracker, ollama_bin=ollama_bin)
        tracker.complete_step("start_ollama")

    # ── Pull models ───────────────────────────────────────────────
    non_model_pulls = {"pull_qdrant"}
    models_to_pull = [
        s.key.removeprefix("pull_")
        for s in steps
        if s.key.startswith("pull_") and s.key not in non_model_pulls
    ]
    for model in models_to_pull:
        key = f"pull_{model}"
        success, output = tracker.run_subprocess(
            ollama.pull_cmd(model, ollama_bin=ollama_bin),
            key, parse_pct=True,
        )
        if success:
            tracker.print(f"[green]  ✓ 模型 {model} 就绪[/green]")
        else:
            tracker.print(f"[red]  ✗ 模型 {model} 拉取失败[/red]")
            _print_error_detail(tracker, output)
            tracker.print(f"[yellow]    手动运行: ollama pull {model}[/yellow]")

    # ── Install Docker ────────────────────────────────────────────
    if "install_docker" in step_keys:
        success, output = tracker.run_subprocess(
            docker.install_cmd(), "install_docker",
        )
        already_installed = (
            "已安装" in output or "already installed" in output.lower()
        )
        if success or already_installed:
            tracker.print("[green]  ✓ Docker 已安装[/green]")
        else:
            tracker.print(
                "[red]  ✗ Docker 安装失败，"
                "请手动安装: https://docker.com[/red]",
            )
            _print_error_detail(tracker, output)

    # ── Launch Docker Desktop ─────────────────────────────────────
    if "launch_docker" in step_keys:
        tracker.begin_step("launch_docker")
        docker.launch_desktop(tracker)
        tracker.complete_step("launch_docker")

    # ── Pull + Start Qdrant ──────────────────────────────────────
    if "pull_qdrant" in step_keys:
        _execute_qdrant_steps(tracker, qdrant_config)

    # ── Save config ───────────────────────────────────────────────
    _execute_save_config(tracker, llm_config, embedder_config, qdrant_config)

    # ── Inject CLAUDE.md rules ────────────────────────────────────
    tracker.begin_step("inject_rules")
    inject_claude_md_rules(quiet=True)
    tracker.print("[green]  ✓ CLAUDE.md 记忆规则已写入[/green]")
    tracker.complete_step("inject_rules")


def _execute_qdrant_steps(
    tracker: InstallProgress,
    qdrant_config: dict,
) -> None:
    """Execute Qdrant pull and start steps."""
    port = qdrant_config.get("port", 6333)

    # Check if already running — skip both pull and start
    if detect_qdrant_container():
        tracker.begin_step("pull_qdrant")
        tracker.print(
            f"[green]  ✓ Qdrant 容器已在运行 (port {port})[/green]",
        )
        tracker.complete_step("pull_qdrant")
        tracker.begin_step("start_qdrant")
        tracker.complete_step("start_qdrant")
        return

    # Pull image
    pull_ok, pull_out = tracker.run_subprocess(
        ["docker", "pull", "qdrant/qdrant"], "pull_qdrant", parse_pct=True,
    )
    if pull_ok:
        tracker.print("[green]  ✓ Qdrant 镜像就绪[/green]")
    else:
        tracker.print("[red]  ✗ Qdrant 镜像拉取失败[/red]")
        _print_error_detail(tracker, pull_out)

    # Start container
    tracker.begin_step("start_qdrant")
    if pull_ok:
        data_path = qdrant_config.get("data_path", "~/.local/share/agent-mem0")
        ok = start_qdrant_container(port, data_path=data_path)
        if ok:
            tracker.print(f"[green]  ✓ Qdrant 已启动 (port {port})[/green]")
        else:
            tracker.print("[red]  ✗ Qdrant 容器启动失败[/red]")
    tracker.complete_step("start_qdrant")


def _execute_save_config(
    tracker: InstallProgress,
    llm_config: dict,
    embedder_config: dict,
    qdrant_config: dict,
) -> None:
    """Build merged config and save to disk."""
    tracker.begin_step("save_config")
    config = DEFAULT_CONFIG.copy()
    config["llm"] = {**config["llm"], **llm_config}
    config["embedder"] = {**config["embedder"], **embedder_config}
    config["vector_store"] = {**config["vector_store"], **qdrant_config}

    # Detect real embedding dimensions from the model
    dims = _detect_embedding_dims(embedder_config)
    config["vector_store"]["embedding_model_dims"] = dims
    tracker.print(f"[dim]  检测到 embedding 维度: {dims}[/dim]")

    # Build overrides: only user-chosen values that differ from defaults
    overrides: dict[str, dict] = {}
    for section in ("llm", "embedder", "vector_store"):
        section_overrides = {}
        for key, value in config[section].items():
            if value != DEFAULT_CONFIG[section].get(key):
                section_overrides[key] = value
        if section_overrides:
            overrides[section] = section_overrides
    save_config_from_template(overrides)
    tracker.print("[green]  ✓ 配置已保存到 ~/.agent-mem0/config.yaml[/green]")
    tracker.complete_step("save_config")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _print_error_detail(tracker: InstallProgress, output: str) -> None:
    """Print the last meaningful lines of error output."""
    lines = [ln.strip() for ln in output.strip().splitlines() if ln.strip()]
    if lines:
        for line in lines[-3:]:
            tracker.print(f"[dim]    {line[:200]}[/dim]")


# Known embedding dimensions for common models
_KNOWN_DIMS: dict[str, int] = {
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
    "nomic-embed-text": 768,
}


def _detect_embedding_dims(embedder_config: dict) -> int:
    """Detect embedding dimensions by calling the model with a test input."""
    provider = embedder_config.get("provider", "ollama")
    model = embedder_config.get("model", "nomic-embed-text")

    try:
        if provider == "ollama":
            import ollama as ollama_client  # Delayed: heavy third-party lib
            base_url = embedder_config.get("base_url", "http://localhost:11434")
            client = ollama_client.Client(host=base_url)
            resp = client.embed(model=model, input="dimension probe")
            embeddings = resp.get("embeddings", [[]])
            if embeddings and embeddings[0]:
                return len(embeddings[0])

        elif provider in ("openai", "litellm"):
            import json as _json
            import urllib.request
            base_url = embedder_config.get("base_url", "https://api.openai.com/v1")
            api_key = embedder_config.get("api_key", "")
            url = f"{base_url.rstrip('/')}/embeddings"
            payload = _json.dumps(
                {"model": model, "input": "dimension probe"},
            ).encode()
            req = urllib.request.Request(
                url, data=payload, method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
                embedding = data.get("data", [{}])[0].get("embedding", [])
                if embedding:
                    return len(embedding)
    except Exception:
        pass

    # Fallback: known dimensions for common models
    model_name = model.split("/")[-1] if "/" in model else model
    if model_name in _KNOWN_DIMS:
        return _KNOWN_DIMS[model_name]

    if provider in ("openai", "litellm"):
        return 1536
    return 768
