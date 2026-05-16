# LLM-Wiki Marketplace

本仓库是 **CANN-Infer-Wiki**（NPU 大模型推理优化知识库）的 Claude Code 云端客户端插件市场，只维护用户端插件和安装入口。Wiki 知识库内容与云端 MCP 服务由独立仓库维护，用户端不 clone wiki 仓、不启动本机 server。

> Marketplace 名字仍是 `llm-wiki`、插件名仍是 `llm-wiki-client`——保留这套命名以便未来同 marketplace 下挂多个 LLM-Wiki 系列插件；当前唯一的 plugin 把内容指向 CANN-Infer-Wiki。

## 安装

添加 marketplace：

```bash
claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud --scope user
```

安装客户端插件：

```bash
claude plugin install llm-wiki-client@llm-wiki --scope user
```

安装那一刻插件自带的 `.mcp.json` 被 Claude Code 加载，`cann-infer-wiki` MCP server 自动注册到客户端配置（HTTP，URL `http://124.220.212.101/mcp`）。

安装后在需要使用 wiki 的项目中执行：

```text
/wiki-mount
```

`/wiki-mount` 会：

1. 探活云端 MCP（调用一次 `wiki_search`）确认链路通。
2. 在项目 `CLAUDE.md` 写入 `<!-- LLM-WIKI:BEGIN -->...<!-- LLM-WIKI:END -->` pin block，告诉 agent 何时调 wiki。

后续真实任务结束后，可以使用 `/wiki-backflow` 创建本地任务现场归档。当前云端只读 MVP 不暴露 `wiki_submit_trajectory`，所以默认停在上传前；回流上传流程保留在插件内，等后续私有上传/鉴权入口接上后恢复。

## 仓库边界

- **LLM-Wiki-Marketplace-Cloud（本仓库）**：维护 Claude Code 插件、commands、skills、`.mcp.json` 客户端配置和 marketplace manifest。
- **CANN-Infer-Wiki-Cloud**：维护知识库内容、MCP server、ingest 引擎和云端部署配置。
- 插件通常很少更新；wiki 内容和 server 端模型/索引升级由云端服务维护，不需要用户侧重发插件。

## 本地开发

本地调试 marketplace：

```bash
cd /path/to/LLM-Wiki-Marketplace
claude plugin marketplace add "$(pwd)" --scope user
claude plugin install llm-wiki-client@llm-wiki --scope user
```

修改插件后执行校验：

```bash
claude plugin validate .
claude plugin validate plugins/llm-wiki-client
```

发布新版本时，需要同步更新：

- `.claude-plugin/marketplace.json`
- `plugins/llm-wiki-client/.claude-plugin/plugin.json`

修改插件 `.mcp.json` 后，已安装的用户需要在会话中跑 `/reload-plugins`（无需退出 Claude Code）即可拿到新配置。
