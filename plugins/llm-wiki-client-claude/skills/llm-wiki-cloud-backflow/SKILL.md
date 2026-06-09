---
name: llm-wiki-cloud-backflow
description: 任务结束后使用。无参数触发，由 agent 判断 task slug 和 workspace，在本地归档真实任务轨迹；如配置 LLM_WIKI_UPLOAD_TOKEN 则通过私有 HTTP 入口上传。
allowed-tools: Bash Read Write
version: 1.2.1
---

# LLM-Wiki Backflow

本 skill 包含 **轨迹归档** 和 **轨迹上传** 具体操作。MCP 查询仍是匿名读取；backflow 上传走私有 token-gated HTTP 入口。

```text
llm-wiki-cloud-backflow
    |
    +--> 1. 轨迹归档：把本次任务整理成本地目录 .llm-wiki/backflow/<task-slug>/
    |     （顶层 <task-slug>.md + workspace/ 等附件）
    |
    +--> 2. 轨迹上传：归档汇报后经用户确认，如配置 LLM_WIKI_UPLOAD_TOKEN，
          把归档目录打包成 tar.gz 并 POST 到 https://wiki.andykong.top/upload/backflow
```

## 1. 轨迹归档

轨迹归档在本地完成，不要求用户提供参数。agent 根据当前任务上下文判断 `task-slug` 和 workspace。

### 1.1 判断 Task Slug 和 Workspace

`task-slug` 固定为：

```text
<YYYY-MM-DD>-<short-ascii-description>
```

判断顺序：

- 如果当前任务已有明确 slug，直接使用。
- 否则从当前 `progress.md` 标题、当前 git branch、最近用户任务描述、workspace 目录名中推断一个短 slug。
- slug 必须使用小写 ASCII、数字和短横线；非字母数字统一转成 `-`。
- 如果多个 slug 都合理但会影响后续可读性或上传目录辨识度，先问用户确认。
- 如果本地已存在同名 `.llm-wiki/backflow/<task-slug>/`，给 slug 追加短后缀用作区分。

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
- 任务中实际使用过 git、或 git 状态影响结论时，按需保存 git 证据快照，作为普通 workspace 材料
- 小型 benchmark 摘要、profiling 摘要、结论截图或文本报告
- 与当前任务相关的 `.agents-log/summary/<timestamp>/` 目录（如果存在）
- 如果没有相关 `.agents-log` summary，可用 `session-extractor` skill 补齐同形态的 agent log summary

默认排除：

- profiler raw data、benchmark dump、模型权重、数据集
- 构建产物、依赖目录、缓存目录、虚拟环境
- 大体积二进制文件
- credentials、tokens、keys、`.env*`
- `.git/`、`.idea/`、`.vscode/`、`.llm-wiki/backflow/`（不要复制 `.git/` 目录；任务需要 git 证据时按第 1.4 节导出成小文本/patch）
- `workspace/agents-log/meta/` 默认不纳入 archive/upload；只有当前任务确实需要详细取证或外溢材料时才保留，并在 `Notes` 说明原因

如果被排除的材料有证据价值，在 `<task-slug>.md` 的 `Notes` 中写清原路径、原因、摘要和可访问位置；不要把大文件硬塞进上传。

### 1.3 纳入任务轨迹

在 workspace 中查找 `.agents-log/summary/`，根据当前任务时间、workspace、任务记录和最近相关 session，识别并归档与当前任务相关的 agent log summary。

处理规则：

- 找到一个或多个相关 session 记录：全部复制到 archive 的 `workspace/agents-log/summary/` 下，保留原 timestamp 目录名和内部结构。
- 如果 summary 目录中包含 `.DS_Store`、AppleDouble `._*`、缓存或临时文件，复制时排除。
- 如果没有找到相关 `.agents-log` summary：触发或使用 `session-extractor` skill，以 structured 模式导出当前会话到 archive 的 `workspace/agents-log/`。
- fallback 成功后，后续仍按 `workspace/agents-log/summary/<timestamp>/` 记录和汇报；只在 `Notes` 中标注它由 `session-extractor` 生成。
- 执行 `session-extractor` 时使用 structured 模式，并把输出根目录设为 `workspace/agents-log/`。
- fallback 生成后，默认只保留 `workspace/agents-log/summary/`；移除或排除 `workspace/agents-log/meta/`，除非当前任务确实需要详细取证或外溢材料。
- 如果 `session-extractor` 失败，不阻塞本地 archive；在顶层 `<task-slug>.md` 的 `Notes` 和最终汇报里写清失败原因。

