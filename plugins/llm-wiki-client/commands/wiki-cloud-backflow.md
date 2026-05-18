---
description: 创建本地 CANN-Infer-Wiki backflow archive；归档汇报后如用户确认且配置 LLM_WIKI_UPLOAD_TOKEN 则上传，否则仅归档
allowed-tools: Bash Read Write
---

使用 `llm-wiki-cloud-backflow` skill 为当前任务创建本地 backflow archive。

本 command 不直接解析参数。`llm-wiki-cloud-backflow` skill 会创建本地归档并先汇报 archive summary；只有用户确认继续且 `LLM_WIKI_UPLOAD_TOKEN` 已配置时，才把归档打成 tar.gz 并上传到 `https://wiki.andykong.top/upload/backflow`。如果未配置 token，则只创建本地 archive 并提示如何配置。

不要解析命令参数。`task-slug` 和 workspace 由 `llm-wiki-cloud-backflow` skill 根据当前任务上下文判断；上传 `slug` 直接用 task-slug。
