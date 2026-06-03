# LLM-Wiki Marketplace

本仓库是 **CANN-Infer-Wiki** 云服务的多客户端插件市场，面向 Claude Code、Codex
和 OpenCode 分发同一套云端 wiki 读写入口。

Marketplace 名称：`llm-wiki-cloud`
插件：`llm-wiki-client@llm-wiki-cloud`

## 安装维护命令

### Claude Code

在 Claude Code 里粘贴：

```text
# 添加 marketplace
/plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud

# 安装插件
/plugin 进入插件配置页面，进入 Marketplaces 菜单
选择 llm-wiki-cloud -> Browse plugins (1)
安装 llm-wiki-client
/reload-plugins

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

任务进入 LLM/NPU 推理优化相关阶段时，触发 `llm-wiki-cloud-query` skill 通过
MCP tools 查询 wiki。任务结束后可触发 `llm-wiki-cloud-backflow` 创建本地任务归档；
若用户确认且配置了 `LLM_WIKI_UPLOAD_TOKEN`，插件会通过私有 HTTP backflow 入口上传归档。

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

## 维护发布

`src/skills/` 是三端 skill 的唯一源头，`src/shared/` 保存共享常量和 pin block，
`platforms/` 保存需要变量渲染的 JSON 模板。

修改源模板后运行：

```bash
python3 scripts/sync_adapters.py
python3 scripts/validate_release.py
python3 -m unittest discover -s tests -v
```

`scripts/sync_adapters.py` 会生成 Claude Code、Codex 和 OpenCode 的 skills、manifest
与 MCP 配置。维护生成产物时不要直接手改 `plugins/*/skills/**/SKILL.md` 或 manifest；
应修改源模板后重新同步。

正式发布前需要人工对比 Claude Code 适配输出与生产原版 skill 文档，确认差异只来自：

- 版本号
- 三端 skill 入口命名
- 平台指令文件：`CLAUDE.md` / `AGENTS.md`
- 平台 MCP tool 名称
- OpenCode 安装脚本和共享 backflow 路径

OpenCode 的 `bootstrap.sh`、`install-opencode.sh`、`uninstall.sh` 是直接维护的发布脚本。

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
plugins/llm-wiki-client-codex/
  .codex-plugin/plugin.json
  .mcp.json
  skills/
    llm-wiki-cloud-mount/SKILL.md
    llm-wiki-cloud-query/SKILL.md
    llm-wiki-cloud-backflow/SKILL.md
plugins/llm-wiki-client-opencode/
  bootstrap.sh
  install-opencode.sh
  uninstall.sh
  opencode.json
  skills/
    llm-wiki-cloud-mount/SKILL.md
    llm-wiki-cloud-query/SKILL.md
    llm-wiki-cloud-backflow/SKILL.md
```