推荐落盘形态：

```text
.llm-wiki/backflow/<task-slug>/
└── workspace/
    └── agents-log/
        └── summary/
            └── 2026-05-20_09-52-44/
                ├── summary.md
                ├── usage.json
                └── agents/
                    └── main/
                        ├── summary.md
                        └── usage.json
```


### 1.4 创建本地归档

本地归档目录固定为：

```text
.llm-wiki/backflow/<task-slug>/
```

**这个目录的内容就是后续 tar.gz 上传包的根目录**——顶层必有且只能有一个 `.md` 文件（通常是 `<task-slug>.md`），其余文件可以任意命名、任意多级嵌套。

归档目录至少包含：

```text
.llm-wiki/backflow/<task-slug>/
├── <task-slug>.md               # 顶层总览（标题/摘要/目录/Notes）
└── workspace/              # 任务现场材料
    ├── progress.md         # 如有
    ├── wiki_usage.md       # 如有（query skill 写的页面使用记录）
    ├── agents-log/         # .agents-log summary；或 session-extractor fallback 生成的同形态目录
    ├── git/                # 如有：任务中使用 git 后按需导出的证据快照，不包含 .git/
    └── ...
```

- 先创建 `workspace/`，把所有相关的任务材料复制进去（保留必要的子目录结构），默认直接复制任务目录，并排除大文件。
- 只有任务中实际使用过 git、或 git 状态/提交/patch 是证据链的一部分时，才创建 `workspace/git/`；不要因为 workspace 是 git 仓库就自动导出 git 证据。
- 不复制 `.git/` 目录；只保存和当前任务相关的小型证据文件，下面是候选项，不要求全部保存：
  - `head.txt`：需要标识仓库根目录、当前分支或当前 HEAD 时，保存 `git rev-parse --show-toplevel`、`git branch --show-current`、`git rev-parse HEAD`
  - `status.txt`：需要说明 dirty state、分支状态或未跟踪文件时，保存 `git status --short --branch`
  - `diff.patch`：任务涉及未暂存工作区改动时，保存 `git diff --no-ext-diff -- .`
  - `diff-cached.patch`：任务涉及已暂存改动时，保存 `git diff --cached --no-ext-diff -- .`
  - `recent-log.txt`：任务依赖最近提交或历史关系时，保存 `git log --oneline --decorate -n 20`
  - `remotes.txt`：只有 remote 身份对任务有证据价值时才保存；如果 URL 含凭据、token 或私有入口，省略或改写后再归档
- 如有相关 agents-log summary，按第 1.3 节复制到 `workspace/agents-log/summary/`；没有时按第 1.3 节使用 `session-extractor` fallback。
- **不要**在归档目录里放真正的二进制（模型权重、profiler raw、大压缩包）。

### 1.5 编写顶层 <task-slug>.md

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

## Git Evidence

实际保存的 `workspace/git/` 证据文件路径（如有）

## Agents Log Summary

`workspace/agents-log/summary/<timestamp>/summary.md` 路径（如有）

## Archive Layout

```text
backflow/<task-slug>/
├── <task-slug>.md
└── workspace/
    ├── progress.md
    ├── wiki_usage.md
    ├── git/              # 如有，按需保存；下列文件不要求全部存在
    │   ├── head.txt
    │   ├── status.txt
    │   ├── diff.patch
    │   ├── diff-cached.patch
    │   └── recent-log.txt
    ├── agents-log/
    │   └── summary/
    │       └── <timestamp>/
    │           ├── summary.md
    │           ├── usage.json
    │           └── agents/...
    └── ...
```

## Notes

- 未归档的大文件、raw profiler、数据集、模型权重等在这里说明原路径、排除原因和可访问位置
- 没有 `progress.md` 或任务轨迹不完整时，在这里说明证据链状况
- 如果任务中使用了 git，记录本次实际纳入了哪些 git 证据文件；如果 `.git/` 未归档，不需要解释，只有需要但无法导出 git 证据时才说明原因
- 记录本次纳入了哪些 `.agents-log/summary/<timestamp>/`；如果未找到相关 summary，说明是否使用了 `session-extractor` fallback 以及输出路径或失败原因

