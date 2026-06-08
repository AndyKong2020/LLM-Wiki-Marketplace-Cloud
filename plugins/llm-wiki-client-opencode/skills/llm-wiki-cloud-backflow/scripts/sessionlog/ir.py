"""归一化中间表示（IR）。

所有平台的原始记录都被适配器映射到这组结构，渲染器只认 IR、不认任何平台细节。
这是「一套渲染器服务三平台」的关键。字段尽量是平台公约数，平台特有信息保留在
``Event.raw`` 里，详细视图按需做通用 JSON 折叠展示。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Block.type 取值
BLOCK_TEXT = "text"
BLOCK_THINKING = "thinking"
BLOCK_TOOL_USE = "tool_use"
BLOCK_TOOL_RESULT = "tool_result"
BLOCK_IMAGE = "image"
BLOCK_RAW = "raw"

# Event.kind 取值（高层语义，跨平台统一）
KIND_USER = "user"
KIND_ASSISTANT = "assistant"
KIND_SYSTEM = "system"
KIND_SUMMARY = "summary"
KIND_META = "meta"

# Agent.kind 取值
AGENT_MAIN = "main"
AGENT_SUBAGENT = "subagent"


@dataclass
class Usage:
    """平台无关的用量。缺失字段保持 0/None，可相加聚合。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 6),
        )

    def is_empty(self) -> bool:
        return (
            self.input_tokens == 0
            and self.output_tokens == 0
            and self.cache_read_tokens == 0
            and self.cache_creation_tokens == 0
            and self.reasoning_tokens == 0
            and self.cost_usd == 0.0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass
class Block:
    """一条消息里的一个内容块。不同 type 用到不同字段。"""

    type: str
    text: str | None = None          # text / thinking 的正文
    name: str | None = None          # tool_use 的工具名
    tool_id: str | None = None       # tool_use 自身 id
    tool_use_id: str | None = None   # tool_result 指向的 tool_use id
    is_error: bool | None = None     # tool_result 是否错误
    value: Any = None                # 结构化载荷：tool 输入、tool 结果内容、raw
    media_type: str | None = None    # image 媒体类型
    data_b64: str | None = None      # image base64 数据


@dataclass
class Event:
    """时间线上的一个归一化事件。"""

    seq: int
    timestamp: datetime | None
    kind: str
    role: str | None = None
    blocks: list[Block] = field(default_factory=list)
    usage: Usage | None = None
    model: str | None = None
    source_path: str | None = None
    source_line: int | None = None
    label: str | None = None         # 平台原始事件类型，如 'file-history-snapshot'
    is_main: bool = False            # 是否属于主 agent（由适配器按归属 agent.kind 置位）
    raw: Any = None                  # 原始记录，供详细视图通用折叠


@dataclass
class Agent:
    """一个 agent 视角（主 agent 或某个 subagent）。"""

    key: str                         # 稳定 slug，主 agent 固定 'main'
    raw_id: str
    kind: str                        # AGENT_MAIN / AGENT_SUBAGENT
    parent_key: str | None = None
    title: str | None = None
    events: list[Event] = field(default_factory=list)

    def first_ts(self) -> datetime | None:
        for event in self.events:
            if event.timestamp is not None:
                return event.timestamp
        return None

    def last_ts(self) -> datetime | None:
        latest: datetime | None = None
        for event in self.events:
            if event.timestamp is not None and (latest is None or event.timestamp > latest):
                latest = event.timestamp
        return latest

    def usage_total(self) -> Usage:
        total = Usage()
        for event in self.events:
            if event.usage is not None:
                total = total + event.usage
        return total

    def models(self) -> list[str]:
        return sorted({event.model for event in self.events if event.model})

    def counts(self) -> dict[str, int]:
        counter: Counter[str] = Counter(event.kind for event in self.events)
        return dict(counter)


@dataclass
class Session:
    """一次完整会话（含其全部 agent 视角）。适配器的产出、渲染器的输入。"""

    platform: str
    session_id: str
    title: str
    summary: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    started_at: datetime | None = None
    last_event_at: datetime | None = None
    source_paths: list[str] = field(default_factory=list)
    agents: list[Agent] = field(default_factory=list)
    raw_meta: dict[str, Any] = field(default_factory=dict)
    # 平台无关的「补充指标」(label, value)，由适配器格式化好（如 claude 的 telemetry）。
    # 渲染器只 extend，不解释其语义 —— 保持 render 平台无关。
    extra_metrics: list[tuple[str, Any]] = field(default_factory=list)

    def main_agent(self) -> Agent | None:
        for agent in self.agents:
            if agent.kind == AGENT_MAIN:
                return agent
        return self.agents[0] if self.agents else None

    def all_events(self) -> list[Event]:
        """跨 agent 合并后的时间线（按时间戳 + seq 稳定排序）。"""
        events = [event for agent in self.agents for event in agent.events]
        return sorted(
            events,
            key=lambda e: (e.timestamp.timestamp() if e.timestamp else float("inf"), e.seq),
        )

    def models(self) -> list[str]:
        models: set[str] = set()
        for agent in self.agents:
            models.update(agent.models())
        return sorted(models)

    def usage_total(self) -> Usage:
        total = Usage()
        for agent in self.agents:
            total = total + agent.usage_total()
        return total
