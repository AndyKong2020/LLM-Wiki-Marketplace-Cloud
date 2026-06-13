---
name: llm-wiki-cloud-mount
description: 为当前项目挂载云端 LLM-Wiki（NPU 大模型优化知识库）。验证插件自带的远程 MCP 可用，并在项目 CLAUDE.md 写入 LLM-WIKI pin block。
allowed-tools: Bash Read Edit Write mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_search
version: 1.3.4
---

# LLM-Wiki Mount

## 1. 概述

`llm-wiki-cloud-mount` 把云端 LLM-Wiki 作为当前 Claude Code 项目的知识入口。

MCP 客户端配置由插件 root 的 `.mcp.json` 自带，安装插件后自动注册：

```text
mcp_server: cann-infer-wiki-cloud
mcp_url:    https://wiki.andykong.top/mcp
mode:       cloud-only read
```

本 skill 不 clone wiki 仓、不启动本机 server、不写 `.mcp.json`、不调用 `claude mcp add`。

整体流程：

```text
llm-wiki-cloud-mount
    |
    +--> STEP 1: 版本检查
    |
    +--> STEP 2: 远程 MCP probe
    |       调用 wiki_search(query="mount probe", limit=1)
    |
    +--> STEP 3: 写入 CLAUDE.md pin block
    |
    +--> STEP 4: 汇报 mount 状态
```

## 2. STEP 1：版本检查

先检查当前插件是否落后于云服务公开的静态版本文件。

当前本地插件版本固定取本 skill frontmatter 的 `version`：

```text
local_version=1.3.4
```

用 Bash 拉取远端 version manifest，并输出本地版本、远端版本与完整 manifest：

```bash
python3 - <<'PY'
import json
import urllib.request

LOCAL_VERSION = "1.3.4"
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

读取 manifest 后按顺序处理：

1. `version_manifest_status=unknown`：汇报检查失败原因，记为 `version_check=unknown`，继续 STEP 2；不要因为网络或 GitHub raw 临时失败阻断 mount。
2. manifest 缺少 `version` 或 `agent`，或 `version` 不是 `x.y.z` 语义版本：记为 `version_check=unknown`，汇报原因，继续 STEP 2。
3. manifest 有效时：读取 `agent` 字段并按其中指令执行版本检查与 mount 流程控制；需要展示更新说明时，优先发送 manifest 的 `user` 字段。如果 `agent` 要求停止 mount，记为 `version_check=stopped_by_manifest`，不要 MCP probe，不要写 `CLAUDE.md`。

需要提示用户更新时，使用 manifest 的 `user` 字段和当前平台更新说明：

```text
当前 llm-wiki-client 版本落后，必须先按当前平台更新后再挂载。
plugin_version_current=<current>
plugin_version_latest=<latest>

请在 Claude Code 中先更新 marketplace，再更新插件：
/plugin marketplace update llm-wiki-cloud
/plugin update llm-wiki-client@llm-wiki-cloud
/reload-plugins

如果 plugin_version_current 低于 1.2.0，不要只运行上面的 update。请先在 Claude Code 输入 `/plugins`，在界面中卸载旧的 llm-wiki-client；然后更新 marketplace 并重新安装插件：
/plugin marketplace update llm-wiki-cloud
/plugin install llm-wiki-client@llm-wiki-cloud
/reload-plugins

然后重新运行挂载入口。
```

## 3. STEP 2：远程 MCP Probe

先确认 MCP tools 在本次会话可见、可用。直接调用：

```text
mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_search(query="mount probe", limit=1)
```

处理规则：

| 结果 | 处理 |
|---|---|
| 返回 `results` 或空结果且无 warning | probe 通过，进入 STEP 2 |
| 返回 `{warning: "..."}` | 输出 warning 原文，停止 mount |
| 工具不存在 | 提示用户运行 `/reload-plugins` 后重新运行挂载入口 |
| MCP 不可达 | 提示当前云端 MCP 不可达，停止 mount |

不要伪造 probe 成功；不要尝试本地启动 server 兜底。

## 4. STEP 3：写入 CLAUDE.md Pin Block

目标文件优先为当前项目根目录 `CLAUDE.md`。如果不存在则创建。

写入或更新这段 block：

```md
<!-- LLM-WIKI:BEGIN -->
本项目已挂载云端 LLM-Wiki（NPU 大模型优化知识库）。
mcp_url: https://wiki.andykong.top/mcp

涉及下列任务时必须使用 llm-wiki-cloud-query skill：
- NPU 大模型优化任务，覆盖四个 domain：cann-infer（推理）、cann-train（训练）、cann-spatial（空间智能）、cann-embodied（具身智能）
  （模型族 qwen3-moe / deepseek-r1 / hunyuan-* / longcat-* / kimi-k2 等；算子 fia / mla / dia / sparse-flash-attention / 3dgs 渲染算子等；并行 tp / dp / cp / ep / fsdp / zigzag-cp / ulysses 等；框架 sglang / torchair / pypto / ascendc / atb / catlass / tilelang / torchtitan / verl / mindspeed / vllm-ascend 等；技术 npu-graph-mode / weight-prefetch / superkernel / afd / autofuse / rollout-rebalance 等；量化 w8a8c8 / w4a8c8 / mxfp8 / hif8 等；平台 atlas-a2 / atlas-a3 / ascend910 等）
- 进入新优化阶段、做方案分析、策略选择、debug 调试、性能/精度回归归因时

涉及 subagent 时，必须将 llm-wiki-cloud-query skill 的使用说明注入到拉起 subagent 的 prompt 中。

知识检索一律通过 MCP 工具：mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_search、mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_get_page。
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
version_check=ok | unknown | stopped_by_manifest
plugin_version_current=<current>
plugin_version_latest=<latest | unknown>
mcp_mode=cloud-only-read
mcp_url=https://wiki.andykong.top/mcp
mcp_probe=rpc_ok | tool_not_found_reload_required | failed | skipped_by_manifest
pin_status=created | updated | already_current | broken
claude_md=<absolute path>
```

如果 `version_check=stopped_by_manifest`，`mcp_probe=skipped_by_manifest`，`pin_status` 不输出或输出 `skipped_by_manifest`，并且必须打印 manifest `user` 字段（如有）或上面的更新命令。

如果 `mcp_probe=tool_not_found_reload_required`，最后提示用户：在当前会话中运行 `/reload-plugins` 后重新运行挂载入口。