````

没有 `progress.md` 或等价任务记录时，必须在 `Summary` 或 `Notes` 说明证据链不完整——server 端 ingest 会据此判断是否走 `to_review` 路径。

### 1.6 汇报并等待确认

轨迹归档完成后，向用户汇报：

- 本地 archive 路径 `.llm-wiki/backflow/<task-slug>/`
- 顶层 `<task-slug>.md` 一句话总结 + 文件大小（不复制全文）
- 整个目录的文件清单（`find . -type f` 输出）+ 文件总数 + 总字节
- 如果任务中使用了 git，纳入了哪些 git 证据文件；`.git/` 目录默认不纳入 archive/upload
- 纳入了哪些 `.agents-log/summary/<timestamp>/`；如果没有找到相关 summary，说明是否使用了 `session-extractor` fallback 以及输出路径或失败原因
- 排除了哪些重要文件以及原因
- 即将作为上传 `slug` 的值

轨迹上传只在归档汇报完成并得到用户确认后执行。无论上传是否成功，**不要删除**本地 `.llm-wiki/backflow/<task-slug>/` archive。

## 2. 轨迹上传

上传入口固定为：

```text
https://wiki.andykong.top/upload/backflow
```

测试时可用 `LLM_WIKI_UPLOAD_URL` 覆盖；未设置时使用上面的默认 endpoint。

### 2.1 检查 Token

如果环境变量 `LLM_WIKI_UPLOAD_TOKEN` 不存在或为空，不执行上传；只汇报本地 archive 路径，并提示用户：

```bash
if [ -z "${LLM_WIKI_UPLOAD_TOKEN:-}" ]; then
  echo "LLM_WIKI_UPLOAD_TOKEN is not configured; keeping local archive only."
  echo 'To enable upload, set: export LLM_WIKI_UPLOAD_TOKEN="llmw_<token-from-operator>"'
  exit 0
fi
```

配置方式：

```bash
export LLM_WIKI_UPLOAD_TOKEN="llmw_<token-from-operator>"
```

token 由 operator 通过仓库外渠道发放。不要打印 token，不要把 token 写入 archive、日志、diff 或 README。

### 2.2 打包 tar.gz

如果 token 存在，先校验 `task_slug` 和 archive root，再把 `.llm-wiki/backflow/<task-slug>/` 打成临时 tar.gz。压缩包固定写到 `/tmp/llm-wiki-backflow-upload/<task-slug>.tar.gz`，并且打包内容必须是 archive root 的内容，而不是外层目录本身。

```bash
task_slug="<task-slug>"

if ! printf '%s\n' "$task_slug" | grep -Eq '^[a-z0-9][a-z0-9-]*$'; then
  echo "task_slug must match ^[a-z0-9][a-z0-9-]*$; got: ${task_slug}"
  exit 1
fi

archive_root=".llm-wiki/backflow/${task_slug}"
if [ ! -d "$archive_root" ]; then
  echo "archive root is not a directory: ${archive_root}"
  exit 1
fi

pkg_dir="/tmp/llm-wiki-backflow-upload"
pkg="${pkg_dir}/${task_slug}.tar.gz"

mkdir -p "$pkg_dir"
COPYFILE_DISABLE=1 tar -czf "$pkg" -C "$archive_root" .
```

`COPYFILE_DISABLE=1` 是给 macOS/BSD tar 的必要保护，避免把资源叉写成
`._source.md` 这类 AppleDouble 文件；这些文件会让 server 误判顶层存在多个
`.md`。

打包前后确认：

- archive root 顶层必须恰好有 1 个 `.md` 文件。0 个或多个都会被 server 拒绝。
- 压缩包大小必须 `<= 50 MiB`，超过时不要调用 curl；保留本地 archive，并向用户汇报需要缩减材料。

```bash
top_md_count="$(find "$archive_root" -maxdepth 1 -type f -iname '*.md' | wc -l | tr -d ' ')"
if [ "$top_md_count" != "1" ]; then
  echo "upload root must contain exactly one top-level .md file, got ${top_md_count}"
  exit 1
fi

pkg_bytes="$(wc -c < "$pkg" | tr -d ' ')"
max_bytes=$((50 * 1024 * 1024))
if [ "$pkg_bytes" -gt "$max_bytes" ]; then
  echo "package too large: ${pkg_bytes} bytes > ${max_bytes} bytes"
  exit 1
fi
```

