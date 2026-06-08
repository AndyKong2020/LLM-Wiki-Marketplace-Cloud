"""平台探测 + 跨适配器共享的路径/环境助手。

原则（见 memory: skill-session-discovery / fail-loud-no-masking-fallbacks）：
- 平台与 session 身份优先从继承的 env 取（权威信号）。
- 缺权威信号不静默猜测，直接报错要求显式参数。
- 各平台的「定位」实现在各自适配器的 locate() 里；本模块只做探测与公共助手。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

VALID_PLATFORMS = ("claude", "codex", "opencode")


@dataclass
class SessionRef:
    """一次待解析会话的定位结果（主 transcript + 关联 subagent 文件）。"""

    session_id: str
    main_path: Path
    subagent_paths: list[Path] = field(default_factory=list)


def detect_platform(env: dict[str, str], override: str | None = None) -> str:
    """自动判断当前会话所在的客户端。无法确定即 fail loud。

    嵌套场景（如从 claude 里启动 codex）下，「执行期标识」(CODEX_SANDBOX / OPENCODE_*)
    比 claude 的 session id 更贴近当前执行上下文，故优先判 codex/opencode。
    """
    if override:
        ov = override.lower()
        if ov not in VALID_PLATFORMS:
            raise ValueError(f"未知 --platform '{override}'，可选：{', '.join(VALID_PLATFORMS)}")
        return ov

    claude = bool(env.get("CLAUDE_CODE_SESSION_ID") or env.get("CLAUDECODE"))
    codex = bool(env.get("CODEX_SANDBOX") or env.get("CODEX_THREAD_ID")
                 or env.get("CODEX_MANAGED_BY_NPM") or env.get("CODEX_MANAGED_PACKAGE_ROOT"))
    oc_marker = (env.get("OPENCODE") or env.get("OPENCODE_RUN_ID")
                 or env.get("OPENCODE_SESSION_ID") or env.get("OPENCODE_PID"))
    # OPENCODE_PID 存活性闸门：残留(进程已死)的 OPENCODE_PID 不算数 -> 避免纯 claude 被误判成 opencode。
    opencode = bool(oc_marker) and (not env.get("OPENCODE_PID") or _pid_alive(env.get("OPENCODE_PID")))

    chosen = "codex" if codex else "opencode" if opencode else "claude" if claude else None
    if chosen is None:
        raise RuntimeError(
            "无法从环境变量自动判断当前客户端。请用 --platform claude|codex|opencode 显式指定。"
            "（Claude Code 注入 CLAUDE_CODE_SESSION_ID；Codex 注入 CODEX_SANDBOX/CODEX_THREAD_ID；"
            "Opencode 注入 OPENCODE/OPENCODE_PID —— 此处均未检测到。）"
        )
    # 嵌套环境（claude 与 codex/opencode 标识并存）无法仅靠 env 判定方向 -> 取最内层执行标识并显式告警。
    if chosen != "claude" and claude:
        print(
            f"[session-extractor] 同时检测到 claude 与 {chosen} 客户端标识（疑似嵌套环境），"
            f"判定当前客户端为 {chosen}；如不对请用 --platform 显式指定。",
            file=sys.stderr,
        )
    return chosen


def _pid_alive(pid_str: str | None) -> bool:
    try:
        pid = int(pid_str)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但非本用户
    except OSError:
        return False
    return True
