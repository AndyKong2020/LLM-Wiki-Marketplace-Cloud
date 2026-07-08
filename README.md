# LLM-Wiki Marketplace

本仓库是 **LLM-Wiki**（NPU 大模型优化知识库）的多客户端插件市场，面向 Claude Code、Codex
和 OpenCode 分发同一套云端 wiki 读写入口。

Marketplace 名称：`llm-wiki-cloud`
插件：`llm-wiki-client@llm-wiki-cloud`

## 知识库能提供什么

LLM-Wiki 为 agent 提供可检索的 NPU 大模型优化经验，用于方案分析、策略选择、性能/精度回归归因和调试。当前覆盖四个 domain：

- `cann-infer`：推理优化
- `cann-train`：训练优化
- `cann-spatial`：空间智能
- `cann-embodied`：具身智能

知识内容包括模型族、算子/kernel、并行策略、推理/训练框架、优化技术、量化、硬件平台、recipe、algorithm，以及必要时可下探的 raw source 证据。

## 安装 / 更新 / 卸载

### Claude Code

在 Claude Code 里粘贴：

```text
# 添加 marketplace
/plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud

# 安装插件
/plugin install llm-wiki-client@llm-wiki-cloud
/reload-plugins

# 更新 marketplace
/plugin marketplace update llm-wiki-cloud

# 更新插件
/plugin update llm-wiki-client@llm-wiki-cloud
/reload-plugins

# 卸载插件
/plugin uninstall llm-wiki-client@llm-wiki-cloud
/reload-plugins

# 移除 marketplace
/plugin marketplace remove llm-wiki-cloud
```

等价 CLI 命令：

```bash
claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud
claude plugin install llm-wiki-client@llm-wiki-cloud
claude plugin marketplace update llm-wiki-cloud
claude plugin update llm-wiki-client@llm-wiki-cloud
claude plugin uninstall llm-wiki-client@llm-wiki-cloud
claude plugin marketplace remove llm-wiki-cloud
```

### Codex

```bash
# 添加 marketplace
codex plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud

# 安装插件
codex plugin add llm-wiki-client@llm-wiki-cloud

# 更新 marketplace
codex plugin marketplace upgrade llm-wiki-cloud

# 更新插件
codex plugin remove llm-wiki-client@llm-wiki-cloud
codex plugin add llm-wiki-client@llm-wiki-cloud

# 卸载插件
codex plugin remove llm-wiki-client@llm-wiki-cloud

# 移除 marketplace
codex plugin marketplace remove llm-wiki-cloud
```

### OpenCode

OpenCode 没有独立 marketplace source；安装和更新都重新运行 bootstrap。

```bash
# 安装 / 更新
curl -fsSL https://raw.githubusercontent.com/AndyKong2020/LLM-Wiki-Marketplace-Cloud/main/plugins/llm-wiki-client-opencode/bootstrap.sh | bash

# 卸载
curl -fsSL https://raw.githubusercontent.com/AndyKong2020/LLM-Wiki-Marketplace-Cloud/main/plugins/llm-wiki-client-opencode/uninstall.sh | bash
```

## 使用方式

在需要挂载知识库的项目中触发 `llm-wiki-cloud-mount` skill。它会探活远程
MCP，并向当前客户端的项目指令文件写入 wiki 使用提示：

- Claude Code：`CLAUDE.md`
- Codex / OpenCode：`AGENTS.md`

任务进入 NPU 大模型优化相关阶段时，触发 `llm-wiki-cloud-query` skill 通过
MCP tools 查询 wiki。任务结束后可触发 `llm-wiki-cloud-backflow` 创建本地任务归档；
若用户确认且配置了 `LLM_WIKI_UPLOAD_TOKEN`，插件会通过私有 HTTP backflow 入口上传归档。
Backflow 会优先沿用项目里的 `.agents-log/summary/`；如果没有相关 summary，才使用
内置 `session-extractor` skill 补齐同形态的 agent log summary。

固定入口：

```text
MCP read:         https://wiki.andykong.top/mcp
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
.agents/plugins/marketplace.json
plugins/llm-wiki-client-claude/
  .claude-plugin/plugin.json
  .mcp.json
  skills/
    llm-wiki-cloud-mount/SKILL.md
    llm-wiki-cloud-query/SKILL.md
    llm-wiki-cloud-backflow/SKILL.md
    session-extractor/
      SKILL.md
      scripts/extract.py
plugins/llm-wiki-client-codex/
  .codex-plugin/plugin.json
  .mcp.json
  skills/
    llm-wiki-cloud-mount/SKILL.md
    llm-wiki-cloud-query/SKILL.md
    llm-wiki-cloud-backflow/SKILL.md
    session-extractor/
      SKILL.md
      scripts/extract.py
plugins/llm-wiki-client-opencode/
  bootstrap.sh
  install-opencode.sh
  uninstall.sh
  opencode.json
  skills/
    llm-wiki-cloud-mount/SKILL.md
    llm-wiki-cloud-query/SKILL.md
    llm-wiki-cloud-backflow/SKILL.md
    session-extractor/
      SKILL.md
      scripts/extract.py
```
