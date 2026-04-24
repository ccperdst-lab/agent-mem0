"""Hardware detection for adaptive install configuration."""

from __future__ import annotations

import os


def detect_ram_gb() -> float:
    """Detect total system RAM in GB using os.sysconf (POSIX).

    Returns 0.0 if detection fails (unsupported platform, permissions, etc.).
    """
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        return (page_size * page_count) / (1024 ** 3)
    except (ValueError, OSError, AttributeError):
        return 0.0


# (model_name, download_size_description)
_RAM_MODEL_MAP: list[tuple[float, str, str]] = [
    (16.0, "qwen2.5:14b", "~9GB"),
    (8.0, "qwen2.5:7b", "~4.7GB"),
    (4.0, "qwen2.5:1.5b", "~1GB"),
    (0.0, "qwen2.5:0.5b", "~400MB"),
]


def recommend_llm_model(ram_gb: float) -> tuple[str, str]:
    """Recommend an LLM model based on available RAM.

    Returns (model_name, download_size_description).
    Falls back to the smallest model if ram_gb <= 0.
    """
    for threshold, model, size in _RAM_MODEL_MAP:
        if ram_gb >= threshold:
            return model, size
    return _RAM_MODEL_MAP[-1][1], _RAM_MODEL_MAP[-1][2]
