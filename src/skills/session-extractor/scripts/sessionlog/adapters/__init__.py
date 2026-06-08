"""平台适配器：把某平台的原始会话记录解析成归一化 IR（``ir.Session``）。

每个适配器只做「探测实际后端 -> 断言 -> 解析」，不做跨后端的兜底链；
缺数据就抛清晰错误（fail loud），由 CLI 上层呈现给用户。
"""
from __future__ import annotations

from . import claude, codex, opencode

# platform -> 适配器模块（暴露 locate()/parse()）。新增平台只在这里登记。
REGISTRY: dict[str, object] = {
    "claude": claude,
    "codex": codex,
    "opencode": opencode,
}


def get_adapter(platform: str):
    adapter = REGISTRY.get(platform)
    if adapter is None:
        raise ValueError(
            f"未知平台 '{platform}'，可选：{', '.join(sorted(REGISTRY))}"
        )
    return adapter


__all__ = ["REGISTRY", "get_adapter", "claude", "codex", "opencode"]
