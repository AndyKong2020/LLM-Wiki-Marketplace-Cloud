---
name: llm-wiki-cloud-query
description: 查询和运行时消费已挂载的 CANN-Infer-Wiki（通过 MCP）。进入新的 LLM/NPU 推理优化阶段、做方案分析、策略选择、debug 调试、性能/精度回归分析；涉及具体 model / kernel / parallelism / module / framework / technique / quantization / platform 知识、或动态层任务回流型经验时使用。
allowed-tools: Bash Read Edit Write mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_search mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_get_page
version: 1.1.6
---

# LLM-Wiki Query

## 1. 触发查询的场景

本 skill 是真实任务运行时的 wiki 入口。CLAUDE.md 中由 `/wiki-cloud-mount` 写入的 LLM-WIKI pin block 已经列出"哪些任务阶段必须查 wiki"，不要在临时判断中绕开它。

下列任一情况发生时必须查 wiki：

- 进入新的优化阶段：bringup / profiling / kernel tuning / 并行策略调整 / 显存优化 / 回归定位
- 做方案分析、策略选择、实现路线判断
- debug 调试、性能或精度异常排查、错误模式归因
- 涉及具体模型族（qwen3-moe / deepseek-r1 / hunyuan-* / longcat-* / kimi-k2 等）、算子（fia / mla / dia / sparse-flash-attention 等）、并行策略（tp / dp / cp / ep / zigzag-cp / ulysses 等）、推理框架（sglang / torchair / pypto / ascendc / atb 等）、优化技术（npu-graph-mode / weight-prefetch / superkernel 等）、量化（w8a8c8 / w4a8c8 / mxfp8 等）、硬件平台（atlas-a3 / ascend910）
- 任务初期判断"是否有 wiki 经验可复用"
- subagent 接到任务后，先判断要不要查 wiki

涉及 subagent 时，必须视情况将 llm-wiki-query skill 的使用说明注入到拉起 subagent 的 prompt 中。
每次使用都必须对每个查询到的页面写记录，并把摘要同步到 `progress.md`（见第 4 节）。

## 2. 重要原则

**通过 MCP 查询**。永远通过 `mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_search` 与 `mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_get_page` 获取知识。

`wiki_search` 返回 `warning`（retriever 失败）→ 据实上报给用户与 progress.md。

subagent 使用本 skill 时与主 agent 共用同一份 `wiki_usage.md`，位于当前任务的 `progress.md` 同级目录。

如果需要理解 wiki 图片内容，必须先把 `wiki_get_page` 返回的 `https://wiki.andykong.top/assets/...` 图片 URL 下载到本地临时文件（建议路径 `/tmp/llm-wiki-assets/<page-id>/<filename>`），再用 Read 工具读取该图片；不要仅凭 URL、文件名、alt 文本或页面上下文推断图片内容。

** wiki 页面不是 ground truth **：wiki 页面可能不是绝对正确，你应当把 wiki 当做一位经验丰富的老同事，而不是字典。遇到冲突时，应当以实际发生的事实优先。

## 3. 执行查询（4 步）

### 3.1 拟 query

把当前问题压缩成一段话：

- 用具体的算子/模型族/技术名（`npu_fused_infer_attention_score` / `Qwen3` / `npu-graph-mode`），不要泛泛说"attention 加速"
- 包含场景关键修饰：硬件平台 / 精度 / 并行配置 / 阶段（prefill/decode）
- 短：一般 ≤100 字，不堆长句

示例：

| 原始任务表达 | 改写后的 query |
|---|---|
| "Qwen3-MoE 怎么调优？" | `Qwen3-MoE Atlas A3 BF16 attention TP MoE EP 切分` |
| "decode 慢，看不出哪儿" | `decode 时延高 attention 与 router AllGather 归因` |
| "MLA 和 FIA 怎么选" | `MLA-Prolog 与 npu_fused_infer_attention_score 适用条件对比` |

仅在你**明确知道**问题就限定在某一类知识时才加 `type` 或 `tags` 过滤：

```text
wiki_search(query="...", type="kernel", limit=5)
wiki_search(query="...", tags=["fia", "decode"], limit=5)
```

`type` 取值：`model / kernel / parallelism / module / framework / technique / quantization / platform`，留空覆盖动态层。多个 `tags` 是交集。

否则**不加过滤**——server 端 retriever 跨类型搜往往更稳。

### 3.2 wiki_search

```text
mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_search(query="<上一节拟好的 query>", limit=5)
```

返回 `{results: [{id, summary, tags, score, qValue}, ...], total}`。这就是 server 已经排好序的 topK，**直接用**：

- 看 top-1/top-2 的 `summary` 决定下一步要不要取正文（覆盖问题就取，明显不沾就重写一条 query）
- 取候选页面 ID 进入 3.3

如果 top-1 的 summary 跟问题完全不沾边（说明 query 没写好），**重写 query** 重新调一次；连续多次都不沾边就在 progress.md 记"wiki 暂无相关知识"，停止本次查询。

### 3.3 wiki_get_page

```text
mcp__plugin_llm-wiki-client_cann-infer-wiki-cloud__wiki_get_page(
    ids=["wiki_static_cann-infer_models_qwen3-moe_md", ...]
)
```

