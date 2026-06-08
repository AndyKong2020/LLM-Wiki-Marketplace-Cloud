"""per-session 幂等状态 + 会话级文件锁。

state 是「可选的优化与稳定层」，不是正确性的来源：
- 记录上次写出的各产物相对路径，下次复用 -> 同一 session 永远写到同一目录，不漂移。
- 缺失（首次运行）是正常的；损坏则 *显式告警* 后当作缺失重建（可见，不静默吞掉）。
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - 非 POSIX
    fcntl = None  # type: ignore

STATE_VERSION = 1


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[session-extractor] 警告：state 文件损坏，将重建（{path}）：{exc}", file=sys.stderr)
        return {}
    return payload if isinstance(payload, dict) else {}


def save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


@contextmanager
def session_lock(lock_dir: Path, session_id: str) -> Iterator[None]:
    """同一 session 的并发触发用排他锁串行化。无 fcntl 时退化为 no-op。"""
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{session_id}.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
