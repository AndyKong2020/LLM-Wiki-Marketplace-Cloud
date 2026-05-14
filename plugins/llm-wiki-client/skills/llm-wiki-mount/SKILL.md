---
name: llm-wiki-mount
description: 为当前项目挂载 CANN-Infer-Wiki（NPU 大模型推理优化知识库）。两阶段执行：① 确保本机 MCP server 可达（必要时 clone 仓库并拉起服务）；② 在项目 CLAUDE.md 写入 LLM-WIKI pin block。MCP 客户端配置由插件 .mcp.json 自动注册，仅支持本机 localhost:5100。
allowed-tools: Bash Read Edit Write
version: 0.4.0
---

# LLM-Wiki Mount

## 1. 概述

`llm-wiki-mount` 把 CANN-Infer-Wiki 的 MCP server 挂载到当前 Claude Code 项目。MCP **客户端配置由插件 root 的 `.mcp.json` 自带**——用户 `claude plugin install llm-wiki-client@llm-wiki` 那一刻就自动注册 `cann-infer-wiki` MCP server；本 skill 不写 `.mcp.json`、不调 `claude mcp add`。

仅支持**本机部署**，URL 固定为 `http://localhost:5100/mcp`。不支持远程 server、不做端口回退、不读环境变量覆盖。

mount 只负责两件事：① 确保本机 MCP server 进程在 5100 端口跑着；② 在项目 `CLAUDE.md` 注入 LLM-WIKI pin block。

固定常量：

```text
repo:      https://gitcode.com/AndyKong2020/CANN-Infer-Wiki.git
ref:       main
cache:     ~/.claude/llm-wiki/repos/cann-infer-wiki/
mcp_url:   http://localhost:5100/mcp
mcp_port:  5100
project:   ${CLAUDE_PROJECT_DIR:-$PWD}
```

整体流程：

```text
/wiki-mount
    |
    v
llm-wiki-mount skill
    |
    +--> STEP 1: 确保 MCP server 在 localhost:5100 跑着
    |       |
    |       +--> 1.1 探活 5100 → 已跑 / 未跑 / 被非 wiki 服务占用
    |       +--> 1.2 (未跑) cache 三态 → clone / ff / 暂停或重建
    |       +--> 1.3 (未跑) 前置检查 (claude CLI / pip / IS_SANDBOX)
    |       +--> 1.4 (未跑) nohup 启动 server
    |       +--> 1.5 MCP RPC probe (调一次 wiki_search)
    |       |
    |       任一步 fail   → STOP，不进 STEP 2，输出诊断
    |       全步 pass     → 进入 STEP 2
    |
    +--> STEP 2: 注入 CLAUDE.md pin block
            |
            +--> 2.1 定位 CLAUDE.md
            +--> 2.2 生成标准 pin block
            +--> 2.3 比对/写入 (created / updated / already_current / broken)
            +--> 2.4 汇报结果
```

## 2. 重要原则

mount 必须幂等。重复调用 `/wiki-mount` 不应破坏已有正确状态；每步都先判"已经是目标态？"再决定是否动手。

mount **不管客户端 MCP 配置**——那是插件 `.mcp.json` 的事。如果用户卸载/禁用了 plugin，整个 MCP entry 会跟着消失，无需 mount 清理。

mount 不要预加载 wiki 内容、不要把 cache 复制进用户项目、不要修改 cache 仓库内的业务文件。客户端永远走 MCP；cache 只是 server 端依赖。

invalid 状态（cache 异常、5100 被非 wiki 服务占用）一律暂停并向用户报告，不要默默覆盖或绕过、也不要换端口/换 URL。

Step 1 任一步骤失败时不要走 Step 2。pin block 写进 CLAUDE.md 但 MCP 不通 → agent 后续调用全部失败，是更糟的失败模式。

## 3. STEP 1：确保 MCP server 在 localhost:5100 跑着

### 3.1 探活 localhost:5100

```bash
curl --noproxy '*' -sI -o /dev/null -w '%{http_code}' --max-time 3 http://localhost:5100/mcp
```

| 返回 | 含义 | 下一步 |
|---|---|---|
| `200`/`401`/`405`/`406` | wiki MCP server 已在跑 | 跳到 3.5 |
| `000`（连不上） | 端口空闲，未跑 | 进 3.2 |
| `502`/`504` 或其它 2xx/3xx | 5100 被非 wiki 服务占用 | **报错并停止**：告诉用户 5100 被占，请杀掉占用进程后重新 `/wiki-mount`；不要换端口 |

