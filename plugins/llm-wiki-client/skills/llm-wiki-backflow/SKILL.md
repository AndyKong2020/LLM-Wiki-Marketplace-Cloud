---
name: llm-wiki-backflow
description: 任务结束后使用。无参数触发，由 agent 判断 task slug 和 workspace，先在本地归档真实任务轨迹，再在用户确认后通过 MCP wiki_submit_trajectory 直接回流到 CANN-Infer-Wiki。
allowed-tools: Bash Read Write mcp__cann-infer-wiki__wiki_submit_trajectory
version: 0.2.0
---

# LLM-Wiki Backflow

本 skill 包含 **轨迹归档** 和 **轨迹上传** 的具体操作。

```text
/wiki-backflow
    |
    +--> 1. 轨迹归档：把本次任务整理成本地目录 .claude/llm-wiki/backflow/<task-slug>/
    |     （顶层 <task-slug>.md + workspace/ 等附件）
    |
    +--> 2. 轨迹上传：用户确认后，调用 wiki_submit_trajectory MCP 工具，
          单次把整个目录上传到 CANN-Infer-Wiki 的 sources/sessions/uploaded/<session_id>/
```

## 1. 轨迹归档

轨迹归档在本地完成，不要求用户提供参数。agent 根据当前任务上下文判断 `task-slug` 和 workspace。

### 1.1 判断 Task Slug 和 Workspace

不要要求 `/wiki-backflow` 传入参数。流程核心是确定 `task-slug`，不是确定 task name。

`task-slug` 固定为：

```text
<YYYY-MM-DD>-<short-ascii-description>
```

判断顺序：

- 如果当前任务已有明确 slug，直接使用。
- 否则从当前 `progress.md` 标题、当前 git branch、最近用户任务描述、workspace 目录名中推断一个短 slug。
- slug 必须使用小写 ASCII、数字和短横线；非字母数字统一转成 `-`。
- 如果多个 slug 都合理但会影响后续可读性或 `session_id` 唯一性，先问用户确认。
- 如果本地已存在同名 `.claude/llm-wiki/backflow/<task-slug>/`，给 slug 追加短后缀用作区分。

workspace 判断：

- workspace 优先选择当前 Claude Code 项目目录。
- 如果当前任务明显在某个子目录完成，则选择该子目录。
- 如果存在多个同样可信的 workspace，且选错会导致归档范围明显不同，先问用户确认。

### 1.2 判断应归档的材料

归档目标是保留后续服务端生成 proposal 所需的证据。

优先纳入：

- `progress.md` 或等价任务记录
- `wiki_usage.md`
- 任务相关源码、配置、小型脚本、README、命令记录
- 任务侧 patch、diff、git status，作为普通 workspace 材料保存
- 小型 benchmark 摘要、profiling 摘要、结论截图或文本报告

默认排除：

- profiler raw data、benchmark dump、模型权重、数据集
- 构建产物、依赖目录、缓存目录、虚拟环境
- 大体积二进制文件
- credentials、tokens、keys、`.env*`
- `.git/`、`.idea/`、`.vscode/`、`.claude/llm-wiki/backflow/`（避免递归归档）

如果被排除的材料有证据价值，在 `<task-slug>.md` 的 `Notes` 中写清原路径、原因、摘要和可访问位置；不要把大文件硬塞进上传。

### 1.3 创建本地归档

本地归档目录固定为：

```text
.claude/llm-wiki/backflow/<task-slug>/
```

**这个目录的内容就是后续会被 `wiki_submit_trajectory` 一次性上传的"文件清单"**——顶层必有 `<task-slug>.md`，其余文件可以任意命名、任意多级嵌套。Server 端会原样保留树结构落到 `sources/sessions/uploaded/<session_id>/`，再由 ingest 加工。


归档目录至少包含：

```text
.claude/llm-wiki/backflow/<task-slug>/
├── <task-slug>.md               # 顶层总览（标题/摘要/目录/Notes）
└── workspace/              # 任务现场材料
    ├── progress.md         # 如有
    ├── wiki_usage.md       # 如有（query skill 写的页面使用记录）
    └── ...
```

- 先创建 `workspace/`，把所有相关的任务材料复制进去（保留必要的子目录结构），默认直接复制任务目录，并排除大文件。
- 如果 workspace 是 git 仓库，可以把 `git status --short` 或 `git diff --no-ext-diff -- .` 保存为普通 workspace 文件。
- 不固定创建 `patches/` 目录；是否保存 diff、保存到哪里，根据当前任务判断。
- **不要**在归档目录里放真正的二进制（模型权重、profiler raw、大压缩包）。

### 1.4 编写顶层 <task-slug>.md

`<task-slug>.md` 是上传时强制要求的顶层入口，务必写得完整自包含。

推荐结构：

````md
---
title: "<display title>"
domain: cann-infer
created_at: <YYYY-MM-DD>
updated_at: <YYYY-MM-DD>
tags: [<场景/优化阶段/相关模型族等关键 tag>]
---

# <display title>

## Summary


## Task Trace

`workspace/progress.md` 路径（如有）

## Wiki Usage History

`workspace/wiki_usage.md` 路径（如有）

## Archive Layout

```text
backflow/<task-slug>/
├── <task-slug>.md
└── workspace/
    ├── progress.md
    ├── wiki_usage.md
    └── ...
```

## Notes

- 未归档的大文件、raw profiler、数据集、模型权重等在这里说明原路径、排除原因和可访问位置
- 没有 `progress.md` 或任务轨迹不完整时，在这里说明证据链状况

````

