"""End-to-end test: memory CRUD via mem0 + Qdrant."""

from __future__ import annotations

import json
import sys
import time

from agent_mem0.config import build_mem0_config, load_config


def main() -> None:
    config = load_config()
    project = "e2e-test"
    mem0_config = build_mem0_config(config, project)

    print(f"mem0 config: {json.dumps(mem0_config, default=str)}")

    from mem0 import Memory

    memory = Memory.from_config(mem0_config)
    print("✓ mem0 initialized")

    # ── ADD ──────────────────────────────────────────────────────
    print("\n--- Test: memory_add ---")
    result = memory.add(
        "The user prefers pytest over unittest for testing",
        user_id=project,
        metadata={"project": project, "updated_at": "2099-01-01T00:00:00+00:00"},
    )
    print(f"  add result: {json.dumps(result, default=str)}")

    # Extract memory ID
    mem_id = None
    if isinstance(result, dict) and "results" in result:
        for r in result["results"]:
            if r.get("id"):
                mem_id = r["id"]
                break
    assert mem_id, f"Failed to get memory ID from add result: {result}"
    print(f"  ✓ memory added: {mem_id}")

    # Give mem0 a moment to index
    time.sleep(2)

    # ── SEARCH ───────────────────────────────────────────────────
    print("\n--- Test: memory_search ---")
    search_results = memory.search(
        "what testing framework does the user prefer",
        filters={"user_id": project},
        top_k=5,
    )
    if isinstance(search_results, dict) and "results" in search_results:
        results = search_results["results"]
    elif isinstance(search_results, list):
        results = search_results
    else:
        results = []

    print(f"  search returned {len(results)} results")
    assert len(results) > 0, "Search returned no results"

    found = any("pytest" in r.get("memory", "").lower() for r in results)
    assert found, f"Expected 'pytest' in results: {results}"
    print("  ✓ search found the memory")

    # Check score field exists
    if results and "score" in results[0]:
        print(f"  ✓ score field present: {results[0]['score']}")

    # ── LIST ─────────────────────────────────────────────────────
    print("\n--- Test: memory_list (get_all) ---")
    all_mems = memory.get_all(filters={"user_id": project})
    if isinstance(all_mems, dict) and "results" in all_mems:
        all_list = all_mems["results"]
    elif isinstance(all_mems, list):
        all_list = all_mems
    else:
        all_list = []

    print(f"  get_all returned {len(all_list)} memories")
    assert len(all_list) > 0, "get_all returned no memories"
    print("  ✓ list OK")

    # ── DELETE ───────────────────────────────────────────────────
    print("\n--- Test: memory_delete ---")
    memory.delete(mem_id)
    print(f"  ✓ memory deleted: {mem_id}")

    # Verify deletion
    time.sleep(1)
    after_delete = memory.get_all(filters={"user_id": project})
    if isinstance(after_delete, dict) and "results" in after_delete:
        remaining = after_delete["results"]
    elif isinstance(after_delete, list):
        remaining = after_delete
    else:
        remaining = []

    remaining_ids = [m.get("id") for m in remaining]
    assert mem_id not in remaining_ids, f"Memory {mem_id} still exists after delete"
    print("  ✓ deletion verified")

    # ── DONE ─────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("All E2E tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ E2E test failed: {e}", file=sys.stderr)
        sys.exit(1)
