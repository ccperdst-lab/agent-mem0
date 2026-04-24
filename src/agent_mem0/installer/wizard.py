"""Install wizard: interactive global setup.

Two-phase design:
  Phase 1 — Interactive configuration (no progress bar, user makes choices)
  Phase 2 — Execution with a non-scrolling progress bar

This module is the orchestration layer. It calls functions from
ollama.py, docker.py, qdrant.py — never runs subprocess directly.
"""

from __future__ import annotations

import json as _json
import urllib.request

from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from agent_mem0.config import DEFAULT_CONFIG, save_config_from_template
from agent_mem0.installer import docker, ollama
from agent_mem0.installer.claude_code import inject_claude_md_rules
from agent_mem0.installer.hardware import detect_ram_gb, recommend_llm_model
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
    preset: str | None = None,
    api_key: str | None = None,
    llm_model: str | None = None,
    embedder_model: str | None = None,
    qdrant_mode: str | None = None,
) -> None:
    """Run the interactive install wizard.

    Args:
        preset: Preset name ("recommended", "light", "cloud") or None for interactive.
        api_key: API key for cloud preset.
        llm_model: Override the LLM model name.
        embedder_model: Override the embedder model name.
        qdrant_mode: Override the Qdrant storage mode.
    """
    console.print(Panel.fit(
        "[bold cyan]🧠 Agent Mem0 安装引导[/bold cyan]\n"
        "为 AI Agent 工具配置跨 session 记忆系统",
        border_style="cyan",
    ))

    # ── Phase 1: Configuration ────────────────────────────────────
    if preset:
        llm_config, embedder_config, qdrant_config = _apply_preset(
            preset, api_key=api_key,
            llm_model=llm_model, embedder_model=embedder_model,
            qdrant_mode=qdrant_mode,
        )
    else:
        llm_config, embedder_config, qdrant_config = _interactive_config(
            llm_model=llm_model, embedder_model=embedder_model,
            qdrant_mode=qdrant_mode,
        )

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
# Non-interactive preset dispatch
# ------------------------------------------------------------------

def _apply_preset(
    preset: str,
    *,
    api_key: str | None = None,
    llm_model: str | None = None,
    embedder_model: str | None = None,
    qdrant_mode: str | None = None,
) -> tuple[dict, dict, dict]:
    """Dispatch to the correct preset builder."""
    if preset == "recommended":
        console.print("\n[dim]━━━ 推荐配置 ━━━[/dim]\n")
        return _build_preset_recommended(
            llm_model=llm_model, embedder_model=embedder_model,
            qdrant_mode=qdrant_mode,
        )
    if preset == "light":
        console.print("\n[dim]━━━ 轻量模式 ━━━[/dim]\n")
        return _build_preset_light(
            llm_model=llm_model, embedder_model=embedder_model,
        )
    if preset == "cloud":
        if not api_key:
            console.print(
                "[red]错误：云端预设需要 --api-key 或 OPENAI_API_KEY 环境变量[/red]",
            )
            raise SystemExit(1)
        console.print("\n[dim]━━━ 云端 API ━━━[/dim]\n")
        return _build_preset_cloud(
            api_key=api_key, llm_model=llm_model,
            embedder_model=embedder_model, qdrant_mode=qdrant_mode,
        )
    console.print(f"[red]未知预设：{preset}[/red]")
    raise SystemExit(1)


# ------------------------------------------------------------------
# Interactive preset selection
# ------------------------------------------------------------------

def _interactive_config(
    *,
    llm_model: str | None = None,
    embedder_model: str | None = None,
    qdrant_mode: str | None = None,
) -> tuple[dict, dict, dict]:
    """Interactive Phase 1: choose a preset or advanced config."""
    choice = _choose_preset()

    if choice == "recommended":
        return _interactive_recommended(
            llm_model=llm_model, embedder_model=embedder_model,
            qdrant_mode=qdrant_mode,
        )
    if choice == "light":
        console.print("\n[dim]━━━ 轻量模式 ━━━[/dim]\n")
        return _build_preset_light(
            llm_model=llm_model, embedder_model=embedder_model,
        )
    if choice == "cloud":
        return _configure_cloud_api(
            llm_model=llm_model, embedder_model=embedder_model,
            qdrant_mode=qdrant_mode,
        )
    # advanced
    console.print("\n[dim]━━━ 高级自定义 ━━━[/dim]\n")
    llm_config = configure_llm_provider()
    embedder_config = configure_embedder_provider()
    qdrant_config = configure_qdrant()
    return llm_config, embedder_config, qdrant_config


