"""Configuration management for agent-mem0."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import platformdirs
import yaml

CONFIG_DIR = Path(platformdirs.user_config_dir("agent-mem0"))
DATA_DIR = Path(platformdirs.user_data_dir("agent-mem0"))
LOG_DIR = Path(platformdirs.user_log_dir("agent-mem0"))
CONFIG_PATH = CONFIG_DIR / "config.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "llm": {
        "provider": "ollama",
        "model": "qwen2.5:7b",
        "base_url": "http://localhost:11434",
        "api_key": "",
        # For custom provider: Python class path (e.g., "my_module.MyLLM")
        "custom_class": "",
        "custom_config": {},
    },
    "embedder": {
        "provider": "ollama",
        "model": "nomic-embed-text",
        "base_url": "http://localhost:11434",
        "api_key": "",
        "custom_class": "",
        "custom_config": {},
    },
    "vector_store": {
        "provider": "qdrant",
        "mode": "docker",  # docker | local | external
        "host": "localhost",
        "port": 6333,
        "data_path": str(DATA_DIR),
        "collection_name": "agent_mem0",
        "embedding_model_dims": 768,  # nomic-embed-text=768, openai=1536
    },
    "memory": {
        "default_ttl_days": 30,
        "gc_threshold": 20,
        "search_top_k": 20,
        "search_threshold": 0.3,
        "search_max_results": 10,
        "custom_instructions": (
            "Prefer preserving decision rationale (WHY) over factual descriptions (WHAT). "
            "Preserve timestamps when merging memories. "
            "Do not store generic technical knowledge (e.g., syntax, stdlib APIs)."
        ),
    },
    "reranker": {
        "provider": "none",  # none / sentence_transformer / llm_reranker / cohere / huggingface
        "config": {},
    },
    "log": {
        "level": "info",
        "max_size_mb": 10,
        "max_files": 3,
        "path": str(LOG_DIR / "agent-mem0.log"),
    },
}


def extract_service_hosts(config: dict[str, Any]) -> set[str]:
    """Extract service hostnames from config (LLM base_url, Embedder base_url, Qdrant host)."""
    from urllib.parse import urlparse

    hosts: set[str] = set()

    # LLM base_url
    llm_url = config.get("llm", {}).get("base_url", "")
    if llm_url:
        parsed = urlparse(llm_url)
        if parsed.hostname:
            hosts.add(parsed.hostname)

    # Embedder base_url
    emb_url = config.get("embedder", {}).get("base_url", "")
    if emb_url:
        parsed = urlparse(emb_url)
        if parsed.hostname:
            hosts.add(parsed.hostname)

    # Qdrant host (plain hostname, not a URL)
    qdrant_host = config.get("vector_store", {}).get("host", "")
    if qdrant_host:
        hosts.add(qdrant_host)

    return hosts


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def setup_no_proxy(config: dict[str, Any]) -> None:
    """Append local service hosts to NO_PROXY env var (deduplicated, non-destructive)."""
    hosts = extract_service_hosts(config)
    local_hosts = hosts & _LOCAL_HOSTS
    if not local_hosts:
        return

    existing = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
    existing_set = {h.strip() for h in existing.split(",") if h.strip()}

    to_add = local_hosts - existing_set
    if not to_add:
        return

    combined = f"{existing},{','.join(sorted(to_add))}" if existing else ",".join(sorted(to_add))
    os.environ["NO_PROXY"] = combined
    os.environ["no_proxy"] = combined


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _expand_paths(config: dict) -> dict:
    """Expand ~ in path-like string values."""
    result = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = _expand_paths(value)
        elif isinstance(value, str) and "~" in value:
            result[key] = str(Path(value).expanduser())
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    """Load config from file, merge with defaults, expand paths."""
    user_config: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                user_config = loaded

    merged = _deep_merge(DEFAULT_CONFIG, user_config)
    return _expand_paths(merged)


def save_config(config: dict[str, Any]) -> None:
    """Save config to file (legacy yaml.dump, used for programmatic updates)."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _find_template_path() -> Path:
    """Locate config.yaml.template relative to the package."""
    # When installed as a package, templates/ is alongside src/
    pkg_dir = Path(__file__).resolve().parent  # agent_mem0/
    # Try: package_root/templates/
    for candidate in [
        pkg_dir.parent.parent / "templates",  # src/../templates (dev)
    ]:
        template = candidate / "config.yaml.template"
        if template.exists():
            return template
    raise FileNotFoundError("config.yaml.template not found")