### 2.3 上传

```bash
upload_url="${LLM_WIKI_UPLOAD_URL:-https://wiki.andykong.top/upload/backflow}"

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/llm-wiki-backflow-curl.XXXXXX")"
curl_config="${tmp_dir}/curl.conf"
body_file="${tmp_dir}/response.json"
cleanup_upload_tmp() {
  rm -rf "$tmp_dir"
}
trap cleanup_upload_tmp EXIT HUP INT TERM

printf 'header = "Authorization: %s %s"\n' "Bearer" "$LLM_WIKI_UPLOAD_TOKEN" > "$curl_config"
chmod 600 "$curl_config"

if ! http_code="$(
  curl -sS -X POST "$upload_url" \
    --config "$curl_config" \
    --form-string "slug=${task_slug}" \
    -F "package=@${pkg};type=application/gzip" \
    --output "$body_file" \
    --write-out "%{http_code}"
)"; then
  echo "Upload request failed; local archive is still available at ${archive_root}"
  exit 1
fi

response="$(cat "$body_file")"
case "$http_code" in
  ''|*[!0-9]*)
    printf 'Upload returned invalid HTTP status: %s\nResponse: %s\n' "$http_code" "$response"
    exit 1
    ;;
esac

if [ "$http_code" -ge 400 ]; then
  printf 'Upload failed with HTTP %s\nResponse: %s\n' "$http_code" "$response"
  exit 1
fi
```

不要使用 `set -x` 运行上传命令，避免 shell trace 泄露 header。token 只写入 mode `0600` 的临时 curl config，curl argv 只包含 config 文件路径，不包含 token；`trap` 会清理该临时目录。不要把 token 写入 archive、日志或输出；正常 server 响应不会包含 token。

### 2.4 处理响应

如果本机有 `jq`，用 JSON 字段汇报：

```bash
if command -v jq >/dev/null 2>&1; then
  if ! printf '%s' "$response" | jq -e . >/dev/null; then
    printf 'Upload returned non-JSON response: %s\n' "$response"
    exit 1
  fi
  if ! status="$(printf '%s' "$response" | jq -er '.status // empty')"; then
    printf 'Upload returned JSON without status: %s\n' "$response"
    exit 1
  fi
  case "$status" in
    ok)
      printf 'Upload ok\nid: %s\npath: %s\nentrypoint: %s\n' \
        "$(printf '%s' "$response" | jq -r '.id // "-"')" \
        "$(printf '%s' "$response" | jq -r '.path // "-"')" \
        "$(printf '%s' "$response" | jq -r '.entrypoint // .entry // "-"')"
      exit 0
      ;;
    duplicate)
      printf 'Upload duplicate: server already has this package\nid: %s\npath: %s\n' \
        "$(printf '%s' "$response" | jq -r '.id // "-"')" \
        "$(printf '%s' "$response" | jq -r '.path // "-"')"
      exit 0
      ;;
    error)
      printf 'Upload error\nerror: %s\nmessage: %s\n' \
        "$(printf '%s' "$response" | jq -r '.error // "-"')" \
        "$(printf '%s' "$response" | jq -r '.message // "-"')"
      exit 1
      ;;
    *)
      printf 'Upload returned unexpected JSON: %s\n' "$response"
      exit 1
      ;;
  esac
else
  printf 'Upload response was not parsed because jq is unavailable: %s\n' "$response"
  echo "Install jq or inspect the response manually; treating upload as unverified."
  exit 1
fi
```

| 返回 | 处理 |
|---|---|
| `status: ok` | 汇报 server id、path、entrypoint；说明 server 已把包发布到 `uploaded/` 队列，ingest 异步接力，不需要等待。**不删除**本地 archive。 |
| `status: duplicate` | 汇报已存在的 server id/path，并说明 server already has this package；不重试，**不删除**本地 archive。 |
| `status: error` | 原样汇报 `error` 和 `message`；保留本地 archive，按 message 修正后再由用户决定是否重试。 |
| 非 JSON 或无法解析 | 打印简短 raw response（不得包含 token），说明本地 archive 仍保留。 |

不要伪造成功响应；不要对 `status: error` 的响应抑制错误信息后伪装成功。