没有 `progress.md` 或等价任务记录时，必须在 `Summary` 或 `Notes` 说明证据链不完整——server 端 ingest 会据此判断是否走 `to_review` 路径。

### 1.5 汇报并等待确认

轨迹归档完成后，向用户汇报：

- 本地 archive 路径 `.claude/llm-wiki/backflow/<task-slug>/`
- 顶层 `<task-slug>.md` 一句话总结 + 文件大小（不复制全文）
- 整个目录的文件清单（`find . -type f` 输出）+ 文件总数 + 总字节
- 排除了哪些重要文件以及原因
- 即将作为 `session_id` 的值

在用户确认前，不进入轨迹上传。

## 2. 轨迹上传

轨迹上传只在用户确认后执行。上传走 MCP 工具 `wiki_submit_trajectory`——单次调用把整个 `backflow/<task-slug>/` 目录的文件原样送到 server 端的 `sources/sessions/uploaded/<session_id>/`，server 端 monitor 接力跑 ingest pipeline。

不需要 fork、不需要 PR、不需要 GitCode API；MCP 客户端配置由插件 `.mcp.json` 自带，`/wiki-mount` 已确认 MCP 可达。

### 2.1 准备 files 数组

遍历 `.claude/llm-wiki/backflow/<task-slug>/` 下所有文件，构造：

```python
files = [
    {"name": "<rel_posix_path>", "content": "<base64-of-raw-bytes>"},
    ...
]
```

要点：

- `name` 用相对 `backflow/<task-slug>/` 的 posix 路径（如 `<task-slug>.md`、`workspace/progress.md`、`workspace/logs/profile.txt`）
- `name` 不能以 `/` 开头、不能含 `..` 段（server 端会拒）
- `content` 一律是 base64 编码的字节（文本或二进制都用同一编码，server 端字节级还原）
- **顶层必须恰好有 1 个 `.md` 文件**作为入口（命名约定 `<task-slug>.md`；server 端自动发现，不固定文件名），0 个或 ≥2 个均会被 server 拒绝
- 跳过 `.git/`、`.DS_Store`、`__pycache__/`、`*.pyc`、`*.tmp` 等噪声
- 单文件超过 ~5 MB 时停下问用户（base64 后变 ~6.7 MB 流量）

参考实现（Python 片段，agent 视情况实测）：

```python
import base64
from pathlib import Path

root = Path(".claude/llm-wiki/backflow/<task-slug>")
SKIP_DIRS = {".git", "__pycache__"}
SKIP_NAMES = {".DS_Store"}
SKIP_EXTS = {".pyc", ".tmp"}

files = []
for p in sorted(root.rglob("*")):
    if not p.is_file() or p.is_symlink():
        continue
    if any(part in SKIP_DIRS for part in p.parts):
        continue
    if p.name in SKIP_NAMES or p.suffix in SKIP_EXTS:
        continue
    rel = p.relative_to(root).as_posix()
    files.append({"name": rel, "content": base64.b64encode(p.read_bytes()).decode()})

top_md = [f for f in files if "/" not in f["name"] and f["name"].lower().endswith(".md")]
assert len(top_md) == 1, f"upload root must contain exactly 1 top-level .md, got {len(top_md)}: {[f['name'] for f in top_md]}"
assert "/" not in session_id and "\\" not in session_id, f"session_id must not contain path separators: {session_id!r}"
```

### 2.2 调用 wiki_submit_trajectory

```text
mcp__cann-infer-wiki__wiki_submit_trajectory(
    session_id="<task-slug>",
    files=[ ... ]
)
```

`session_id` 直接用 task-slug。Server 端用 `Path(session_id).name` 取 basename 兜底，对空串 / `.` / `..` / 以 `.` 开头的值会显式 reject，但**含 `/` 或 `\` 的值不会报错而是被静默截短**（如 `e2e/case-e` 落到 `uploaded/case-e/`），客户端务必在本地先 assert session_id 无路径分隔符（见 2.1 末尾）。Server 端写入走 `<uploaded>/.staging/<id>/` → 原子 `rename` 到 `<uploaded>/<id>/`，monitor 永远不会看到半成品。

成功返回：

```json
{
    "status": "ok",
    "path": "/.../sources/sessions/uploaded/<task-slug>",
    "file_count": N,
    "total_bytes": M
}
```

### 2.3 处理响应

| 返回 | 处理 |
|---|---|
| `status: ok` | 上传成功。向用户汇报 server 端落盘路径、文件数、字节数；提示 "server 端 monitor 会自动接力 ingest，不需要等待"。**不删除**本地 `.claude/llm-wiki/backflow/<task-slug>/`（用户可能要二次检查） |
| `status: error, message: "session already exists: ..."` | 该 `session_id` 已上传过。问用户：① 用 `-r2`/`-r3` 后缀重起一次 backflow ② 或就此停止 |
| `status: error, message: "upload root must contain exactly one top-level .md file, got ..."` | 顶层 `.md` 文件不是恰好 1 个（0 个或 ≥2 个）。回到 1.4 调整后重试 |
| `status: error, message: "files[i].content invalid base64 ..."` 或 `unsafe path component ...` | 2.1 编码或路径构造出问题，复查 `name` / `content` 字段 |
| MCP 不可达 / 工具不可见 | 告诉用户先跑 `/wiki-mount` 确认 server 就绪后再 `/wiki-backflow`；本地 archive 已经在 `.claude/llm-wiki/backflow/<task-slug>/`，下次直接复用 |

不要伪造成功响应；不要对 `status: error` 的响应抑制错误信息后伪装成功。Server 端 monitor 接力之后用户可以通过 `tail -f <cache>/mcp.log` 观察 ingest 进度（可选）。
