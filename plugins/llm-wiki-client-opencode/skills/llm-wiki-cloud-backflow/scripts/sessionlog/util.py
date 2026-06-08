"""平台无关的纯函数工具。无副作用、无平台耦合。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "parse_timestamp",
    "format_timestamp",
    "utcnow",
    "slugify",
    "excerpt",
    "format_int",
    "serialize_value",
    "ms_to_datetime",
    "to_int",
    "make_agent_key",
    "RESERVED_AGENT_KEYS",
]

# 这些是布局里的结构性文件/目录名；subagent key 不得取这些，否则 flat 的 <key>.md
# 会撞上 index.md/usage.json、structured 的 agents/<key> 会撞上结构目录 -> 静默丢数据。
RESERVED_AGENT_KEYS = frozenset({"main", "index", "usage", "merged", "agents", "artifacts", "shared"})


def to_int(value: Any, default: int = 0) -> int:
    """安全转 int：非数字/None 返回 default，不抛。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def make_agent_key(raw_id: str, used: set[str], is_main: bool = False) -> str:
    """生成稳定的 agent key（主 agent 固定 'main'），避开保留名与已用 key。"""
    if is_main:
        return "main"
    base = slugify(raw_id) or "agent"
    candidate = base
    attempt = 1
    while candidate in RESERVED_AGENT_KEYS or candidate in used:
        attempt += 1
        candidate = f"{base}-{attempt:02d}"
    return candidate


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    """把 ISO 字符串 / epoch 秒 / datetime 解析成带时区的 datetime。无法解析返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def ms_to_datetime(value: Any) -> datetime | None:
    """Opencode 时间戳是 epoch 毫秒。"""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-_.")
    return slug.lower()


def excerpt(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def format_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def serialize_value(value: Any) -> tuple[str, str]:
    """把任意值序列化为 (文本, 扩展名)。dict/list -> json，str -> 原样，None -> (empty)。"""
    if value is None:
        return "(empty)", "txt"
    if isinstance(value, str):
        return value, "txt"
    if isinstance(value, (dict, list, tuple, bool, int, float)):
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), "json"
    return str(value), "txt"
