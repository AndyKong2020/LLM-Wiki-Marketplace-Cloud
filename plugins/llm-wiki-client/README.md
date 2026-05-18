# LLM-Wiki Client

用于 Claude Code 的 CANN-Infer-Wiki（NPU 大模型推理优化知识库）云端客户端插件。通过插件 root `.mcp.json` 自动注册远程 `cann-infer-wiki-cloud` MCP server；提供 `/wiki-cloud-mount` 写入项目 pin block、`/wiki-cloud-backflow` 创建本地任务回流归档并在配置 token 时上传，以及 `llm-wiki-cloud-query` skill 在运行时通过 MCP 工具检索 wiki。

## Install

本插件通过 LLM-Wiki Cloud marketplace 安装：

```bash
claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud --scope user
claude plugin install llm-wiki-client@llm-wiki-cloud --scope user
```

安装那一刻插件 `.mcp.json` 会被 Claude Code 加载，`cann-infer-wiki-cloud` MCP server 自动注册到客户端配置；URL 默认 `https://wiki.andykong.top/mcp`。

隔离测试时可以装到当前项目：

```bash
claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud --scope project
claude plugin install llm-wiki-client@llm-wiki-cloud --scope project
```

如果之前安装的是旧 marketplace：

```bash
claude plugin disable llm-wiki-client@llm-wiki --scope user
claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud --scope user
claude plugin install llm-wiki-client@llm-wiki-cloud --scope user
```

当前会话已经启动时，安装或更新后运行 `/reload-plugins`。

更新已安装的 Cloud 插件：

```bash
claude plugin update llm-wiki-client@llm-wiki-cloud --scope user
```

如果是 project scope 安装，把 `--scope user` 换成 `--scope project`。

## Commands

- `/wiki-cloud-mount`：验证云端 MCP 可达，并在项目 `CLAUDE.md` 写入 LLM-WIKI pin block。
- `/wiki-cloud-backflow`：创建本地 `.claude/llm-wiki/backflow/<task-slug>/` 轨迹归档；如果设置 `LLM_WIKI_UPLOAD_TOKEN`，会打包为 `tar.gz` 并上传到私有 backflow HTTP 入口。

`llm-wiki-cloud-query` skill 没有显式 slash 入口，由 `CLAUDE.md` pin block 中列出的触发场景自动激活。

## Private Backflow Upload

Upload is optional and token-gated. The fixed upload endpoint is:

```text
https://wiki.andykong.top/upload/backflow
```

Set the upload token with an environment variable:

```bash
export LLM_WIKI_UPLOAD_TOKEN="llmw_<token-from-operator>"
```

The operator distributes upload tokens out-of-band. Do not commit tokens, write them into archives, or paste them into logs.

For local or staging tests, optionally override the endpoint:

```bash
export LLM_WIKI_UPLOAD_URL="https://example.test/upload/backflow"
```

If `LLM_WIKI_UPLOAD_URL` is unset, `/wiki-cloud-backflow` uploads to `https://wiki.andykong.top/upload/backflow`.

The upload flow keeps the local archive and creates a tar.gz copy from:

```text
.claude/llm-wiki/backflow/<task-slug>/
```

The package is created from the contents of that archive root, must contain exactly one top-level `.md` file, and must be no larger than 50 MiB compressed. The server response uses:

| `status` | Meaning |
|---|---|
| `ok` | Package accepted; report `id`, `path`, and `entry`. |
| `duplicate` | Server already has this package; report existing `id` and `path`. |
| `error` | Upload failed; report `error` and `message`, then keep the local archive. |

Successful and duplicate uploads are queued under server-side `sources/sessions/uploaded/`. Ingest runs asynchronously after upload; `/wiki-cloud-backflow` does not wait for accepted/to_review processing.

## Fixed MCP Endpoint

```text
https://wiki.andykong.top/mcp
```

客户端不 clone wiki 仓、不启动本机 server、不需要 GitCode 权限或 SSH key。MCP 读取保持匿名，通过 `wiki_search` / `wiki_get_page` / `wiki_get_index` 访问；backflow 写入不走 MCP，而是通过私有 token HTTP 上传入口。

图片资产通过 HTTPS URL 暴露，例如：

```text
https://wiki.andykong.top/assets/cann-infer/models/qwen3-moe/attention_tp.png
```

当需要理解图片内容时，agent 应把 asset URL 下载到 `/tmp/llm-wiki-assets/<page-id>/<filename>`，再用 Read 工具读取本地图片。只引用或展示图片时可以直接使用 HTTPS URL。

## Design

插件包含三类资产：

- `commands/`：`wiki-cloud-mount.md`、`wiki-cloud-backflow.md` 两个 slash 入口
- `skills/`：`llm-wiki-cloud-mount`、`llm-wiki-cloud-query`、`llm-wiki-cloud-backflow` 三个 skill，承载流程规则
- `.mcp.json`：插件 root，自动注册云端 `cann-infer-wiki-cloud` MCP server（HTTP transport，HTTPS URL `https://wiki.andykong.top/mcp`）

MCP server 由云端托管，客户端永远通过 MCP 工具（`wiki_search` / `wiki_get_page` / `wiki_get_index`）访问 wiki，不绕开走本地文件。回流上传使用独立 HTTPS endpoint 和 `LLM_WIKI_UPLOAD_TOKEN`，不改变云端 MCP 读取行为。

## Verification

运行 `/wiki-cloud-mount` 后，预期远程 MCP probe 成功，并在项目 `CLAUDE.md` 写入 pin block。直接用 MCP 查询时，预期页面图片链接是：

```text
https://wiki.andykong.top/assets/...
```

云端 MCP 读取工具列表应只包含：

```text
wiki_search
wiki_get_page
wiki_get_index
```
