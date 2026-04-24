"""Provider detection, installation, and configuration."""

from __future__ import annotations

import platform
import shutil
import subprocess

from rich.console import Console
from rich.prompt import Confirm, Prompt

console = Console()

LLM_PROVIDERS = ["ollama", "openai", "anthropic", "litellm", "custom"]
EMBEDDER_PROVIDERS = ["ollama", "openai", "litellm", "custom"]

DEFAULT_LLM_MODELS: dict[str, str] = {
    "ollama": "qwen2.5:7b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "litellm": "openai/your-model",
}

DEFAULT_EMBEDDER_MODELS: dict[str, str] = {
    "ollama": "nomic-embed-text",
    "openai": "text-embedding-3-small",
    "litellm": "openai/your-embedding-model",
}


def detect_ollama() -> bool:
    """Check if Ollama is installed and running."""
    return shutil.which("ollama") is not None


def install_ollama() -> bool:
    """Install Ollama based on OS and architecture."""
    system = platform.system().lower()
    arch = platform.machine().lower()

    console.print(f"\n[yellow]检测到系统: {system} ({arch})[/yellow]")

    if system == "darwin":
        if shutil.which("brew"):
            console.print("[cyan]通过 Homebrew 安装 Ollama...[/cyan]")
            result = subprocess.run(["brew", "install", "ollama"], capture_output=True, text=True)
            if result.returncode == 0:
                console.print("[green]✓ Ollama 安装成功[/green]")
                return True
        console.print("[yellow]请从 https://ollama.ai 下载安装 Ollama[/yellow]")
        return False

    elif system == "linux":
        console.print("[cyan]通过官方脚本安装 Ollama...[/cyan]")
        result = subprocess.run(
            ["sh", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("[green]✓ Ollama 安装成功[/green]")
            return True
        console.print(f"[red]安装失败: {result.stderr}[/red]")
        return False

    else:
        console.print(f"[yellow]不支持自动安装 Ollama on {system}，请手动安装: https://ollama.ai[/yellow]")
        return False


def pull_ollama_model(model: str) -> bool:
    """Pull an Ollama model."""
    console.print(f"[cyan]拉取模型 {model}...[/cyan]")
    result = subprocess.run(["ollama", "pull", model], capture_output=False)
    if result.returncode == 0:
        console.print(f"[green]✓ 模型 {model} 就绪[/green]")
        return True
    console.print(f"[red]模型拉取失败，请手动运行: ollama pull {model}[/red]")
    return False


def ensure_ollama_running() -> bool:
    """Ensure Ollama service is running."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        console.print("[yellow]Ollama 服务未运行，尝试启动...[/yellow]")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import time
        time.sleep(2)
        return True


def configure_llm_provider() -> dict:
    """Interactive LLM provider configuration."""
    console.print("\n[bold]选择 LLM Provider[/bold]（用于记忆提取和冲突判断）")
    for i, p in enumerate(LLM_PROVIDERS):
        default_mark = " [green](默认)[/green]" if p == "ollama" else ""
        console.print(f"  {i + 1}. {p}{default_mark}")

    choice = Prompt.ask("选择", default="1")
    try:
        idx = int(choice) - 1
        provider = LLM_PROVIDERS[idx]
    except (ValueError, IndexError):
        provider = "ollama"

    config: dict = {"provider": provider}

    if provider == "ollama":
        if not detect_ollama():
            console.print("[yellow]未检测到 Ollama，将在后续步骤中自动安装[/yellow]")
        config["model"] = Prompt.ask("LLM 模型", default=DEFAULT_LLM_MODELS["ollama"])
        config["base_url"] = Prompt.ask("Ollama 地址", default="http://localhost:11434")

    elif provider in ("openai", "anthropic"):
        config["model"] = Prompt.ask("模型名称", default=DEFAULT_LLM_MODELS.get(provider, ""))
        config["api_key"] = Prompt.ask("API Key", password=True)

    elif provider == "litellm":
        config["model"] = Prompt.ask("模型名称 (例: openai/your-model)", default="openai/your-model")
        config["base_url"] = Prompt.ask("API Base URL")
        api_key = Prompt.ask("API Key (可选，留空跳过)", default="", password=True)
        if api_key:
            config["api_key"] = api_key

    elif provider == "custom":
        config["custom_class"] = Prompt.ask("Python 类路径 (例: my_module.MyLLM)")
        console.print("[dim]自定义配置可在 config.yaml 的 llm.custom_config 中设置[/dim]")

    return config


def configure_embedder_provider() -> dict:
    """Interactive Embedder provider configuration."""
    console.print("\n[bold]选择 Embedding Provider[/bold]（用于记忆向量化）")
    for i, p in enumerate(EMBEDDER_PROVIDERS):
        default_mark = " [green](默认)[/green]" if p == "ollama" else ""
        console.print(f"  {i + 1}. {p}{default_mark}")

    choice = Prompt.ask("选择", default="1")
    try:
        idx = int(choice) - 1
        provider = EMBEDDER_PROVIDERS[idx]
    except (ValueError, IndexError):
        provider = "ollama"

    config: dict = {"provider": provider}

    if provider == "ollama":
        config["model"] = Prompt.ask("Embedding 模型", default=DEFAULT_EMBEDDER_MODELS["ollama"])
        config["base_url"] = Prompt.ask("Ollama 地址", default="http://localhost:11434")

    elif provider == "openai":
        config["model"] = Prompt.ask("模型名称", default=DEFAULT_EMBEDDER_MODELS["openai"])
        config["api_key"] = Prompt.ask("API Key", password=True)

    elif provider == "litellm":
        config["model"] = Prompt.ask("模型名称", default="openai/your-embedding-model")
        config["base_url"] = Prompt.ask("API Base URL")
        api_key = Prompt.ask("API Key (可选)", default="", password=True)
        if api_key:
            config["api_key"] = api_key

    elif provider == "custom":
        config["custom_class"] = Prompt.ask("Python 类路径 (例: my_module.MyEmbedder)")

    return config


def setup_ollama_models(llm_config: dict, embedder_config: dict) -> None:
    """Pull required Ollama models if provider is Ollama."""
    models_to_pull = set()
    if llm_config.get("provider") == "ollama":
        models_to_pull.add(llm_config.get("model", DEFAULT_LLM_MODELS["ollama"]))
    if embedder_config.get("provider") == "ollama":
        models_to_pull.add(embedder_config.get("model", DEFAULT_EMBEDDER_MODELS["ollama"]))

    if models_to_pull:
        ensure_ollama_running()
        for model in models_to_pull:
            pull_ollama_model(model)