curl 一直返回 0/超时但 `ss -tln \| grep :5100` 显示端口被占的情况，等同"被非 wiki 服务占用"分支处理。

如果 curl 一直 0，确认下 shell 没设代理覆盖 localhost：

```bash
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost
```

### 3.2 Cache 三态处理（仅未跑）

```bash
CACHE_ROOT="${HOME}/.claude/llm-wiki/repos"
CACHE_PATH="${CACHE_ROOT}/cann-infer-wiki"
REPO_HTTPS="https://gitcode.com/AndyKong2020/CANN-Infer-Wiki.git"
REF="main"
```

按顺序判 cache 状态：

```bash
# 路径不存在 → missing
test -e "$CACHE_PATH" || echo missing

# 路径存在但不是 git → invalid
test -d "$CACHE_PATH/.git" || echo invalid

# remote 不匹配 → invalid
git -C "$CACHE_PATH" config --get remote.origin.url   # 必须等于 $REPO_HTTPS

# dirty → invalid
git -C "$CACHE_PATH" status --porcelain               # 必须为空

# 与 origin/main 分叉 → invalid；HEAD == origin/main 或可 ff → ready
git -C "$CACHE_PATH" fetch origin "$REF" --prune
git -C "$CACHE_PATH" merge-base --is-ancestor HEAD "origin/$REF"
```

按状态走对应分支：

- **missing**：
  ```bash
  mkdir -p "$CACHE_ROOT"
  git clone --branch "$REF" --single-branch "$REPO_HTTPS" "$CACHE_PATH"
  ```
  clone 失败 → 报错停止 mount，**不要回退 SSH**（HTTPS 是固定协议）。

- **ready 且 HEAD == origin/main**：什么都不做，进 3.3。

- **ready 但 HEAD 落后**：
  ```bash
  git -C "$CACHE_PATH" merge --ff-only "origin/$REF"
  ```
  ff 失败 → 视作 invalid。

- **invalid**：向用户说明具体 invalid 原因（非 git 目录 / remote 不匹配 / dirty / 分叉等），给两个选择：
  - A. 暂停 mount，让用户手工处理 cache 后重新 `/wiki-mount`
  - B. 备份当前 cache 后重新 clone 最新 main

  只有用户选 B 才执行：
  ```bash
  BACKUP_PATH="${CACHE_PATH}.backup.$(date '+%Y%m%d%H%M%S')"
  mv "$CACHE_PATH" "$BACKUP_PATH"
  git clone --branch "$REF" --single-branch "$REPO_HTTPS" "$CACHE_PATH"
  ```

### 3.3 启动前置检查（仅未跑）

任一缺失 → **错误退出，不要自动安装/绕过**，向用户报告缺什么。

```bash
# claude CLI 在 PATH（server 的 claude-agent retriever 模式必备）
which claude || { echo "missing: claude CLI"; exit 1; }

# Python 依赖（全局安装，不创建 venv）
pip install -q -r "$CACHE_PATH/mcp-server/requirements.txt"

# root 部署需要 IS_SANDBOX=1
if [ "$(id -u)" = "0" ] && [ "${IS_SANDBOX:-0}" != "1" ]; then
  echo "missing: 当前以 root 运行但未设 IS_SANDBOX=1。请先 export IS_SANDBOX=1 后重新 /wiki-mount"
  exit 1
fi
```

### 3.4 启动 server（仅未跑）

只在 5100 启动，**不做端口回退**：

```bash
LOG_FILE="$CACHE_PATH/mcp.log"
cd "$CACHE_PATH/mcp-server"
nohup python -u server.py --port 5100 --host 127.0.0.1 \
    > "$LOG_FILE" 2>&1 &
disown $! 2>/dev/null || true
```

等待并校验启动成功：

```bash
sleep 5
grep -E "Uvicorn running" "$LOG_FILE" \
    || { echo "server 起不来，看 $LOG_FILE 末尾 30 行"; exit 1; }
```

`Uvicorn running` 出现且没有 `address already in use` 才算起来。

### 3.5 MCP RPC probe

不要只看 `claude mcp list` 显示 Connected——那只代表 HTTP 握手通，不能发现"工具没注册 / index loader 挂 / retriever 错误"一类暗病。直接调用一次：

