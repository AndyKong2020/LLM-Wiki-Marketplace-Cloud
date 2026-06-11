---
name: session-extractor
description: 把当前 agent 会话记录按需导出为 Markdown 到 .session-extractor/ 目录。当用户想保存、归档、快照当前会话，把对话/交互记录转成 markdown，生成 session log，或导出 transcript 时使用。支持 structured（默认，带 meta/summary 结构）与 flat（每 agent 一个大 md）两种形态、多次触发增量幂等、多 agent/subagent；跨 Claude Code / Codex / Opencode 三平台，自动判断当前客户端。
allowed-tools: Bash Read Write
version: 1.3.3
---

# Session Extractor

把**当前会话**（或本项目历史会话）的原始记录转成结构化 Markdown，落到工作目录下的 `.session-extractor/`。
非实时、无 hook：主动触发，可多次触发增量刷新（同一 session 始终写到同一目录，幂等覆盖）。

何时用：用户说「把这次会话存成 markdown / 归档 / 快照 / 导出 transcript / 生成 session log」。

---

## 工作流：三步路由

按顺序走完三步，得到 `<platform>` 与 `<mode>`，最后执行脚本。

### 第 1 步 · 路由客户端 `<platform>`（你自行判断）

**你正运行在某个客户端里，你自己清楚是哪个**——直接据此判定，不要靠脚本猜环境变量：

| 你是…… | `<platform>` |
|---|---|
| **Claude Code** | `claude` |
| **Codex** | `codex` |
| **Opencode** | `opencode` |

执行时**显式把它传给 `--platform <platform>`**。

- 若要导出的不是当前客户端、而是别处的历史会话，就按那份会话所属的平台填。
- 省略 `--platform` 时脚本会退回「按环境变量自动猜测」并打印提示——但**首选你自行判断并显式传入**：更可靠，且避免嵌套环境（如一个客户端里启动另一个）下的歧义。
- 当前会话的定位：claude 用权威 session id；codex/opencode 无 session-id env，按 cwd 最近活跃推断并打印警告，精确指定用 `--session <id>`。

→ 产出：`<platform>`（你判断得出）。

### 第 2 步 · 路由输出形式 `<mode>`

| 形式 | 选它当…… | 产物 |
|---|---|---|
| **structured**（默认） | 想要可导航的结构、人读总览与详细/取证分离、给下游工具消费 | `summary/` + `meta/` 双树 |
| **flat** | 想要每个 agent 一个**自包含大 md**，便于整篇阅读或搬运 | 每 agent 一个 `<key>.md` |
| **both** | 两者都要 | 同时产出 |

- 用户没特别说 → 用 **structured**。
- 用户说「一个文件 / 整篇 / 平铺 / 一个大 md」→ 用 **flat**。

→ 产出：`<mode>`（默认 `structured`）。

### 第 3 步 · 执行对应脚本

```bash
python3 <session-extractor-skill-dir>/scripts/extract.py --platform <platform> --mode <mode> [--all | --session <id>]
```

`--platform` 用你第 1 步自行判断的结果显式传入。

- `<session-extractor-skill-dir>` 是当前 `session-extractor` skill 所在目录；如果客户端没有暴露 skill 目录，先在已安装插件/skill cache 中找到 `skills/session-extractor/scripts/extract.py`。
- 默认导出**当前会话**到 `<cwd>/.session-extractor`；用 `--out DIR` 改目录。
- 脚本会：探测平台/定位 transcript → 解析（含 subagent、telemetry）→ 渲染 → **打印落点**。把落点回报给用户。
- 退出码非 0 表示失败（如未显式指定 `--platform` 且 env 无法判断 / 找不到 session / 平台数据目录不存在 / `--session` 不存在）——把脚本的报错原样转达，不要掩盖。

**示例**（`<platform>` 用你自判的结果，下面以 claude 为例）：
- 默认（当前会话，structured）：`python3 .../extract.py --platform claude`
- 平铺：`python3 .../extract.py --platform claude --mode flat`
- 两种都要：`python3 .../extract.py --platform claude --mode both`
- 本项目全部历史会话：`python3 .../extract.py --platform claude --all`
- 指定某会话：`python3 .../extract.py --platform claude --session <id>`

