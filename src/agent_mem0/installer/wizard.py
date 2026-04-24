"""Install wizard: interactive global setup.

Two-phase design:
  Phase 1 — Interactive configuration (no progress bar, user makes choices)
  Phase 2 — Execution with a non-scrolling progress bar
"""

from __future__ import annotations

import platform
import shutil
import subprocess

from rich.console import Console
from rich.panel import Panel

from agent_mem0.config import DEFAULT_CONFIG, save_config, save_config_from_template
from agent_mem0.installer.claude_code import inject_claude_md_rules
from agent_mem0.installer.progress import InstallProgress, Step
from agent_mem0.installer.providers import (
    configure_embedder_provider,
    configure_llm_provider,
    detect_ollama,
)
from agent_mem0.installer.qdrant import configure_qdrant

console = Console()


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def run_install_wizard() -> None:
    """Run the interactive install wizard."""
    console.print(Panel.fit(
        "[bold cyan]🧠 Agent Mem0 安装引导[/bold cyan]\n"
        "为 AI Agent 工具配置跨 session 记忆系统",
        border_style="cyan",
    ))

    # ── Phase 1: Interactive configuration ────────────────────────
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
    if needs_ollama and not detect_ollama():
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
        if not _is_docker_ready():
            if _is_docker_installed():
                # Installed but not running — just need to launch
                steps.append(Step("launch_docker", "启动 Docker Desktop", weight=10))
            else:
                # Not installed at all
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

    # ── Install Ollama ────────────────────────────────────────────
    if "install_ollama" in step_keys:
        success, output = tracker.run_subprocess(
            _ollama_install_cmd(), "install_ollama",
        )
        if success:
            tracker.print("[green]  ✓ Ollama 安装成功[/green]")
        else:
            tracker.print("[red]  ✗ Ollama 安装失败，请手动安装: https://ollama.ai[/red]")
            _print_error_detail(tracker, output)

    # ── Start Ollama ──────────────────────────────────────────────
    if "start_ollama" in step_keys:
        tracker.begin_step("start_ollama")
        _ensure_ollama_ready(tracker)
        tracker.complete_step("start_ollama")

    # ── Pull models ───────────────────────────────────────────────
    models_to_pull = [
        s.key.removeprefix("pull_") for s in steps if s.key.startswith("pull_")
    ]
    for model in models_to_pull:
        key = f"pull_{model}"
        success, output = tracker.run_subprocess(
            ["ollama", "pull", model], key, parse_pct=True,
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
            _docker_install_cmd(), "install_docker",
        )
        if success:
            tracker.print("[green]  ✓ Docker 已安装[/green]")
        else:
            tracker.print("[red]  ✗ Docker 安装失败，请手动安装: https://docker.com[/red]")
            _print_error_detail(tracker, output)

    # ── Launch Docker Desktop ─────────────────────────────────────
    if "launch_docker" in step_keys:
        tracker.begin_step("launch_docker")
        _launch_docker_desktop(tracker)
        tracker.complete_step("launch_docker")

    # ── Pull + Start Qdrant ──────────────────────────────────────
    if "pull_qdrant" in step_keys:
        port = qdrant_config.get("port", 6333)

        # Check if already running — skip both pull and start
        already_running = False
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "ancestor=qdrant/qdrant", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                already_running = True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        if already_running:
            tracker.begin_step("pull_qdrant")
            tracker.print(f"[green]  ✓ Qdrant 容器已在运行 (port {port})[/green]")
            tracker.complete_step("pull_qdrant")
            tracker.begin_step("start_qdrant")
            tracker.complete_step("start_qdrant")
        else:
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
                ok = _start_qdrant_container(port, data_path=data_path)
                if ok:
                    tracker.print(f"[green]  ✓ Qdrant 已启动 (port {port})[/green]")
                else:
                    tracker.print("[red]  ✗ Qdrant 容器启动失败[/red]")
            tracker.complete_step("start_qdrant")

    # ── Save config ───────────────────────────────────────────────
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

    # ── Inject CLAUDE.md rules ────────────────────────────────────
    tracker.begin_step("inject_rules")
    inject_claude_md_rules(quiet=True)
    tracker.print("[green]  ✓ CLAUDE.md 记忆规则已写入[/green]")
    tracker.complete_step("inject_rules")


# ------------------------------------------------------------------
# Low-level helpers (avoid conflicting console output from provider
# modules by calling subprocess directly here)
# ------------------------------------------------------------------

