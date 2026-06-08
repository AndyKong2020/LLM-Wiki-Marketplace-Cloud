"""session-extractor core package.

把不同 agent 平台（Claude Code / Codex / Opencode）的会话记录归一化成一个统一的
中间表示（IR），再由平台无关的渲染器输出 structured / flat 两种 Markdown 布局。

模块边界：
- ir       归一化中间表示（Session / Agent / Event / Block / Usage）
- util     纯函数工具（时间戳、slug、序列化、截断）
- discover 平台探测 + 当前 session 定位（env 优先，缺权威信号即 fail loud）
- adapters 各平台「原始记录 -> IR」的适配器
- render   IR -> Markdown（structured / flat）+ 大内容外溢
- state    per-session 幂等状态（产物相对路径复用）+ 文件锁
"""

__version__ = "0.1.0"
