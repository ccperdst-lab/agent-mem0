---
name: agent-memory:init
description: AI 分析当前项目结构并生成项目级 CLAUDE.md
trigger: /agent-memory:init
---

# /agent-memory:init

分析当前项目，生成项目级 CLAUDE.md。

## 执行步骤

### Step 1: 扫描项目

分析以下文件（如果存在）：
- go.mod / package.json / pom.xml / requirements.txt / pyproject.toml → 语言和依赖
- 目录结构（ls 顶层和关键子目录）→ 架构模式
- docker-compose.yml / Dockerfile / k8s/ → 基础设施
- Makefile / justfile → 构建方式
- README.md → 已有文档
- .env.example → 环境变量

### Step 2: 生成项目 CLAUDE.md

在 .claude/CLAUDE.md 写入（如已有内容则在开头追加项目信息段落）：

```markdown
# 项目上下文

- **project**: <项目名，从 .claude/mcp.json 的 args 中获取，或使用目录名>
- **技术栈**: <检测到的语言、框架、数据库等>
- **架构**: <目录结构推断的架构模式>
- **核心功能**: <从 README 或代码推断的主要功能>
- **构建/运行**: <从 Makefile 或 package.json 推断的命令>
- **测试**: <测试框架和运行方式>
```

### Step 3: 确认

将生成的内容展示给用户，等待用户确认或修改后再写入文件。
