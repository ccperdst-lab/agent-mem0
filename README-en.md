# agent-mem0

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/agent-mem0.svg)](https://pypi.org/project/agent-mem0/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

[中文文档](README.md)

**Cross-session memory for Claude Code.**

Every Claude Code conversation starts from scratch — it doesn't remember your preferences, technical decisions, or project context. agent-mem0 injects persistent memory via an MCP Server, allowing Claude to carry context across sessions.

## Architecture

```mermaid
graph LR
    CC[Claude Code] <-->|MCP / stdio| MCP[MCP Server]
    MCP --> mem0[mem0]
    mem0 --> LLM[LLM<br/>Memory extraction<br/>& conflict detection]
    mem0 --> EMB[Embedder<br/>Text vectorization]
    mem0 --> QD[Qdrant<br/>Vector storage]
```

**How it works:**
- **mem0** handles semantic understanding of memories — extracting key information, detecting conflicts between old and new memories, and automatically merging updates
- **LLM** provides semantic capabilities for mem0 (e.g., recognizing that "user likes pytest" and "user prefers pytest framework" are the same memory)
- **Embedder** converts text into vectors for similarity search in Qdrant
- **Qdrant** stores and retrieves memory vectors, supporting Docker, pure local, and external connection modes

## Quick Start

### Prerequisites

- Python 3.10+
- Docker (recommended, for running Qdrant) or use pure local mode
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

### 1. Install

```bash
pip install agent-mem0
```

Or install from source:

```bash
git clone https://github.com/ccperdst-lab/agent-mem0.git
cd agent-mem0
pip install -e .
```

### 2. Global Setup (one-time)

**Interactive wizard:**

```bash
agent-mem0 install
```

The wizard will guide you through:
- Choosing an LLM Provider (Ollama / OpenAI / Anthropic / LiteLLM)
- Choosing an Embedding Provider (Ollama / OpenAI / LiteLLM)
- Configuring Qdrant storage mode (Docker / Local / External)
- Auto-detecting and installing Ollama, Docker (if needed)
- Pulling required models and images
- Writing config file and CLAUDE.md memory rules

**Non-interactive mode (CI/automation):**

```bash
# Use recommended preset (auto-detects hardware to choose models)
agent-mem0 install --default

# Specify a preset
agent-mem0 install --default --preset cloud --api-key "sk-..."
```

Available presets: `recommended` (auto-select), `light` (lightweight local), `cloud` (cloud API).

### 3. Project Setup (once per project)

```bash
cd your-project
agent-mem0 setup
```

This creates in your project directory:
- `.mcp.json` — MCP Server config for Claude Code
- `.claude/skills/agent-memory/` — `/agent-memory:init` Skill

### 4. Start Using

Launch Claude Code and the memory system takes effect automatically. On first use, run:

```
/agent-memory:init
```

This generates project-level context (CLAUDE.md) to help Claude better understand your project.

## Features

### Cross-Session Memory

Claude automatically remembers your preferences, technical decisions, and project context. Relevant memories are retrieved at the start of each new session — no need to repeat background information.

### Project Isolation + Global Sharing

Each project's memories are isolated from one another, while global memories (personal preferences, general rules) are shared. During search, project and global memories are ranked together by relevance score — no artificial caps on either source.

### Smart Memory Management

- **Scene-driven tool selection**: 5 mandatory rules ensure Claude uses the right memory tool at the right time
- **Conflict detection**: When modifying existing architecture/decisions, automatically searches and updates related memories instead of creating duplicates
- **Search pipeline**: Wide candidate retrieval → relevance threshold filtering → TTL filtering → score sorting → truncation
- **Optional reranking**: Supports Reranker (sentence-transformer / LLM / Cohere) for secondary ranking after vector retrieval

### Multiple Provider Support

| Type | Available Providers |
|------|-------------------|
| LLM | Ollama, OpenAI, Anthropic, LiteLLM |
| Embedder | Ollama, OpenAI, LiteLLM |
| Vector Store | Qdrant (Docker / Local / External) |
| Reranker | sentence-transformer, LLM, Cohere, HuggingFace (optional) |

### Async Writes & Auto GC

Memory writes are executed asynchronously via a background queue, never blocking Claude's responses. Expired memories (beyond TTL) are automatically flagged during search and batch-deleted when the threshold is reached.

### Memory Rule Injection

During installation, 5 mandatory memory rules are written to `~/.claude/CLAUDE.md`, covering all 6 tools (search / add / update / delete / list / history), ensuring Claude proactively manages memories in every session.

## MCP Tools

After installation, Claude Code can operate on memories through these MCP tools:

| Tool | Description | Key Parameters |
|------|-------------|---------------|
| `memory_search` | Semantic memory search | `query`, `project`, `days`, `top_k` |
| `memory_add` | Add memory (auto dedup & merge) | `text`, `project`, `metadata` |
| `memory_update` | Update existing memory content | `memory_id`, `text` |
| `memory_delete` | Delete a specific memory | `memory_id` |
| `memory_list` | List all memories | `project`, `days` |
| `memory_history` | View memory change history | `memory_id` |

> These tools are called automatically by Claude based on memory rules — you typically don't need to invoke them manually.

## Configuration

Config file location varies by platform:

| Platform | Config Directory | Data Directory | Log Directory |
|----------|-----------------|----------------|---------------|
| macOS | `~/Library/Application Support/agent-mem0/` | Same as config | `~/Library/Logs/agent-mem0/` |
| Linux | `~/.config/agent-mem0/` | `~/.local/share/agent-mem0/` | `~/.local/state/agent-mem0/log/` |
| Windows | `%APPDATA%\agent-mem0\` | `%LOCALAPPDATA%\agent-mem0\` | `%LOCALAPPDATA%\agent-mem0\Logs\` |

Uses a **shadow config** approach: the code has built-in defaults for all fields, and the user config file only needs to specify the fields you want to override.

### Common Scenarios

**Using OpenAI:**

```yaml
llm:
  provider: openai
  model: gpt-4o-mini
  api_key: "sk-..."

embedder:
  provider: openai
  model: text-embedding-3-small
  api_key: "sk-..."
```

**Using Ollama (local deployment, no API key needed):**

```yaml
llm:
  provider: ollama
  model: qwen2.5:7b
  base_url: http://localhost:11434

embedder:
  provider: ollama
  model: nomic-embed-text
  base_url: http://localhost:11434
```

**Using LiteLLM proxy (e.g., Azure OpenAI):**

```yaml
llm:
  provider: litellm
  model: azure_openai/gpt-4o
  base_url: https://your-litellm-proxy.com
  api_key: "your-key"
```

**Tuning search parameters:**

```yaml
memory:
  search_top_k: 20        # Candidates per search call
  search_threshold: 0.3   # Relevance threshold (0 = no filtering)
  search_max_results: 10  # Max entries returned
  default_ttl_days: 30    # Memory retention period in days
```

**Enable Reranker (optional):**

```yaml
reranker:
  provider: sentence_transformer
  config:
    model: cross-encoder/ms-marco-MiniLM-L-6-v2
    top_k: 10
```

Requires extra install: `pip install agent-mem0[reranker]`

## CLI Commands

| Command | Description |
|---------|-------------|
| `agent-mem0 install` | Global install wizard: configure providers, storage, memory rules |
| `agent-mem0 install --default` | Non-interactive mode: auto-detect hardware, use recommended config |
| `agent-mem0 setup` | Project-level setup: write MCP config and Skill |
| `agent-mem0 status` | Show system status: Qdrant connection, provider config, memory stats |
| `agent-mem0 uninstall` | Uninstall: remove config and artifacts, preserve memory data |
| `agent-mem0 uninstall --purge` | Full uninstall: also delete memory data and Docker container |

## FAQ

**Q: Qdrant connection failed**

Check if Docker is running:
```bash
docker ps | grep qdrant
# If not running:
docker start agent-mem0-qdrant
```

Or switch to local mode (no Docker needed):
```yaml
vector_store:
  mode: local
```

**Q: Ollama model pull failed**

Confirm Ollama service is running:
```bash
ollama list
# If not running:
ollama serve
```

**Q: Connection fails behind a proxy**

agent-mem0 automatically adds local service addresses (localhost, etc.) to `NO_PROXY`. If issues persist, set it manually:
```bash
export NO_PROXY=localhost,127.0.0.1
```

**Q: How to check current status?**

```bash
agent-mem0 status
```

Shows Qdrant connection status, provider config, registered projects, and memory statistics.

## License

[Apache-2.0](LICENSE)
