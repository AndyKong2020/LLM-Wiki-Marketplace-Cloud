# LLM-Wiki Client

用于 Claude Code 的 CANN-Infer-Wiki（NPU 大模型推理优化知识库）客户端插件。通过插件 root `.mcp.json` 自动注册 `cann-infer-wiki` MCP server；提供 `/wiki-mount`（必要时本机起 server + 写 CLAUDE.md pin）、`/wiki-backflow`（通过 `wiki_submit_trajectory` 直接上传任务目录）两个入口，以及 `llm-wiki-query` skill（运行时通过 MCP 工具检索 wiki）。

## Install

本插件通过 LLM-Wiki marketplace 安装：

```bash
claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace --scope user
claude plugin install llm-wiki-client@llm-wiki --scope user
```

安装那一刻插件 `.mcp.json` 会被 Claude Code 加载，`cann-infer-wiki` MCP server 自动注册到客户端配置；URL 默认 `http://localhost:5100/mcp`。

## Commands

- `/wiki-mount`：确保本机 MCP server 在 5100 端口跑着（必要时 clone wiki 仓 + 拉起 server）+ 在项目 `CLAUDE.md` 写入 LLM-WIKI pin block。
- `/wiki-backflow`：把任务现场打包成目录，通过 MCP `wiki_submit_trajectory` 上传到 wiki server。

`/wiki-backflow` 分两步：

1. **轨迹归档**：在本地 `.claude/llm-wiki/backflow/<task-slug>/` 生成顶层 `source.md` + 任务现场材料。
2. **轨迹上传**：用户确认后调用 `mcp__cann-infer-wiki__wiki_submit_trajectory` 一次性把整个目录送到 server 的 `sources/sessions/uploaded/<session_id>/`；server 端 monitor 自动接力 ingest。

`/wiki-backflow` 不接收参数。`task-slug` 和 workspace 由 agent 根据当前任务上下文判断。

`llm-wiki-query` skill 没有显式 slash 入口，由 `CLAUDE.md` pin block 中列出的触发场景自动激活。

## Fixed Wiki

```text
https://gitcode.com/AndyKong2020/CANN-Infer-Wiki.git
main
```

server 端 cache 走 HTTPS clone，不要求用户配 SSH key。

## Local State

全局 cache（仅 server 端依赖，客户端不直接 Read/Grep）：

```text
~/.claude/llm-wiki/repos/cann-infer-wiki/
```

项目状态：

```text
<project>/.claude/llm-wiki/
└── backflow/<task-slug>/    # /wiki-backflow 生成的归档目录
```

mount 状态直接写在项目 `CLAUDE.md` 的 `<!-- LLM-WIKI:BEGIN -->` block 中，不再维护独立的 mount 配置文件；MCP 客户端配置由插件 `.mcp.json` 管理，不需要 `claude mcp add`。

## Design

插件包含三类资产：

- `commands/`：`wiki-mount.md`、`wiki-backflow.md` 两个 slash 入口
- `skills/`：`llm-wiki-mount`、`llm-wiki-query`、`llm-wiki-backflow` 三个 skill，承载流程规则
- `.mcp.json`：插件 root，自动注册 `cann-infer-wiki` MCP server（HTTP transport，URL `http://localhost:5100/mcp`）

MCP server 仍是独立 Python 进程，**不由插件本身托管**——`/wiki-mount` 在本机首次运行时按需 clone 仓库到 cache + `nohup` 拉起 server，但 server 进程的所有权归运行环境。客户端永远通过 MCP 工具（`wiki_search` / `wiki_get_page` / `wiki_submit_trajectory`）访问 wiki，不绕开走 cache 文件。
