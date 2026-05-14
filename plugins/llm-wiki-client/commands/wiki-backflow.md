---
description: 创建本地 CANN-Infer-Wiki backflow archive 并通过 MCP 上传任务轨迹
allowed-tools: Bash Read Write mcp__cann-infer-wiki__wiki_submit_trajectory
---

使用 `llm-wiki-backflow` skill 为当前任务创建本地 backflow archive 并回流到 wiki。

本 command 不直接运行脚本。`llm-wiki-backflow` skill 按两步执行：先在 `.claude/llm-wiki/backflow/<task-slug>/` 做轨迹归档，再在用户确认后调用 `mcp__cann-infer-wiki__wiki_submit_trajectory` 一次性把整个目录送进 server。

不要解析命令参数。`task-slug` 和 workspace 由 `llm-wiki-backflow` skill 根据当前任务上下文判断；`session_id` 直接用 task-slug。
