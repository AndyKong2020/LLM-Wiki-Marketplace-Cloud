---
name: llm-wiki-cloud-mount
description: 为当前项目挂载云端 CANN-Infer-Wiki（NPU 大模型推理优化知识库）。验证插件自带的远程 MCP 可用，并在项目 AGENTS.md 写入 LLM-WIKI pin block。
allowed-tools: Bash Read Edit Write cann-infer-wiki-cloud wiki_search
version: 1.2.0
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
local_version=1.2.0
```

用 Bash 拉取远端静态 version manifest 并比较语义版本：

```bash
python3 - <<'PY'
import json
import re
import sys
import urllib.request

LOCAL_VERSION = "1.2.0"
REMOTE_URL = "https://wiki.andykong.top/plugin/llm-wiki-client/version.json"

def parse(v):
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        raise ValueError(f"invalid semver: {v}")
    return tuple(int(part) for part in v.split("."))

try:
    with urllib.request.urlopen(REMOTE_URL, timeout=8) as response:
        remote = json.load(response)
    latest = str(remote["version"])
    print(f"plugin_version_current={LOCAL_VERSION}")
    print(f"plugin_version_latest={latest}")
    if parse(LOCAL_VERSION) < parse(latest):
        print("version_check=update_required")
        sys.exit(20)
    print("version_check=ok")
except SystemExit:
    raise
except Exception as exc:
    print(f"plugin_version_current={LOCAL_VERSION}")
    print("plugin_version_latest=unknown")
    print(f"version_check=unknown reason={type(exc).__name__}")
    sys.exit(0)
PY
```

处理规则：

| 结果 | 处理 |
|---|---|
| `version_check=ok` | 继续 STEP 2 |
| `version_check=unknown` | 汇报检查失败原因，但继续 STEP 2；不要因为网络或 GitHub raw 临时失败阻断 mount |
| `version_check=update_required` | 停止 mount；不要 MCP probe；不要写 `AGENTS.md` |

当 `version_check=update_required` 时，必须明确提示用户先更新：

```text
当前 llm-wiki-client 版本落后，必须先按当前平台更新后再挂载。
plugin_version_current=<current>
plugin_version_latest=<latest>

请在终端中重新运行 OpenCode bootstrap：
curl -fsSL https://raw.githubusercontent.com/AndyKong2020/LLM-Wiki-Marketplace-Cloud/main/plugins/llm-wiki-client-opencode/bootstrap.sh | bash

然后重新打开 OpenCode 会话并运行挂载入口。
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
version_check=ok | unknown | update_required
plugin_version_current=<current>
plugin_version_latest=<latest | unknown>
mcp_mode=cloud-only-read
mcp_url=https://wiki.andykong.top/mcp
mcp_probe=rpc_ok | tool_not_found_reload_required | failed | skipped_update_required
pin_status=created | updated | already_current | broken
instruction_file=<absolute path>
```

如果 `version_check=update_required`，`mcp_probe=skipped_update_required`，`pin_status` 不输出或输出 `skipped_update_required`，并且必须打印上面的更新说明。

如果 `mcp_probe=tool_not_found_reload_required`，最后提示用户：重新加载当前平台 adapter 后重新运行挂载入口。