def _choose_preset() -> str:
    """Display preset choices and return the selected preset name."""
    console.print("\n[bold]选择安装方式[/bold]\n")
    console.print("  [cyan]1.[/cyan] ✅ 推荐配置（根据你的硬件自动选择）[green]（默认）[/green]")
    console.print("  [cyan]2.[/cyan] 🪶 轻量模式（最小下载，快速体验）")
    console.print("  [cyan]3.[/cyan] ☁️  云端 API（使用 OpenAI 或其他 API）")
    console.print("  [cyan]4.[/cyan] ⚙️  高级自定义\n")

    choice = Prompt.ask("选择", default="1")
    mapping = {"1": "recommended", "2": "light", "3": "cloud", "4": "advanced"}
    return mapping.get(choice, "recommended")


def _interactive_recommended(
    *,
    llm_model: str | None = None,
    embedder_model: str | None = None,
    qdrant_mode: str | None = None,
) -> tuple[dict, dict, dict]:
    """Recommended preset with hardware info display and confirmation."""
    ram = detect_ram_gb()
    model, size = recommend_llm_model(ram)
    final_model = llm_model or model

    console.print("\n[dim]━━━ 推荐配置 ━━━[/dim]\n")
    if ram > 0:
        console.print(f"  检测到系统内存：[bold]{ram:.0f} GB[/bold]")
    else:
        console.print("  [yellow]无法检测系统内存，使用最小模型[/yellow]")
    console.print(f"  推荐 LLM 模型：[bold]{final_model}[/bold]（下载 {size}）")
    console.print(f"  Embedding 模型：[bold]{DEFAULT_CONFIG['embedder']['model']}[/bold]（下载 ~274MB）")

    mode = qdrant_mode or _auto_qdrant_mode()
    mode_label = "Docker 容器" if mode == "docker" else "本地存储"
    console.print(f"  向量数据库：[bold]{mode_label}[/bold]\n")

    if not Confirm.ask("使用此配置继续安装？", default=True):
        console.print("[dim]已取消，进入高级自定义...[/dim]")
        llm_config = configure_llm_provider()
        embedder_config = configure_embedder_provider()
        qdrant_config = configure_qdrant()
        return llm_config, embedder_config, qdrant_config

    llm_config = {
        "provider": "ollama",
        "model": final_model,
        "base_url": DEFAULT_CONFIG["llm"]["base_url"],
    }
    embedder_config = {
        "provider": "ollama",
        "model": embedder_model or DEFAULT_CONFIG["embedder"]["model"],
        "base_url": DEFAULT_CONFIG["embedder"]["base_url"],
    }
    qdrant_config = _build_qdrant_config(mode)
    return llm_config, embedder_config, qdrant_config


def _configure_cloud_api(
    *,
    llm_model: str | None = None,
    embedder_model: str | None = None,
    qdrant_mode: str | None = None,
) -> tuple[dict, dict, dict]:
    """Interactive cloud API configuration: OpenAI or other."""
    console.print("\n[bold]选择云端 API[/bold]\n")
    console.print("  [cyan]1.[/cyan] OpenAI（一个 API Key 搞定）[green]（默认）[/green]")
    console.print("  [cyan]2.[/cyan] 其他（兼容 OpenAI 格式的 API）\n")

    choice = Prompt.ask("选择", default="1")

    if choice == "2":
        return _configure_other_api(
            llm_model=llm_model, embedder_model=embedder_model,
            qdrant_mode=qdrant_mode,
        )

    # OpenAI path
    key = Prompt.ask("OpenAI API Key", password=True)
    mode = qdrant_mode or _auto_qdrant_mode()
    return _build_preset_cloud(
        api_key=key, llm_model=llm_model,
        embedder_model=embedder_model, qdrant_mode=mode,
    )


