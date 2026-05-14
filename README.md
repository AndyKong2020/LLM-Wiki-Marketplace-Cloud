# LLM-Wiki Marketplace

本仓库是 **CANN-Infer-Wiki**（NPU 大模型推理优化知识库）的 Claude Code 插件市场，只维护用户端插件和安装入口。Wiki 知识库内容由 `https://gitcode.com/AndyKong2020/CANN-Infer-Wiki.git` 维护（包含 MCP server、ingest 引擎、wiki 静态/动态页面），插件发布与 wiki 内容更新彼此解耦。

> Marketplace 名字仍是 `llm-wiki`、插件名仍是 `llm-wiki-client`——保留这套命名以便未来同 marketplace 下挂多个 LLM-Wiki 系列插件；当前唯一的 plugin 把内容指向 CANN-Infer-Wiki。

## 安装

添加 marketplace：

```bash
claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace --scope user
```

安装客户端插件：

```bash
claude plugin install llm-wiki-client@llm-wiki --scope user
```

安装那一刻插件自带的 `.mcp.json` 被 Claude Code 加载，`cann-infer-wiki` MCP server 自动注册到客户端配置（HTTP，URL `http://localhost:5100/mcp`）。

安装后在需要使用 wiki 的项目中执行：

```text
/wiki-mount
```

`/wiki-mount` 会：

1. 检查 `localhost:5100` 上 MCP server 是否在跑；未跑则按 `~/.claude/llm-wiki/repos/cann-infer-wiki/` 三态（missing/ready/invalid）clone 或 fast-forward 仓库到 cache，再 `nohup` 拉起 server。
2. 探活 MCP（调用一次 `wiki_search`）确认链路通。
3. 在项目 `CLAUDE.md` 写入 `<!-- LLM-WIKI:BEGIN -->...<!-- LLM-WIKI:END -->` pin block，告诉 agent 何时调 wiki。

后续真实任务结束后，可以使用 `/wiki-backflow` 把任务现场目录通过 `mcp__cann-infer-wiki__wiki_submit_trajectory` 上传到 wiki server；server 端 monitor 自动接力 ingest（脱敏 → Q 值更新 → 知识提取 → 查重合并 → 落库到 `wiki/dynamic/cann-infer/`），不再走 fork+PR 流程。

## 仓库边界

- **LLM-Wiki-Marketplace（本仓库）**：维护 Claude Code 插件、commands、skills、`.mcp.json` 客户端配置和 marketplace manifest。
- **CANN-Infer-Wiki**：维护知识库内容（schema、wiki 静态/动态页、sources）、MCP server（FastMCP + 三种 retriever）、ingest 引擎（脱敏 + Claude 加工流水线）。
- 插件通常很少更新；wiki 内容通过 `/wiki-mount` 自己拉取最新主仓，不依赖插件发版；server 端模型/索引升级也不需要重发插件。

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
