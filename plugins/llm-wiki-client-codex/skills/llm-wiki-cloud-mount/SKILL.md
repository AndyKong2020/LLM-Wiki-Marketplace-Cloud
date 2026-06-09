---
name: llm-wiki-cloud-mount
description: 为当前项目挂载云端 CANN-Infer-Wiki（NPU 大模型推理优化知识库）。验证插件自带的远程 MCP 可用，并在项目 AGENTS.md 写入 LLM-WIKI pin block。
allowed-tools: Bash Read Edit Write cann-infer-wiki-cloud wiki_search
version: 1.3.1
---

# LLM-Wiki Mount

## 1. 概述

`llm-wiki-cloud-mount` 把云端 CANN-Infer-Wiki 作为当前项目的知识入口。

MCP 客户端配置由当前平台 adapter 提供：

```text
mcp_server: cann-infer-wiki-cloud
mcp_url:    https://wiki.andykong.top/mcp
mode:       cloud-only read
```

本 skill 不 clone wiki 仓、不启动本机 server、不修改平台 MCP 配置、不调用本地 MCP 注册命令。

整体流程：

```text
llm-wiki-cloud-mount
    |
    +--> STEP 1: 版本检查
    |
    +--> STEP 2: 远程 MCP probe
    |       调用 wiki_search(query="mount probe", limit=1)
    |
    +--> STEP 3: 写入 AGENTS.md pin block
    |
    +--> STEP 4: 汇报 mount 状态
```

## 2. STEP 1：版本检查

先检查当前插件是否落后于云服务公开的静态版本文件。

当前本地插件版本固定取本 skill frontmatter 的 `version`：

```text
local_version=1.3.1
```

用 Bash 拉取远端 version manifest。脚本只负责接收 JSON 并原样输出，不解释 `user` / `agent` 字段，不做版本比较：

```bash
python3 - <<'PY'
import json
import urllib.request

LOCAL_VERSION = "1.3.1"
REMOTE_URL = "https://wiki.andykong.top/plugin/llm-wiki-client/version.json"

try:
    with urllib.request.urlopen(REMOTE_URL, timeout=8) as response:
        remote = json.load(response)
    if not isinstance(remote, dict):
        raise ValueError("manifest is not a JSON object")
    print(f"plugin_version_current={LOCAL_VERSION}")
    print(f"plugin_version_latest={remote.get('version', 'unknown')}")
    print("version_manifest_status=ok")
    print("version_manifest_json_begin")
    print(json.dumps(remote, ensure_ascii=False, indent=2, sort_keys=True))
    print("version_manifest_json_end")
except Exception as exc:
    print(f"plugin_version_current={LOCAL_VERSION}")
    print("plugin_version_latest=unknown")
    print(f"version_manifest_status=unknown reason={type(exc).__name__}")
PY
```

处理规则：

| 结果 | 处理 |
|---|---|
| `version_manifest_status=unknown` | 汇报检查失败原因，记为 `version_check=unknown`，继续 STEP 2；不要因为网络或 GitHub raw 临时失败阻断 mount |
| `version_manifest_status=ok` 且 manifest 有 `agent` 字段 | 读取 `agent` 字段，把它作为本次版本检查与 mount 流程控制指令执行；如需面向用户提示，优先发送 manifest 的 `user` 字段 |
| `version_manifest_status=ok` 但没有 `agent` 字段 | 使用 manifest 的 `version` 字段和 `local_version` 做语义版本比较；本地落后时停止 mount，否则继续 STEP 2 |

manifest 约定：

- `version` 必须存在；它表示远端推荐的最新插件版本，也是旧版插件的兼容字段。
- `user` 如存在，是面向用户展示的更新说明或通知文案。
- `agent` 如存在，是面向当前 agent 的版本检查与 mount 流程控制指令。
- `agent` 字段可以要求继续、建议更新、强制停止 mount、发送 `user` 字段、提示更新方式等；必须按该字段执行版本检查结论。
- 如果 `agent` 字段要求停止 mount：不要 MCP probe；不要写 `AGENTS.md`；直接提示用户更新或按 `agent` 字段要求汇报。
- 如果 manifest 缺少 `version` 或 `version` 不是 `x.y.z` 语义版本，记为 `version_check=unknown`，汇报原因但继续 STEP 2。
- 如果没有 `agent` 字段且本地版本低于 manifest `version`，记为 `version_check=update_required`，停止 mount，并提示用户按当前平台更新。