def _print_error_detail(tracker: InstallProgress, output: str) -> None:
    """Print the last meaningful line of error output."""
    lines = [l.strip() for l in output.strip().splitlines() if l.strip()]
    if lines:
        # Show last 3 lines max
        for line in lines[-3:]:
            tracker.print(f"[dim]    {line[:200]}[/dim]")


def _ensure_ollama_ready(tracker: InstallProgress) -> None:
    """Ensure Ollama service is running with retries."""
    import time

    # First check if already running
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            tracker.print("[green]  ✓ Ollama 服务已就绪[/green]")
            return
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Start the service
    tracker.update_description("启动 Ollama 服务...")
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait with retries (up to 15 seconds)
    for i in range(15):
        time.sleep(1)
        tracker.update_description(f"等待 Ollama 就绪... ({i + 1}s)")
        try:
            result = subprocess.run(
                ["ollama", "list"], capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                tracker.print("[green]  ✓ Ollama 服务已就绪[/green]")
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    tracker.print("[yellow]  ⚠ Ollama 服务可能未完全就绪，继续尝试...[/yellow]")


def _is_docker_ready() -> bool:
    """Check if Docker daemon is running and responsive."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _is_docker_installed() -> bool:
    """Check if Docker is installed (but maybe not running).

    On macOS, checks /Applications/Docker.app.
    Also checks if ``docker`` CLI is on PATH.
    """
    if shutil.which("docker"):
        return True
    if platform.system().lower() == "darwin":
        from pathlib import Path
        return Path("/Applications/Docker.app").exists()
    return False


def _launch_docker_desktop(tracker: InstallProgress) -> None:
    """Launch Docker Desktop and wait for it to be ready."""
    import time

    system = platform.system().lower()
    if system == "darwin":
        subprocess.run(["open", "-a", "Docker"], capture_output=True)
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
                ["docker", "info"], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                tracker.print("[green]  ✓ Docker 已就绪[/green]")
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    tracker.print("[yellow]  ⚠ Docker 未能在 60s 内就绪，请手动启动[/yellow]")


def _ollama_install_cmd() -> list[str]:
    """Return the install command for Ollama on the current platform."""
    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        return ["brew", "install", "ollama"]
    if system == "linux":
        return ["sh", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"]
    # Fallback — will likely fail, wizard prints manual instructions
    return ["ollama", "--version"]


def _docker_install_cmd() -> list[str]:
    """Return the install command for Docker on the current platform."""
    system = platform.system().lower()
    if system == "darwin" and shutil.which("brew"):
        return ["brew", "install", "--cask", "docker"]
    if system == "linux":
        return ["sh", "-c", "curl -fsSL https://get.docker.com | sh"]
    return ["docker", "--version"]


def _start_qdrant_container(port: int, data_path: str = "~/.local/share/agent-mem0") -> bool:
    """Create and start the Qdrant Docker container with volume mapping."""
    from pathlib import Path
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
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True

    # Container name conflict — try restart
    if "already in use" in result.stderr:
        restart = subprocess.run(
            ["docker", "start", "agent-mem0-qdrant"],
            capture_output=True, text=True,
        )
        return restart.returncode == 0

    return False


def _detect_embedding_dims(embedder_config: dict) -> int:
    """Detect embedding dimensions by calling the model with a test input."""
    provider = embedder_config.get("provider", "ollama")
    model = embedder_config.get("model", "nomic-embed-text")

    try:
        if provider == "ollama":
            import ollama
            base_url = embedder_config.get("base_url", "http://localhost:11434")
            client = ollama.Client(host=base_url)
            resp = client.embed(model=model, input="dimension probe")
            embeddings = resp.get("embeddings", [[]])
            if embeddings and embeddings[0]:
                return len(embeddings[0])

        elif provider in ("openai", "litellm"):
            import urllib.request
            import json as _json
            base_url = embedder_config.get("base_url", "https://api.openai.com/v1")
            api_key = embedder_config.get("api_key", "")
            url = f"{base_url.rstrip('/')}/embeddings"
            payload = _json.dumps({"model": model, "input": "dimension probe"}).encode()
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
    _KNOWN_DIMS = {
        "text-embedding-3-large": 3072,
        "text-embedding-3-small": 1536,
        "text-embedding-ada-002": 1536,
        "nomic-embed-text": 768,
    }
    # Strip provider prefix for lookup (e.g., "azure_openai/text-embedding-3-large")
    model_name = model.split("/")[-1] if "/" in model else model
    if model_name in _KNOWN_DIMS:
        return _KNOWN_DIMS[model_name]

    if provider in ("openai", "litellm"):
        return 1536
    return 768
