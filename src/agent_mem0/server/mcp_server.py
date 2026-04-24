"""MCP Server: mem0-powered memory tools for AI Agent tools."""

from __future__ import annotations

import atexit
import json
import queue
import threading
import time
from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP

from agent_mem0.config import build_mem0_config, load_config
from agent_mem0.logger import (
    log_conflict,
    log_debug,
    log_error,
    log_memory_op,
    setup_logger,
)

# Globals initialized in run_server()
_memory = None
_locked_project: str = ""
_default_ttl_days: int = 30
_mcp = FastMCP("agent-memory")
_write_worker: _WriteWorker | None = None
_gc_buffer: _GCBuffer | None = None


class _WriteWorker:
    """Single background daemon thread + queue for async write operations."""

    def __init__(self, base_delay: float = 1.0, factor: float = 2.0, max_retries: int = 3) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._base_delay = base_delay
        self._factor = factor
        self._max_retries = max_retries
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue(self, func, *args, **kwargs) -> None:
        """Add a write operation to the queue."""
        self._queue.put((func, args, kwargs))

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    def _run(self) -> None:
        """Worker loop: process queued tasks with exponential backoff retry."""
        while True:
            func, args, kwargs = self._queue.get()
            delay = self._base_delay
            for attempt in range(1, self._max_retries + 1):
                try:
                    func(*args, **kwargs)
                    if attempt > 1:
                        log_memory_op("WRITE_RETRY_OK", _locked_project,
                                      f"succeeded on attempt {attempt}")
                    break
                except Exception as e:
                    if attempt < self._max_retries:
                        log_error(f"Write attempt {attempt}/{self._max_retries} failed: {e}, "
                                  f"retrying in {delay:.0f}s")
                        time.sleep(delay)
                        delay *= self._factor
                    else:
                        log_error(f"Write failed after {self._max_retries} attempts: {e}")
            self._queue.task_done()


class _GCBuffer:
    """Thread-safe buffer for collecting expired memory IDs and flushing when threshold is reached."""

    def __init__(self, threshold: int = 20) -> None:
        self._lock = threading.Lock()
        self._ids: list[str] = []
        self._threshold = threshold

    def add(self, ids: list[str]) -> None:
        """Add expired memory IDs to the buffer."""
        if not ids:
            return
        with self._lock:
            self._ids.extend(ids)

    def flush_if_ready(self) -> list[str]:
        """Return and clear buffered IDs if threshold is reached, else return empty list."""
        with self._lock:
            if len(self._ids) < self._threshold:
                return []
            flushed = self._ids[:]
            self._ids.clear()
            return flushed


def _check_project(project: str) -> str | None:
    """Validate project access. Returns error message or None if OK."""
    allowed = {_locked_project, "global"}
    if project not in allowed:
        msg = f"Access denied: project '{project}' not in allowed list {allowed}"
        log_error(msg)
        return msg
    return None


def _filter_by_time(memories: list[dict], days: int) -> tuple[list[dict], list[str]]:
    """Filter memories by updated_at within the last N days.

    Returns:
        (valid_memories, expired_ids) — valid memories to return, and IDs of expired ones for GC.
    """
    if days <= 0:
        return memories, []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.isoformat()
    filtered = []
    expired_ids = []
    for m in memories:
        meta = m.get("metadata", {}) or {}
        updated = meta.get("updated_at", "")
        # If no timestamp, include it (legacy data)
        if not updated or updated >= cutoff_str:
            filtered.append(m)
        else:
            expired_ids.append(m.get("id", ""))
    # Remove empty IDs
    expired_ids = [i for i in expired_ids if i]
    return filtered, expired_ids