---

## 参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `--mode structured\|flat\|both` | 输出形态（第 2 步） | `structured` |
| `--platform claude\|codex\|opencode` | 你第 1 步自判的客户端（**首选显式传**）；省略则回退 env 自动探测 | 建议显式 |
| `--out DIR` | 输出根目录 | `<cwd>/.session-extractor` |
| `--session ID` | 指定某个 session | 当前会话（env） |
| `--all` | 导出本项目（cwd）全部历史会话 | 否 |
| `--config-dir DIR` | 覆盖平台配置/数据目录 | 按各平台 env+约定 |
| `--cwd DIR` | 覆盖工作目录（影响 `--all`/最近会话推断的 cwd 匹配与默认输出目录） | 当前目录 |
| `--quiet` | 只在出错时输出 | 否 |

## 输出结构

**structured（默认）**——贴合原版双树（结构对齐 `.agents-log`，无 `<platform>` 层）：
```
.session-extractor/
├─ summary/<时间戳>/                            # 人读总览（单时间戳，无 platform 层）
│  ├─ summary.md  usage.json
│  └─ agents/<key>/{summary.md,usage.json}     # 外溢复用 meta 的 artifacts、自身无 rendered
└─ meta/                                       # 详细+取证+索引+状态
   ├─ index.md                                 # 全局索引（所有会话）
   ├─ state/<platform>__<sid>.json             # 幂等状态（产物相对路径）
   ├─ locks/                                   # 会话级文件锁
   └─ sessions/YYYY/MM/<sid>/                  # 无 platform 层；sid 全局唯一
      ├─ index.md   merged/session.md          # 跨 agent 合并时间线
      ├─ agents/<key>/session.md               # 每 agent 详细时间线
      └─ artifacts/{shared,<key>}/rendered/    # 大内容外溢（summary 与 detail 共用）
```

**flat**——每 session 一目录、每 agent 一个自包含大 md：
```
.session-extractor/<时间戳>/
├─ index.md   main.md   <subagent>.md   usage.json
```
（flat 目录与 `meta/`、`summary/` 平级、无 platform 层；也共用 `meta/state/`、`meta/index.md` 做状态与全局索引。）

flat 的 `main.md`/`<subagent>.md` 是**人读的完整详细流水**：元信息 + Usage + 一条详细 Timeline（每条事件含 role/model/usage，**工具输入/输出完整内联、不截断、不外溢**）。会**过滤掉记账/元事件**（hook 输出 attachment、mode、permission-mode、ai-title、file-history-snapshot、last-prompt、非错误级 system），只留对话/工具/错误。需要逐条取证完整（含全部记账事件）请看 `meta/`。

summary/agent summary 行为对齐 `.agents-log`：每段超阈值（文本 4000 / 工具结果 1200，超出截断到 ~400 字符）外溢成 **meta 树**的 `rendered/` 文件并留跨树链接（summary 树自身不含 artifacts，与 `.agents-log` 一致）；agent summary 含 `Detailed log`、`Detailed index` 两个到 meta 的链接。

## 行为约定

- **只读**原始会话数据，绝不修改。
- 平台与 session 身份**优先取自继承的环境变量**；缺权威信号时**直接报错**并提示用 `--session`，不静默猜测。
- 大段文本 / 结构化对象 / base64 图片超阈值会**外溢**成 `rendered/` 文件，正文留摘要+相对链接。
- 坏数据不致命：无法解析的行计入 `parse_warnings` 并在文档里提示，不静默丢弃。
- **同秒碰撞防护**：summary/flat 用时间戳目录名；两会话 `started_at` 撞同一秒时，后到者靠各目录的 `.owner`（`platform__sid`）识别归属、自动加 `__<sid>` 后缀，绝不互毁（meta 树按 sid 命名本就不撞）。