没有 `agent` 字段、且 `version_check=update_required` 时，必须明确提示用户先更新：

```text
当前 llm-wiki-client 版本落后，必须先按当前平台更新后再挂载。
plugin_version_current=<current>
plugin_version_latest=<latest>

请在终端中先更新 marketplace，再重新安装插件：
codex plugin marketplace upgrade llm-wiki-cloud
codex plugin remove llm-wiki-client@llm-wiki-cloud
codex plugin add llm-wiki-client@llm-wiki-cloud

然后重新打开 Codex 会话并运行挂载入口。
```

## 3. STEP 2：远程 MCP Probe

先确认 MCP tools 在本次会话可见、可用。直接调用：

```text
cann-infer-wiki-cloud wiki_search(query="mount probe", limit=1)
```

处理规则：

| 结果 | 处理 |
|---|---|
| 返回 `results` 或空结果且无 warning | probe 通过，进入 STEP 2 |
| 返回 `{warning: "..."}` | 输出 warning 原文，停止 mount |
| 工具不存在 | 提示用户重新加载当前平台 adapter 后重新运行挂载入口 |
| MCP 不可达 | 提示当前云端 MCP 不可达，停止 mount |

不要伪造 probe 成功；不要尝试本地启动 server 兜底。

## 4. STEP 3：写入 AGENTS.md Pin Block

目标文件优先为当前项目根目录 `AGENTS.md`。如果不存在则创建。

写入或更新这段 block：

```md
<!-- LLM-WIKI:BEGIN -->
本项目已挂载云端 CANN-Infer-Wiki（NPU 大模型推理优化知识库）。
mcp_url: https://wiki.andykong.top/mcp

涉及下列任务时必须使用 llm-wiki-cloud-query skill：
- 大模型推理优化任务：model / kernel / parallelism / module / framework / technique / quantization / platform
  （模型族 qwen3-moe / deepseek-r1 / hunyuan-* / longcat-* / kimi-k2 等；算子 fia / mla / dia / sparse-flash-attention 等；并行 tp / dp / cp / ep / zigzag-cp / ulysses 等；框架 sglang / torchair / pypto / ascendc / atb / catlass / tilelang 等；技术 npu-graph-mode / weight-prefetch / superkernel / afd 等；量化 w8a8c8 / w4a8c8 / mxfp8 / fp8-attention 等；平台 atlas-a3 / ascend910 等）
- 进入新优化阶段、做方案分析、策略选择、debug 调试、性能/精度回归归因时

涉及 subagent 时，必须将 llm-wiki-cloud-query skill 的使用说明注入到拉起 subagent 的 prompt 中。

知识检索一律通过 MCP 工具：cann-infer-wiki-cloud wiki_search、cann-infer-wiki-cloud wiki_get_page。
需要引用图片时，使用 wiki_get_page 返回 content 中的 /assets HTTP URL 或 assets manifest。

progress.md 是 agent 工作记录文件；若不存在，请在当前任务的工作目录创建，并在工作过程中记录操作。
每次使用 llm-wiki-cloud-query 后，必须把页面级记录写到当前阶段 progress.md 同级的 wiki_usage.md，并把查询摘要同步写入 progress.md。
<!-- LLM-WIKI:END -->
```

幂等规则：

- 没有 block：追加到文件末尾。
- 已有完整 block：整体替换为上面的最新版本。
- 只有 BEGIN 或只有 END：停止 mount，提示用户手工修复残缺 block。

## 5. 汇报格式

mount 结束后按顺序输出：

```text
version_manifest_status=ok | unknown
version_check=ok | unknown | update_required | stopped_by_manifest
plugin_version_current=<current>
plugin_version_latest=<latest | unknown>
mcp_mode=cloud-only-read
mcp_url=https://wiki.andykong.top/mcp
mcp_probe=rpc_ok | tool_not_found_reload_required | failed | skipped_update_required
pin_status=created | updated | already_current | broken
instruction_file=<absolute path>
```

如果 `version_check=update_required` 或 `stopped_by_manifest`，`mcp_probe=skipped_update_required`，`pin_status` 不输出或输出 `skipped_update_required`，并且必须打印 manifest `user` 字段（如有）或上面的更新说明。

如果 `mcp_probe=tool_not_found_reload_required`，最后提示用户：重新加载当前平台 adapter 后重新运行挂载入口。