```text
mcp__cann-infer-wiki__wiki_search(query="mount probe", limit=1)
```

期望返回 `{results, total}` 且无 `warning` 字段。如：

- 返回 `{results: [...], total: N}` → probe 通过，进 STEP 2
- 返回 `{warning: "..."}` → 输出 warning 原文 + server log 末尾 30 行，停止 mount
- 工具不存在（`mcp__cann-infer-wiki__*` 在 agent 工具列表里看不到） → 让用户在当前会话跑 `/reload-plugins`，reload 完重新 `/wiki-mount`

## 4. STEP 2：注入 CLAUDE.md

### 4.1 定位 CLAUDE.md

```bash
CLAUDE_MD="${CLAUDE_PROJECT_DIR:-$PWD}/CLAUDE.md"
```

不要写到 `.claude/CLAUDE.md`，本 skill 只管理项目根 `CLAUDE.md`。

### 4.2 标准 pin block

```md
<!-- LLM-WIKI:BEGIN -->
本项目已挂载 CANN-Infer-Wiki（NPU Atlas A3 / Ascend910 系列大模型推理优化知识库）。
mcp_url: http://localhost:5100/mcp

涉及下列任务时必须使用 llm-wiki-query skill：
- 静态知识查询：model / kernel / parallelism / module / framework / technique / quantization / platform
  （模型族 qwen3-moe / deepseek-r1 / hunyuan-* / longcat-* / kimi-k2 等；算子 fia / mla / dia / sparse-flash-attention 等；并行 tp / dp / cp / ep / zigzag-cp / ulysses 等；框架 sglang / torchair / pypto / ascendc / atb / catlass / tilelang 等；技术 npu-graph-mode / weight-prefetch / superkernel / afd 等；量化 w8a8c8 / w4a8c8 / mxfp8 / fp8-attention 等；平台 atlas-a3 / ascend910 等）
- 动态知识查询：任务回流型经验，如调试策略、bringup 路径、性能调优梯子
- 进入新优化阶段、做方案分析、策略选择、debug 调试、性能/精度回归归因时

涉及 subagent 拉起时，需让 subagent 同样使用 llm-wiki-query skill。

知识检索一律通过 MCP 工具：mcp__cann-infer-wiki__wiki_search、mcp__cann-infer-wiki__wiki_get_page。
不要预加载或穷举 wiki；不要绕开 MCP 直接读 ~/.claude/llm-wiki/repos/ 下的 cache 文件。

每次使用 llm-wiki-query 后，必须把页面级记录写到当前阶段 progress.md 同级的 wiki_usage.md，
并把查询摘要同步写入 progress.md。
<!-- LLM-WIKI:END -->
```

### 4.3 编辑规则

文件不存在 → 创建 CLAUDE.md，内容就是上述 block，记 `claude_md_status=created`。

文件存在但**不含**任何 LLM-WIKI 标记 → 在文件末尾追加 block（原文末尾如缺空行先补一行），记 `claude_md_status=created`。

文件存在且**同时含** `<!-- LLM-WIKI:BEGIN -->` 与 `<!-- LLM-WIKI:END -->` → 把两者之间的内容与标准 block 内容比对：
- 完全一致 → 记 `claude_md_status=already_current`
- 不一致 → 用标准 block 替换中间内容（不动 BEGIN/END 标记本身的位置），记 `claude_md_status=updated`

文件存在但只含 BEGIN 或只含 END → **停止 mount**，记 `error_code=claude_pin_broken`，让用户先手动修复 CLAUDE.md（pin block 残缺通常意味着外部工具改坏了）。

## 5. 汇报结果

mount 全流程结束后，按顺序输出以下字段（每行一个 `key=value`）：

```text
cache_status=<cloned | updated | already_latest | recloned | aborted>
server_status=<already_running | started | failed>
mcp_probe=<rpc_ok | tool_not_found_reload_required | failed>
claude_md_status=<created | updated | already_current | broken>
cache_path=<absolute cache path>
server_log=<absolute log path>
```

不要展开完整 server log、cache 目录或 wiki index 文件列表。

如果 `mcp_probe=tool_not_found_reload_required`，最后用一行提示用户：在当前会话中运行 `/reload-plugins` 后重新 `/wiki-mount`。