返回 `{pages: [{id, content, frontmatter, qValue}], errors: []}`。

- `content`：Markdown 正文
- `frontmatter`：可能含 `source`（溯源）、`contradictions`（矛盾页 ID 列表）、`arch_support` 等
- `errors`：取页失败的 ID（多半是 ID 拼写错或页已归档）。跳过，**不重试**

读 content 时按问题类别看不同段：

- **策略类**：`## Solution` / `## When applicable` / `## Trade-offs`
- **debug 类**：`## Problem` / `## Symptom` / `## Root Cause` / `## Verification`
- **事实类**：API 名、参数表、约束条件
- 若 `frontmatter.contradictions` 非空：必读其中之一了解争议点（再次 `wiki_get_page`）

TODO:链接下探

### 3.4 应用 + 记录

把读到的内容应用到当前任务。如要拉起 subagent ，**在 prompt 里明确要求 subagent 也用 `llm-wiki-cloud-query` skill 和当前任务的 `wiki_usage.md`路径**（路径见 5 节）。

每次 `wiki_get_page` 取过的页都要写到 `wiki_usage.md`（4.1 节）；本次查询对阶段判断有影响时，同步在 `progress.md` 追加 wiki 查阅记录（4.2 节）。

## 4. 页面使用记录格式

### 4.1 wiki_usage.md

**位置**（严格）：

- 优先：当前任务 `progress.md` 同级目录下的 `wiki_usage.md`
- 当前任务还没有 `progress.md` → 在当前任务目录创建 `wiki_usage.md`

**格式**：每个使用过的页面一个一级标题，标题直接用 MCP ID。

```md
# wiki_static_cann-infer_models_qwen3-moe_md

## 原因
为什么读取这个页面（当前阶段在判断什么、出于哪条线索查到这页）

## 效果
这个页面对当前阶段的实际帮助（解决了什么 / 改变了哪个判断 / 排除了哪个假设）

## 分数
- overall: -1 | 0 | +1

## 备注
保留限制、误导点、是否要继续使用、与其它页的关系、页面需要修正的点等

# wiki_dynamic_cann-infer_<slug>_md

...
```

`overall` 必填，取值范围 `{-1, 0, +1}`：
- `+1`：明确推动了任务前进 / 解决了具体问题
- `0`：读了但对当前阶段没产生显著影响（仍记下，避免被反复 re-search）
- `-1`：误导了判断 / 与现实冲突 / 浪费了时间

同一页面被多次使用 → 不要新建重复 header，在已有标题下追加新的原因/效果/备注；分数取最近一次判断（覆盖式更新）。

### 4.2 progress.md 同步

每次使用 wiki 后，在当前阶段 `progress.md` 的小节下追加一条 bullet：

```md
- 查阅：`wiki_static_cann-infer_models_qwen3-moe_md`、`wiki_static_cann-infer_kernels_fused-infer-attention-score_md`
  - 目的：判断 attention TP 切分上限对 decode 时延的影响
  - 结论：4tp + FIA 比 8tp 整体快 35%；KV cache 翻倍但 FIA 单核增益更大
```

## 5. Subagent 规则

subagent 使用本 skill 时必须遵守：

- 与主 agent 共用同一份 `wiki_usage.md`（路径由主 agent 在调用时传入；subagent 不另建）
- 如无写文件权限，subagent 必须在返回给主 agent 时提供可追加的 Markdown 片段（原因/效果/分数/备注按 4.1 格式）
- subagent 返回前**必须**为本次读过的每个页面填 `overall` 分数；主 agent 不替 subagent 补分
- subagent 最终回复带上 `wiki_usage.md` 路径、本次新增/更新的页面 ID 列表

## 6. 主 Agent 规则

主 agent 每进入一个新阶段、使用了 wiki 后：

- 在该阶段 `progress.md` 同级写/补 `wiki_usage.md`（4.1 节）
- 阶段结束时复盘本阶段读过的页面，确认每条 `overall` 分数是否仍准确，必要时调整
- 整理 subagent 返回的 Markdown 片段追加到同一份 `wiki_usage.md`，但**不要改写** subagent 已写的原因/效果/分数

## 7. 错误处理

| 现象 | 处理 |
|---|---|
| `wiki_search` 抛错 `MCP server unreachable` 或工具不可见 | 不要伪造结果。提示用户运行 `/wiki-cloud-mount` 或 `/reload-plugins`，停止本次查询 |
| `wiki_search` 返回 `{warning: "..."}`（retriever 失败） | 把 warning 原文写到 `progress.md` "Wiki 查询记录"段；本次查询作废，不继续 get_page |
| `wiki_get_page` 返回 `errors=[{id, reason}]` | 跳过这些 ID（多半是已归档或拼写错）；不重试 |
| top-1 候选 summary 完全不沾边 | 重写 query 再试一次；最多重试 1 次仍不沾边 → progress.md 记"wiki 暂无相关知识"，停止 |
| `wiki_search` 返回 `total=0` | progress.md 记一笔"wiki 暂无相关知识"；继续任务一般流程 |
