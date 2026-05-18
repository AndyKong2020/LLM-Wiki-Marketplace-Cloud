---
name: llm-wiki-cloud-mount
description: 为当前项目挂载云端 CANN-Infer-Wiki（NPU 大模型推理优化知识库）。验证插件自带的远程 MCP 可用，并在项目 CLAUDE.md 写入 LLM-WIKI pin block。
allowed-tools: Bash Read Edit Write mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_search
version: 1.1.0
---

# LLM-Wiki Mount

## 1. 概述

`llm-wiki-cloud-mount` 把云端 CANN-Infer-Wiki 作为当前 Claude Code 项目的知识入口。

MCP 客户端配置由插件 root 的 `.mcp.json` 自带，安装插件后自动注册：

```text
mcp_server: cann-infer-wiki-cloud
mcp_url:    https://wiki.andykong.top/mcp
mode:       cloud-only read
```

本 skill 不 clone wiki 仓、不启动本机 server、不写 `.mcp.json`、不调用 `claude mcp add`。

整体流程：

```text
/wiki-cloud-mount
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

先检查当前插件是否落后于远端 marketplace main 分支。此检查只在
`/wiki-cloud-mount` 执行，不在 query/backflow 路径里执行。

当前本地插件版本固定取本 skill frontmatter 的 `version`：

```text
local_version=1.1.0
```

用 Bash 拉取远端 plugin manifest 并比较语义版本：

```bash
python3 - <<'PY'
import json
import re
import sys
import urllib.request

LOCAL_VERSION = "1.1.0"
REMOTE_URL = "https://raw.githubusercontent.com/AndyKong2020/LLM-Wiki-Marketplace-Cloud/main/plugins/llm-wiki-client/.claude-plugin/plugin.json"

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
| `version_check=update_required` | 停止 mount；不要 MCP probe；不要写 `CLAUDE.md` |

当 `version_check=update_required` 时，必须明确提示用户先更新，不使用“建议”措辞：

```text
当前 llm-wiki-client 版本落后，必须先更新插件后再挂载。
plugin_version_current=<current>
plugin_version_latest=<latest>

请在 Claude Code 中运行：
/plugin update llm-wiki-client@llm-wiki-cloud
/reload-plugins

然后重新运行：
/llm-wiki-client:llm-wiki-cloud-mount
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
| 工具不存在 | 提示用户运行 `/reload-plugins` 后重新 `/wiki-cloud-mount` |
| MCP 不可达 | 提示当前云端 MCP 不可达，停止 mount |

不要伪造 probe 成功；不要尝试本地启动 server 兜底。

## 4. STEP 3：写入 CLAUDE.md Pin Block

目标文件优先为当前项目根目录 `CLAUDE.md`。如果不存在则创建。

写入或更新这段 block：

```md
<!-- LLM-WIKI:BEGIN -->
本项目已挂载云端 CANN-Infer-Wiki（NPU 大模型推理优化知识库）。
mcp_url: https://wiki.andykong.top/mcp
mode: cloud-only-read

在以下场景必须优先查询 wiki：
- 进入新的 LLM/NPU 推理优化阶段：bringup、profiling、kernel tuning、并行策略调整、显存优化、回归定位
- 做方案分析、策略选择、实现路线判断
- debug 调试、性能或精度异常排查、错误模式归因
- 涉及具体模型族、算子、并行策略、推理框架、优化技术、量化或硬件平台知识

知识检索一律通过 MCP 工具：mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_search、mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_get_page。
需要引用图片时，使用 wiki_get_page 返回 content 中的 /assets HTTP URL 或 assets manifest。
不要读取或 clone wiki 仓库；当前 MCP 服务是匿名只读，不支持 `wiki_submit_trajectory`。任务回流使用 `/wiki-cloud-backflow`，在用户确认且配置 `LLM_WIKI_UPLOAD_TOKEN` 后通过私有 HTTP 入口上传。
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
claude_md=<absolute path>
```

如果 `version_check=update_required`，`mcp_probe=skipped_update_required`，`pin_status` 不输出或输出 `skipped_update_required`，并且必须打印上面的更新命令。

如果 `mcp_probe=tool_not_found_reload_required`，最后提示用户：在当前会话中运行 `/reload-plugins` 后重新 `/wiki-cloud-mount`。
