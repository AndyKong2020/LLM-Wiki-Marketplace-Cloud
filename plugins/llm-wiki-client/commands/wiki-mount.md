---
description: 为当前项目挂载 CANN-Infer-Wiki MCP server（确保本机 localhost:5100 可达 + 写入 CLAUDE.md pin block）
allowed-tools: Bash Read Edit Write
---

使用 `llm-wiki-mount` skill 为当前项目执行 mount。

不要解析命令参数。MCP 客户端配置由插件 root `.mcp.json` 自带，URL 固定 `http://localhost:5100/mcp`，不支持远程 server、不支持端口覆盖、不读环境变量。需要换部署位置请直接改插件源 `.mcp.json` 后 `/reload-plugins`。

mount 的执行步骤、cache 三态处理、server 进程管理、pin block 内容、结果汇报全部以 `llm-wiki-mount` skill 为准。
