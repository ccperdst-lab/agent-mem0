"""Timeout wrapper for blocking calls using a shared thread pool."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, TypeVar

T = TypeVar("T")

_executor = ThreadPoolExecutor(max_workers=2)


def call_with_timeout(func: Any, *args: Any, timeout: float, **kwargs: Any) -> Any:
    """Execute *func* in a background thread with a timeout.

    Args:
        func: Callable to execute.
        *args: Positional arguments forwarded to *func*.
        timeout: Maximum seconds to wait.  Must be > 0.
        **kwargs: Keyword arguments forwarded to *func*.

    Returns:
        The return value of *func*.

    Raises:
        TimeoutError: If *func* does not complete within *timeout* seconds.
    """
    future = _executor.submit(func, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeout:
        raise TimeoutError(f"Operation timed out after {timeout:.0f}s")
