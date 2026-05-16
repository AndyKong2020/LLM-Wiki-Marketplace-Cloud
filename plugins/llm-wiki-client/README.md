# LLM-Wiki Client

用于 Claude Code 的 CANN-Infer-Wiki（NPU 大模型推理优化知识库）云端只读客户端插件。通过插件 root `.mcp.json` 自动注册远程 `cann-infer-wiki-cloud` MCP server；提供 `/wiki-cloud-mount` 写入项目 pin block、`/wiki-cloud-backflow` 保留任务回流归档流程，以及 `llm-wiki-cloud-query` skill 在运行时通过 MCP 工具检索 wiki。

## Install

本插件通过 LLM-Wiki Cloud marketplace 安装：

```bash
claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud --scope user
claude plugin install llm-wiki-client@llm-wiki-cloud --scope user
```

安装那一刻插件 `.mcp.json` 会被 Claude Code 加载，`cann-infer-wiki-cloud` MCP server 自动注册到客户端配置；URL 默认 `https://wiki.andykong.top/mcp`。

如果之前安装的是旧 marketplace：

```bash
claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud --scope user
claude plugin install llm-wiki-client@llm-wiki-cloud --scope user
```

当前会话已经启动时，安装或更新后运行 `/reload-plugins`。

## Commands

- `/wiki-cloud-mount`：验证云端 MCP 可达，并在项目 `CLAUDE.md` 写入 LLM-WIKI pin block。
- `/wiki-cloud-backflow`：创建本地 `.claude/llm-wiki/backflow/<task-slug>/` 轨迹归档；当前云端只读 MVP 不执行上传，上传流程保留到后续私有入口启用。

`llm-wiki-cloud-query` skill 没有显式 slash 入口，由 `CLAUDE.md` pin block 中列出的触发场景自动激活。

## Fixed MCP Endpoint

```text
https://wiki.andykong.top/mcp
```

客户端不 clone wiki 仓、不启动本机 server、不需要 GitCode 权限或 SSH key。当前 MVP 云端服务是匿名只读，不暴露 `wiki_submit_trajectory`；backflow 先只做本地归档。

## Design

插件包含三类资产：

- `commands/`：`wiki-cloud-mount.md`、`wiki-cloud-backflow.md` 两个 slash 入口
- `skills/`：`llm-wiki-cloud-mount`、`llm-wiki-cloud-query`、`llm-wiki-cloud-backflow` 三个 skill，承载流程规则
- `.mcp.json`：插件 root，自动注册云端 `cann-infer-wiki-cloud` MCP server（HTTP transport，HTTPS URL `https://wiki.andykong.top/mcp`）

MCP server 由云端托管，客户端永远通过 MCP 工具（`wiki_search` / `wiki_get_page`）访问 wiki，不绕开走本地文件。回流上传会在后续私有上传/鉴权入口接入后恢复。

## Verification

运行 `/wiki-cloud-mount` 后，预期远程 MCP probe 成功，并在项目 `CLAUDE.md` 写入 pin block。直接用 MCP 查询时，预期页面图片链接是：

```text
https://wiki.andykong.top/assets/...
```

公开只读 MVP 的工具列表应只包含：

```text
wiki_search
wiki_get_page
wiki_get_index
```
