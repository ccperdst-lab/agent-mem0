# agent-mem0

Cross-session memory system for AI Agent tools, powered by mem0 + Qdrant + MCP.

## Install

```bash
pip install agent-mem0
```

## Quick Start

```bash
# Global setup (one-time)
agent-mem0 install

# Project setup (per project)
cd your-project
agent-mem0 setup

# In Claude Code, generate project context
/agent-memory:init
```

## Features

- Persistent cross-session memory via mem0 + Qdrant
- Project-level memory isolation with global shared memory
- MCP Server (stdio) for Claude Code integration
- Multiple LLM/Embedding providers: Ollama, OpenAI, Anthropic, LiteLLM, Custom
- Interactive install wizard with auto-detection of Ollama/Docker
- Time-based memory filtering (default 30 days)
- Operation logging with rotation

## License

Apache-2.0