def _configure_other_api(
    *,
    llm_model: str | None = None,
    embedder_model: str | None = None,
    qdrant_mode: str | None = None,
) -> tuple[dict, dict, dict]:
    """Configure a custom OpenAI-compatible API."""
    base_url = Prompt.ask("API Base URL")
    key = Prompt.ask("API Key", password=True)
    llm = llm_model or Prompt.ask("LLM 模型名", default="gpt-4o-mini")
    emb_input = embedder_model or Prompt.ask(
        "Embedding 模型名（留空则用本地 Ollama）", default="",
    )

    llm_config: dict = {
        "provider": "openai",
        "model": llm,
        "api_key": key,
        "base_url": base_url,
    }

    if emb_input:
        embedder_config: dict = {
            "provider": "openai",
            "model": emb_input,
            "api_key": key,
            "base_url": base_url,
        }
    else:
        # Fallback to local Ollama embedder
        embedder_config = {
            "provider": "ollama",
            "model": DEFAULT_CONFIG["embedder"]["model"],
            "base_url": DEFAULT_CONFIG["embedder"]["base_url"],
        }

    mode = qdrant_mode or _auto_qdrant_mode()
    qdrant_config = _build_qdrant_config(mode)
    return llm_config, embedder_config, qdrant_config


# ------------------------------------------------------------------
# Preset builders (non-interactive mode)
# ------------------------------------------------------------------

def _auto_qdrant_mode() -> str:
    """Pick Qdrant mode automatically: docker if available, else local."""
    return "docker" if docker.is_ready() or docker.is_installed() else "local"


def _build_qdrant_config(mode: str) -> dict:
    """Build Qdrant config dict for a given mode."""
    vs = DEFAULT_CONFIG["vector_store"]
    config: dict = {
        "provider": "qdrant",
        "mode": mode,
        "collection_name": vs["collection_name"],
    }
    if mode == "external":
        config["host"] = vs["host"]
        config["port"] = vs["port"]
    elif mode == "docker":
        config["host"] = vs["host"]
        config["port"] = vs["port"]
        config["data_path"] = vs["data_path"]
    else:  # local
        config["data_path"] = vs["data_path"]
    return config


def _build_preset_recommended(
    *,
    llm_model: str | None = None,
    embedder_model: str | None = None,
    qdrant_mode: str | None = None,
) -> tuple[dict, dict, dict]:
    """Build configs for the 'recommended' preset (hardware-aware)."""
    ram = detect_ram_gb()
    auto_model, _ = recommend_llm_model(ram)

    llm_config = {
        "provider": "ollama",
        "model": llm_model or auto_model,
        "base_url": DEFAULT_CONFIG["llm"]["base_url"],
    }
    embedder_config = {
        "provider": "ollama",
        "model": embedder_model or DEFAULT_CONFIG["embedder"]["model"],
        "base_url": DEFAULT_CONFIG["embedder"]["base_url"],
    }
    mode = qdrant_mode or _auto_qdrant_mode()
    qdrant_config = _build_qdrant_config(mode)
    return llm_config, embedder_config, qdrant_config


def _build_preset_light(
    *,
    llm_model: str | None = None,
    embedder_model: str | None = None,
) -> tuple[dict, dict, dict]:
    """Build configs for the 'light' preset (smallest models, local qdrant)."""
    llm_config = {
        "provider": "ollama",
        "model": llm_model or "qwen2.5:0.5b",
        "base_url": DEFAULT_CONFIG["llm"]["base_url"],
    }
    embedder_config = {
        "provider": "ollama",
        "model": embedder_model or DEFAULT_CONFIG["embedder"]["model"],
        "base_url": DEFAULT_CONFIG["embedder"]["base_url"],
    }
    qdrant_config = _build_qdrant_config("local")
    return llm_config, embedder_config, qdrant_config


def _build_preset_cloud(
    *,
    api_key: str,
    base_url: str | None = None,
    llm_model: str | None = None,
    embedder_model: str | None = None,
    qdrant_mode: str | None = None,
) -> tuple[dict, dict, dict]:
    """Build configs for the 'cloud' preset (OpenAI-compatible API)."""
    resolved_base = base_url or "https://api.openai.com/v1"
    llm_config: dict = {
        "provider": "openai",
        "model": llm_model or "gpt-4o-mini",
        "api_key": api_key,
        "base_url": resolved_base,
    }
    embedder_config: dict = {
        "provider": "openai",
        "model": embedder_model or "text-embedding-3-small",
        "api_key": api_key,
        "base_url": resolved_base,
    }
    mode = qdrant_mode or _auto_qdrant_mode()
    qdrant_config = _build_qdrant_config(mode)
    return llm_config, embedder_config, qdrant_config


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
