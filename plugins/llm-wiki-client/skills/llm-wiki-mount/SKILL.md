---
name: llm-wiki-mount
description: 为当前项目挂载云端 CANN-Infer-Wiki（NPU 大模型推理优化知识库）。验证插件自带的远程 MCP 可用，并在项目 CLAUDE.md 写入 LLM-WIKI pin block。
allowed-tools: Read Edit Write mcp__cann-infer-wiki__wiki_search
version: 0.5.0
---

# LLM-Wiki Mount

## 1. 概述

`llm-wiki-mount` 把云端 CANN-Infer-Wiki 作为当前 Claude Code 项目的知识入口。

MCP 客户端配置由插件 root 的 `.mcp.json` 自带，安装插件后自动注册：

```text
mcp_server: cann-infer-wiki
mcp_url:    http://124.220.212.101/mcp
mode:       cloud-only read
```

本 skill 不 clone wiki 仓、不启动本机 server、不写 `.mcp.json`、不调用 `claude mcp add`。

整体流程：

```text
/wiki-mount
    |
    +--> STEP 1: 远程 MCP probe
    |       调用 wiki_search(query="mount probe", limit=1)
    |
    +--> STEP 2: 写入 CLAUDE.md pin block
    |
    +--> STEP 3: 汇报 mount 状态
```

## 2. STEP 1：远程 MCP Probe

先确认 MCP tools 在本次会话可见、可用。直接调用：

```text
mcp__cann-infer-wiki__wiki_search(query="mount probe", limit=1)
```

处理规则：

| 结果 | 处理 |
|---|---|
| 返回 `results` 或空结果且无 warning | probe 通过，进入 STEP 2 |
| 返回 `{warning: "..."}` | 输出 warning 原文，停止 mount |
| 工具不存在 | 提示用户运行 `/reload-plugins` 后重新 `/wiki-mount` |
| MCP 不可达 | 提示当前云端 MCP 不可达，停止 mount |

不要伪造 probe 成功；不要尝试本地启动 server 兜底。

## 3. STEP 2：写入 CLAUDE.md Pin Block

目标文件优先为当前项目根目录 `CLAUDE.md`。如果不存在则创建。

写入或更新这段 block：

```md
<!-- LLM-WIKI:BEGIN -->
本项目已挂载云端 CANN-Infer-Wiki（NPU 大模型推理优化知识库）。
mcp_url: http://124.220.212.101/mcp
mode: cloud-only-read

在以下场景必须优先查询 wiki：
- 进入新的 LLM/NPU 推理优化阶段：bringup、profiling、kernel tuning、并行策略调整、显存优化、回归定位
- 做方案分析、策略选择、实现路线判断
- debug 调试、性能或精度异常排查、错误模式归因
- 涉及具体模型族、算子、并行策略、推理框架、优化技术、量化或硬件平台知识

知识检索一律通过 MCP 工具：mcp__cann-infer-wiki__wiki_search、mcp__cann-infer-wiki__wiki_get_page。
需要引用图片时，使用 wiki_get_page 返回 content 中的 /assets HTTP URL 或 assets manifest。
不要读取或 clone wiki 仓库；当前云端服务是匿名只读，不支持 `wiki_submit_trajectory` 上传。`/wiki-backflow` 仅保留本地归档流程，后续私有上传入口接入后再启用上传。
<!-- LLM-WIKI:END -->
```

幂等规则：

- 没有 block：追加到文件末尾。
- 已有完整 block：整体替换为上面的最新版本。
- 只有 BEGIN 或只有 END：停止 mount，提示用户手工修复残缺 block。

## 4. 汇报格式

mount 结束后按顺序输出：

```text
mcp_mode=cloud-only-read
mcp_url=http://124.220.212.101/mcp
mcp_probe=rpc_ok | tool_not_found_reload_required | failed
pin_status=created | updated | already_current | broken
claude_md=<absolute path>
```

如果 `mcp_probe=tool_not_found_reload_required`，最后提示用户：在当前会话中运行 `/reload-plugins` 后重新 `/wiki-mount`。
