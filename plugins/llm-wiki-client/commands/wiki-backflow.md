---
description: 创建本地 CANN-Infer-Wiki backflow archive；云端只读 MVP 暂停在上传前
allowed-tools: Bash Read Write
---

使用 `llm-wiki-backflow` skill 为当前任务创建本地 backflow archive。

本 command 不直接运行脚本。当前云端只读 MVP 不暴露 `wiki_submit_trajectory`，所以默认只执行归档并停在上传前；上传流程文档保留在 `llm-wiki-backflow` skill 中，等后续私有上传/鉴权入口接上后再启用。

不要解析命令参数。`task-slug` 和 workspace 由 `llm-wiki-backflow` skill 根据当前任务上下文判断；`session_id` 直接用 task-slug。
