---
description: 为当前项目挂载云端 CANN-Infer-Wiki MCP（验证远程工具 + 写入 CLAUDE.md pin block）
allowed-tools: Read Edit Write mcp__cann-infer-wiki__wiki_search
---

使用 `llm-wiki-mount` skill 为当前项目执行 mount。

不要解析命令参数。MCP 客户端配置由插件 root `.mcp.json` 自带，URL 固定为云端 `http://124.220.212.101/mcp`；本 command 不 clone wiki 仓、不启动本机 server、不做端口探测。

mount 的执行步骤、远程 MCP probe、pin block 内容、结果汇报全部以 `llm-wiki-mount` skill 为准。