@_mcp.tool()
def memory_search(query: str, project: str = "", days: int = 0) -> str:
    """搜索记忆。默认搜索当前项目和全局记忆。

    Args:
        query: 搜索关键词或语义描述
        project: 项目名（默认为当前项目，也可指定 "global" 只搜全局）
        days: 时间过滤，只返回最近 N 天的记忆（默认使用配置的 TTL）
    """
    if not project:
        project = _locked_project

    error = _check_project(project)
    if error:
        return json.dumps({"error": error}, ensure_ascii=False)

    if days <= 0:
        days = _default_ttl_days

    start = time.time()
    try:
        results = []
        # Search within the specified project
        project_results = _memory.search(query, filters={"user_id": project}, top_k=10)
        if isinstance(project_results, dict) and "results" in project_results:
            results.extend(project_results["results"])
        elif isinstance(project_results, list):
            results.extend(project_results)

        # Also search global if project is not global
        if project != "global":
            global_results = _memory.search(query, filters={"user_id": "global"}, top_k=5)
            if isinstance(global_results, dict) and "results" in global_results:
                results.extend(global_results["results"])
            elif isinstance(global_results, list):
                results.extend(global_results)

        results, expired_ids = _filter_by_time(results, days)

        # Feed expired IDs to GC buffer
        if expired_ids and _gc_buffer is not None:
            _gc_buffer.add(expired_ids)
            log_debug(f"GC buffer: added {len(expired_ids)} expired IDs")
            to_delete = _gc_buffer.flush_if_ready()
            if to_delete and _write_worker is not None:
                log_memory_op("GC_TRIGGER", project, f"flushing {len(to_delete)} expired memories")
                _write_worker.enqueue(_do_gc_delete, to_delete)

        elapsed = time.time() - start
        log_memory_op("SEARCH", project, f"query=\"{query}\" results={len(results)} time={elapsed:.2f}s")
        log_debug(f"Search details: query=\"{query}\" project={project} days={days} raw={json.dumps(results, ensure_ascii=False, default=str)}")

        # Return compact format: only fields Claude needs
        compact = [{"id": r["id"], "memory": r.get("memory", ""), "project": r.get("user_id", "")} for r in results]
        return json.dumps({"memories": compact, "count": len(compact)}, ensure_ascii=False)
    except Exception as e:
        log_error(f"Search failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _do_gc_delete(ids: list[str]) -> None:
    """Batch delete expired memories, executed in background worker."""
    deleted = 0
    failed = 0
    for mid in ids:
        try:
            _memory.delete(mid)
            deleted += 1
        except Exception as e:
            log_error(f"GC delete failed for {mid}: {e}")
            failed += 1
    log_memory_op("GC_COMPLETE", _locked_project,
                  f"deleted={deleted} failed={failed} total={len(ids)}")


def _do_memory_add(text: str, project: str, meta: dict) -> None:
    """Actual memory write operation, executed in background worker."""
    start = time.time()
    result = _memory.add(text, user_id=project, metadata=meta)
    elapsed = time.time() - start

    # Log the operation and any conflicts
    events = []
    if isinstance(result, dict) and "results" in result:
        for r in result["results"]:
            event = r.get("event", "UNKNOWN")
            events.append(event)
            if event == "UPDATE":
                old_mem = r.get("previous_memory", "")
                new_mem = r.get("memory", text)
                log_conflict(old_mem, new_mem, "UPDATE")

    event_str = ",".join(events) if events else "ADD"
    log_memory_op("ADD", project, f"text=\"{text[:50]}...\" events={event_str} time={elapsed:.2f}s")
    log_debug(f"Add details: project={project} metadata={meta}")


@_mcp.tool()
def memory_add(text: str, project: str = "", metadata: dict | None = None) -> str:
    """添加一条记忆。mem0 会自动处理冲突（更新已有的相似记忆）。写入在后台异步完成。

    Args:
        text: 要记忆的内容
        project: 项目名（当前项目名或 "global"）
        metadata: 额外的元数据
    """
    if not project:
        project = _locked_project

    error = _check_project(project)
    if error:
        return json.dumps({"error": error}, ensure_ascii=False)

    now = datetime.now(timezone.utc).isoformat()
    meta = metadata or {}
    meta.update({
        "project": project,
        "updated_at": now,
    })
    if "created_at" not in meta:
        meta["created_at"] = now

    # Enqueue to background worker, return immediately
    _write_worker.enqueue(_do_memory_add, text, project, meta)
    log_debug(f"Write enqueued: project={project} text=\"{text[:50]}...\"")

    return json.dumps({"status": "accepted"}, ensure_ascii=False)


@_mcp.tool()
def memory_list(project: str = "", days: int = 0) -> str:
    """列出记忆。默认列出当前项目和全局记忆。

    Args:
        project: 项目名（留空列出当前项目+全局）
        days: 时间过滤，只返回最近 N 天的记忆（默认使用配置的 TTL）
    """
    if not project:
        project = _locked_project

    error = _check_project(project)
    if error and project != "":
        return json.dumps({"error": error}, ensure_ascii=False)

    if days <= 0:
        days = _default_ttl_days

    try:
        results = []

        project_mems = _memory.get_all(filters={"user_id": project})
        if isinstance(project_mems, dict) and "results" in project_mems:
            results.extend(project_mems["results"])
        elif isinstance(project_mems, list):
            results.extend(project_mems)

        if project != "global":
            global_mems = _memory.get_all(filters={"user_id": "global"})
            if isinstance(global_mems, dict) and "results" in global_mems:
                results.extend(global_mems["results"])
            elif isinstance(global_mems, list):
                results.extend(global_mems)

        results, _expired = _filter_by_time(results, days)
        # Sort by updated_at descending
        results.sort(
            key=lambda m: (m.get("metadata") or {}).get("updated_at", ""),
            reverse=True,
        )

        log_memory_op("LIST", project, f"count={len(results)} days={days}")

        compact = [{"id": r["id"], "memory": r.get("memory", ""), "project": r.get("user_id", "")} for r in results]
        return json.dumps({"memories": compact, "count": len(compact)}, ensure_ascii=False)
    except Exception as e:
        log_error(f"List failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@_mcp.tool()
def memory_delete(memory_id: str) -> str:
    """删除一条记忆。

    Args:
        memory_id: 记忆的 ID
    """
    try:
        _memory.delete(memory_id)
        log_memory_op("DELETE", _locked_project, f"id={memory_id}")
        return json.dumps({"status": "deleted", "memory_id": memory_id}, ensure_ascii=False)
    except Exception as e:
        log_error(f"Delete failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def run_server(project: str) -> None:
    """Initialize and run the MCP Server."""
    global _memory, _locked_project, _default_ttl_days, _write_worker, _gc_buffer

    config = load_config()
    setup_logger(config)

    _locked_project = project
    _default_ttl_days = config.get("memory", {}).get("default_ttl_days", 30)
    gc_threshold = config.get("memory", {}).get("gc_threshold", 20)

    log_debug(f"Starting MCP Server: project={project}")

    # Build mem0 config and initialize
    mem0_config = build_mem0_config(config, project)

    from mem0 import Memory

    _memory = Memory.from_config(mem0_config)

    # Initialize async write worker and GC buffer
    _write_worker = _WriteWorker(base_delay=1.0, factor=2.0, max_retries=3)
    _gc_buffer = _GCBuffer(threshold=gc_threshold)

    def _on_exit():
        pending = _write_worker.pending_count
        if pending > 0:
            log_error(f"WARNING: MCP server exiting with {pending} pending write(s) in queue")

    atexit.register(_on_exit)

    log_debug(f"mem0 initialized with config: {json.dumps(mem0_config, default=str)}")
    log_debug(f"Async write worker started, GC threshold={gc_threshold}")

    # Run MCP server in stdio mode
    _mcp.run(transport="stdio")
