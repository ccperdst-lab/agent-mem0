"""Project registry: track which projects use agent-mem0."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_mem0.config import CONFIG_DIR

REGISTRY_PATH = CONFIG_DIR / "projects.json"


def load_registry() -> dict[str, Any]:
    """Load the project registry. Returns empty structure if file doesn't exist."""
    if not REGISTRY_PATH.exists():
        return {"projects": {}}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if "projects" not in data:
            data["projects"] = {}
        return data
    except (json.JSONDecodeError, ValueError):
        return {"projects": {}}


def save_registry(registry: dict[str, Any]) -> None:
    """Save the project registry to disk."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def register_project(name: str, path: str | Path) -> None:
    """Register a project in the registry (creates or updates)."""
    registry = load_registry()
    registry["projects"][name] = {
        "path": str(Path(path).resolve()),
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    save_registry(registry)
