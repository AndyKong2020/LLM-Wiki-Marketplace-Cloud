# LLM-Wiki Marketplace

本仓库是 **CANN-Infer-Wiki** 云服务的 Claude Code 客户端插件市场。

Marketplace 名称：`llm-wiki-cloud`
插件：`llm-wiki-client@llm-wiki-cloud`


## 安装

在 Claude Code 实例中，运行以下命令：

步骤 1：添加市场
```bash
/plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud
```

步骤 2：安装插件
```bash
/plugin install llm-wiki-client@llm-wiki-cloud
```

安装或更新后运行：

```text
/reload-plugins
```

更新：
```bash
/plugin update llm-wiki-client@llm-wiki-cloud
```

## 使用方式

1. 在需要挂载知识库的项目中运行 `/llm-wiki-client:llm-wiki-cloud-mount`。它会探活远程 MCP，并向 `CLAUDE.md`
   写入 wiki 使用提示。
2. 正常使用 claude code。任务进入 LLM/NPU 推理优化相关阶段时，`llm-wiki-cloud-query`
   skill 通过 MCP tools 查询 wiki。
3. （可选）任务结束后运行 `/llm-wiki-client:wiki-cloud-backflow` 创建本地任务归档。若用户确认且配置了
   `LLM_WIKI_UPLOAD_TOKEN`，插件会通过私有 HTTP backflow 入口上传归档，将任务经验吸收到 wiki 中。

固定入口：

```text
MCP read:        https://wiki.andykong.top/mcp
Backflow upload: https://wiki.andykong.top/upload/backflow
Assets:          https://wiki.andykong.top/assets/...
```

Backflow 上传是可选的，需配置 api-token：

```bash
export LLM_WIKI_UPLOAD_TOKEN="llmw_<token-from-operator>"
```

Token 由 operator 通过仓库外渠道分发。不要提交 token，不要把 token 写入归档，
也不要粘贴到日志里。


## 目录结构

```text
.claude-plugin/marketplace.json
plugins/llm-wiki-client/
  .claude-plugin/plugin.json
  .mcp.json
  README.md
  commands/
    wiki-cloud-mount.md
    wiki-cloud-backflow.md
  skills/
    llm-wiki-cloud-mount/SKILL.md
    llm-wiki-cloud-query/SKILL.md
    llm-wiki-cloud-backflow/SKILL.md
```