def save_config_from_template(overrides: dict[str, dict[str, Any]]) -> None:
    """Generate config.yaml from template by uncommenting override lines.

    Args:
        overrides: Nested dict of {section: {key: value}} to uncomment and set.
                   Example: {"llm": {"provider": "litellm", "base_url": "https://..."}}
    """
    template_path = _find_template_path()
    template = template_path.read_text(encoding="utf-8")

    lines = template.splitlines()
    result: list[str] = []
    current_section: str | None = None

    for line in lines:
        stripped = line.lstrip("# ").strip()

        # Detect section headers like "# llm:" or "# vector_store:"
        if stripped.rstrip(":") in ("llm", "embedder", "vector_store", "memory", "log"):
            candidate_section = stripped.rstrip(":")
            if candidate_section in overrides:
                current_section = candidate_section
                result.append(f"{candidate_section}:")
                continue
            else:
                current_section = None
                result.append(line)
                continue

        # Inside an active section, try to match "key: value" lines
        if current_section and line.startswith("#   ") and ":" in stripped:
            parts = stripped.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                if key in overrides.get(current_section, {}):
                    value = overrides[current_section][key]
                    # Format the value
                    if isinstance(value, str):
                        # Quote strings that contain special chars or are empty
                        if not value or any(c in value for c in ":#{}[]&*?|>!%@`"):
                            value_str = f'"{value}"'
                        else:
                            value_str = value
                    else:
                        value_str = str(value)
                    result.append(f"  {key}: {value_str}")
                    continue

        # Check if we've left the current section (non-comment, non-empty, not indented)
        if current_section and line and not line.startswith("#") and not line.startswith(" "):
            current_section = None

        result.append(line)

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text("\n".join(result) + "\n", encoding="utf-8")


def build_mem0_config(config: dict[str, Any], project: str) -> dict[str, Any]:
    """Build mem0-compatible config dict from our config."""
    llm_cfg = config["llm"]
    embedder_cfg = config["embedder"]
    vs_cfg = config["vector_store"]

    mem0_config: dict[str, Any] = {}

    # LLM config
    provider = llm_cfg["provider"]
    if provider == "custom":
        # Custom provider handled separately at initialization
        pass
    else:
        # mem0 doesn't support custom base_url for litellm LLM provider,
        # so we map litellm -> openai with openai_base_url for compatibility.
        mem0_llm_provider = "openai" if provider == "litellm" else provider
        llm_section: dict[str, Any] = {"provider": mem0_llm_provider, "config": {"model": llm_cfg["model"]}}
        if provider == "ollama":
            llm_section["config"]["ollama_base_url"] = llm_cfg["base_url"]
        elif provider in ("openai", "litellm"):
            if llm_cfg.get("api_key"):
                llm_section["config"]["api_key"] = llm_cfg["api_key"]
            if llm_cfg.get("base_url"):
                llm_section["config"]["openai_base_url"] = llm_cfg["base_url"]
        elif provider == "anthropic":
            if llm_cfg.get("api_key"):
                llm_section["config"]["api_key"] = llm_cfg["api_key"]
        mem0_config["llm"] = llm_section

    # Embedder config
    # Note: mem0 doesn't support "litellm" as embedder provider,
    # so we map litellm -> openai with openai_base_url for compatibility.
    emb_provider = embedder_cfg["provider"]
    if emb_provider == "custom":
        pass
    else:
        mem0_emb_provider = "openai" if emb_provider == "litellm" else emb_provider
        emb_section: dict[str, Any] = {"provider": mem0_emb_provider, "config": {"model": embedder_cfg["model"]}}
        if emb_provider == "ollama":
            emb_section["config"]["ollama_base_url"] = embedder_cfg["base_url"]
        elif emb_provider in ("openai", "litellm"):
            if embedder_cfg.get("api_key"):
                emb_section["config"]["api_key"] = embedder_cfg["api_key"]
            if embedder_cfg.get("base_url"):
                emb_section["config"]["openai_base_url"] = embedder_cfg["base_url"]
        mem0_config["embedder"] = emb_section

    # Vector store config
    vs_section: dict[str, Any] = {
        "provider": "qdrant",
        "config": {
            "collection_name": vs_cfg["collection_name"],
            "embedding_model_dims": vs_cfg.get("embedding_model_dims", 768),
        },
    }
    if vs_cfg["mode"] in ("docker", "external"):
        vs_section["config"]["host"] = vs_cfg["host"]
        vs_section["config"]["port"] = vs_cfg["port"]
    else:  # local
        data_path = Path(vs_cfg.get("data_path", str(DATA_DIR))).expanduser()
        vs_section["config"]["path"] = str(data_path / "qdrant_storage")
    mem0_config["vector_store"] = vs_section

    # Custom instructions for mem0 memory extraction
    mem_cfg = config.get("memory", {})
    custom_instructions = mem_cfg.get("custom_instructions", "")
    if custom_instructions:
        mem0_config["custom_instructions"] = custom_instructions

    # Reranker config passthrough to mem0
    reranker_cfg = config.get("reranker", {})
    reranker_provider = reranker_cfg.get("provider", "none")
    if reranker_provider != "none":
        reranker_inner = dict(reranker_cfg.get("config", {}) or {})
        # LLM inheritance: when llm_reranker has no explicit LLM config, inherit from main
        if reranker_provider == "llm_reranker" and "provider" not in reranker_inner:
            reranker_inner.setdefault("provider", llm_cfg["provider"])
            reranker_inner.setdefault("model", llm_cfg["model"])
            if llm_cfg.get("api_key"):
                reranker_inner.setdefault("api_key", llm_cfg["api_key"])
        mem0_config["reranker"] = {
            "provider": reranker_provider,
            "config": reranker_inner,
        }

    return mem0_config
