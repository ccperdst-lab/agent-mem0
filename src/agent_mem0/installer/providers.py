"""Interactive provider configuration (LLM and Embedder selection)."""

from __future__ import annotations

from rich.prompt import Prompt

from agent_mem0.installer import ollama
from agent_mem0.installer.output import console

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
        if not ollama.detect():
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
