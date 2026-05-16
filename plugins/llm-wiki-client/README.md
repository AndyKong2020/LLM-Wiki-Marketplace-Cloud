# LLM-Wiki Client

用于 Claude Code 的 CANN-Infer-Wiki（NPU 大模型推理优化知识库）云端只读客户端插件。通过插件 root `.mcp.json` 自动注册远程 `cann-infer-wiki` MCP server；提供 `/wiki-mount` 写入项目 pin block、`/wiki-backflow` 保留任务回流归档流程，以及 `llm-wiki-query` skill 在运行时通过 MCP 工具检索 wiki。

## Install

本插件通过 LLM-Wiki marketplace 安装：

```bash
claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud --scope user
claude plugin install llm-wiki-client@llm-wiki --scope user
```

安装那一刻插件 `.mcp.json` 会被 Claude Code 加载，`cann-infer-wiki` MCP server 自动注册到客户端配置；URL 默认 `http://124.220.212.101/mcp`。

## Commands

- `/wiki-mount`：验证云端 MCP 可达，并在项目 `CLAUDE.md` 写入 LLM-WIKI pin block。
- `/wiki-backflow`：创建本地 `.claude/llm-wiki/backflow/<task-slug>/` 轨迹归档；当前云端只读 MVP 不执行上传，上传流程保留到后续私有入口启用。

`llm-wiki-query` skill 没有显式 slash 入口，由 `CLAUDE.md` pin block 中列出的触发场景自动激活。

## Fixed MCP Endpoint

```text
http://124.220.212.101/mcp
```

客户端不 clone wiki 仓、不启动本机 server、不需要 GitCode 权限或 SSH key。当前 MVP 云端服务是匿名只读，不暴露 `wiki_submit_trajectory`；backflow 先只做本地归档。

## Design

插件包含三类资产：

- `commands/`：`wiki-mount.md`、`wiki-backflow.md` 两个 slash 入口
- `skills/`：`llm-wiki-mount`、`llm-wiki-query`、`llm-wiki-backflow` 三个 skill，承载流程规则
- `.mcp.json`：插件 root，自动注册云端 `cann-infer-wiki` MCP server（HTTP transport，URL `http://124.220.212.101/mcp`）

MCP server 由云端托管，客户端永远通过 MCP 工具（`wiki_search` / `wiki_get_page`）访问 wiki，不绕开走本地文件。回流上传会在后续私有上传/鉴权入口接入后恢复。
