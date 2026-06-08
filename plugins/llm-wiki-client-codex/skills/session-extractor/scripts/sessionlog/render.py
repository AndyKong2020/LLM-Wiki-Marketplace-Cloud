"""IR -> Markdown 渲染。完全平台无关：只认 ir.Session / Agent / Event / Block。

两种布局：
- structured（默认）：贴合原版双树 —— summary/（人读总览+按 agent 对话） + meta/（详细时间线+原始折叠+外溢产物）。
- flat：每 session 一个目录，main 与每个 subagent 各一个自包含大 md，外加 index.md。

大段文本 / 结构化对象 / base64 图片超过内联阈值时外溢成 rendered/ 文件，正文留摘要+相对链接，
并按内容 hash 去重。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .ir import (
    AGENT_SUBAGENT,
    BLOCK_IMAGE,
    BLOCK_TEXT,
    BLOCK_THINKING,
    BLOCK_TOOL_RESULT,
    BLOCK_TOOL_USE,
    KIND_ASSISTANT,
    KIND_USER,
    Agent,
    Event,
    Session,
    Usage,
)
from .util import excerpt, format_int, format_timestamp, serialize_value, slugify, utcnow

TEXT_INLINE_LIMIT = 6000
JSON_INLINE_LIMIT = 3000
TOOL_RESULT_INLINE_LIMIT = 4000
SUMMARY_TEXT_INLINE_LIMIT = 4000
SUMMARY_VALUE_INLINE_LIMIT = 1200
EXCERPT_LEN = 400

IMAGE_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}


# ============================================================ 产物外溢

class ArtifactStore:
    def __init__(self, rendered_dir: Path) -> None:
        self.dir = rendered_dir
        self.counter = 0
        self.cache: dict[str, Path] = {}

    def _new_path(self, prefix: str, ext: str) -> Path:
        self.counter += 1
        safe = slugify(prefix)[:48] or "artifact"
        return self.dir / f"{self.counter:03d}-{safe}.{ext.lstrip('.') or 'txt'}"

    def write_text(self, prefix: str, content: str, ext: str = "txt") -> Path:
        key = f"t:{ext}:{hashlib.sha1(content.encode('utf-8')).hexdigest()}"
        if key in self.cache:
            return self.cache[key]
        path = self._new_path(prefix, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.cache[key] = path
        return path

    def write_bytes(self, prefix: str, data: bytes, ext: str) -> Path:
        key = f"b:{ext}:{hashlib.sha1(data).hexdigest()}"
        if key in self.cache:
            return self.cache[key]
        path = self._new_path(prefix, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.cache[key] = path
        return path


class Ctx:
    """渲染上下文：当前 md 文件路径 + 它的外溢产物仓库，用于生成相对链接。

    spill=True（默认）：超过内联阈值的大文本/JSON 外溢成 rendered/ 文件、正文留链接（summary/meta 用）。
    spill=False：完整内联，不外溢（flat 用——人读的完整详细流水）。图片仍外溢（二进制无法内联）。
    """

    def __init__(self, md_path: Path, store: ArtifactStore, spill: bool = True) -> None:
        self.md_path = md_path
        self.store = store
        self.spill = spill

    def rel(self, target: Path) -> str:
        return os.path.relpath(target, self.md_path.parent)


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


# ============================================================ Markdown 基元

def bullets(items: Iterable[tuple[str, Any]]) -> list[str]:
    out: list[str] = []
    for label, value in items:
        if value in (None, ""):
            continue
        out.append(f"- {label}: {value}")
    return out


def code_block(text: str, lang: str = "") -> list[str]:
    return [f"```{lang}".rstrip(), text, "```", ""]


def quote_body(text: str) -> list[str]:
    if not text:
        return ["_Empty_", ""]
    return [f"> {line}" if line else ">" for line in text.splitlines()] + [""]


def join(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_text_file_atomic(path: Path, content: str) -> None:
    """临时文件 + os.replace 原子替换：并发读者永不见截断的半文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _text_section(title: str, text: str, ctx: Ctx, prefix: str, limit: int) -> list[str]:
    lines = [f"#### {title}"]
    if ctx.spill and len(text) > limit:
        artifact = ctx.store.write_text(prefix, text)
        lines.append(f"[Open artifact]({ctx.rel(artifact)}) ({len(text)} chars)")
        lines.append("")
        return lines
    lines.extend(quote_body(text))
    return lines


def _value_section(title: str, value: Any, ctx: Ctx, prefix: str, limit: int) -> list[str]:
    lines = [f"#### {title}"]
    serialized, ext = serialize_value(value)
    if ctx.spill and len(serialized) > limit:
        artifact = ctx.store.write_text(prefix, serialized, ext=ext)
        lines.append(f"[Open artifact]({ctx.rel(artifact)}) ({len(serialized)} chars)")
        lines.append("")
        return lines
    lines.extend(code_block(serialized, "json" if ext == "json" else "text"))
    return lines


def _image_section(title: str, block: Any, ctx: Ctx, prefix: str) -> list[str]:
    lines = [f"#### {title}"]
    media = block.media_type or "application/octet-stream"
    ext = IMAGE_EXT.get(media, "bin")
    data = block.data_b64
    if isinstance(data, str):
        try:
            artifact = ctx.store.write_bytes(prefix, base64.b64decode(data, validate=False), ext)
        except (ValueError, binascii.Error):
            artifact = ctx.store.write_text(prefix, data, ext="txt")
    else:
        artifact = ctx.store.write_text(prefix, json.dumps({"media_type": media}, ensure_ascii=False), ext="json")
    lines.extend(bullets([("Media type", media), ("Artifact", f"[{artifact.name}]({ctx.rel(artifact)})")]))
    lines.append("")
    return lines


# ============================================================ 详细时间线（meta / merged / flat）

def _usage_inline(usage: Usage | None) -> str | None:
    if usage is None or usage.is_empty():
        return None
    parts = [f"in {format_int(usage.input_tokens)}", f"out {format_int(usage.output_tokens)}"]
    if usage.cache_read_tokens:
        parts.append(f"cache-r {format_int(usage.cache_read_tokens)}")
    if usage.cache_creation_tokens:
        parts.append(f"cache-w {format_int(usage.cache_creation_tokens)}")
    if usage.reasoning_tokens:
        parts.append(f"reasoning {format_int(usage.reasoning_tokens)}")
    return ", ".join(parts)


def render_block_detail(prefix: str, block: Any, ctx: Ctx) -> list[str]:
    if block.type in (BLOCK_TEXT, BLOCK_THINKING):
        if not (block.text or "").strip():
            return []  # 跳过空文本/空 thinking，不产出噪音段落
        title = "Text" if block.type == BLOCK_TEXT else "Thinking"
        return _text_section(title, block.text or "", ctx, f"{prefix}-{block.type}", TEXT_INLINE_LIMIT)
    if block.type == BLOCK_TOOL_USE:
        lines = [f"#### Tool Call `{block.name or 'unknown'}`"]
        lines.extend(bullets([("Call ID", block.tool_id)]))
        lines.append("")
        lines.extend(_value_section("Tool input", block.value, ctx, f"{prefix}-toolin", JSON_INLINE_LIMIT))
        return lines
    if block.type == BLOCK_TOOL_RESULT:
        lines = [f"#### Tool Result `{block.tool_use_id or ''}`".rstrip()]
        lines.extend(bullets([("Is error", None if block.is_error is None else str(block.is_error))]))
        lines.append("")
        lines.extend(_value_section("Result", block.value, ctx, f"{prefix}-toolout", TOOL_RESULT_INLINE_LIMIT))
        return lines
    if block.type == BLOCK_IMAGE:
        return _image_section("Image", block, ctx, f"{prefix}-image")
    return _value_section("Content", block.value, ctx, f"{prefix}-raw", JSON_INLINE_LIMIT)


def render_event_detail(index: int, event: Event, ctx: Ctx, show_source: bool = False) -> list[str]:
    label = event.label or event.kind
    suffix = f" [{event.source_path}]" if show_source and event.source_path and not event.is_main else ""
    lines = [f"### {index:03d}. {format_timestamp(event.timestamp)} `{label}`{suffix}", ""]
    lines.extend(
        bullets(
            [
                ("Role", event.role),
                ("Model", event.model),
                ("Usage", _usage_inline(event.usage)),
                ("Source", f"{event.source_path}:{event.source_line}" if event.source_line else None),
            ]
        )
    )
    if event.blocks or lines[-1] != "":
        lines.append("")
    prefix = f"{event.source_path}-{event.source_line}"
    for i, block in enumerate(event.blocks, 1):
        lines.extend(render_block_detail(f"{prefix}-{i}", block, ctx))
    # 无内容块的非对话事件（attachment/mode/快照/加密 reasoning 等）通用折叠原始记录，保证取证完整；
    # 有内容块的事件（如 codex developer 注入消息）已展示内容，不再重复 dump raw。
    if event.raw is not None and not event.blocks and event.kind not in (KIND_USER, KIND_ASSISTANT):
        lines.extend(_value_section("Raw event", event.raw, ctx, f"{prefix}-rawevent", JSON_INLINE_LIMIT))
    lines.append("")
    return lines


def render_timeline(events: list[Event], ctx: Ctx, show_source: bool = False) -> list[str]:
    lines = ["## Timeline", ""]
    if not events:
        return lines + ["_No events._", ""]
    for index, event in enumerate(events, 1):
        lines.extend(render_event_detail(index, event, ctx, show_source=show_source))
    return lines


# ============================================================ 对话（summary，仅 user/assistant）

def render_conversation(events: list[Event], ctx: Ctx) -> list[str]:
    lines: list[str] = []
    visible = 0
    for event in events:
        if event.kind not in (KIND_USER, KIND_ASSISTANT):
            continue
        body = _conversation_event(event, ctx)
        if not body:
            continue
        visible += 1
        actor = (event.role or event.kind).title()
        if event.source_path and not event.is_main:
            actor = f"{actor} [{event.source_path}]"
        lines.append(f"### {visible:03d}. {format_timestamp(event.timestamp)} {actor}")
        lines.append("")
        lines.extend(body)
        lines.append("")
    return lines


def _conversation_event(event: Event, ctx: Ctx) -> list[str]:
    lines: list[str] = []
    prefix = f"{event.source_path}-sum-{event.source_line}"
    for i, block in enumerate(event.blocks, 1):
        if block.type in (BLOCK_TEXT, BLOCK_THINKING) and not (block.text or "").strip():
            continue
        if block.type == BLOCK_TEXT:
            title = "Output" if event.kind == KIND_ASSISTANT else "User"
            lines.extend(_summary_text(title, block.text or "", ctx, f"{prefix}-{i}"))
        elif block.type == BLOCK_THINKING:
            lines.extend(_summary_text("Thinking", block.text or "", ctx, f"{prefix}-{i}"))
        elif block.type == BLOCK_TOOL_USE:
            lines.append(f"#### Tool Call `{block.name or 'unknown'}`")
            serialized, ext = serialize_value(block.value)
            lines.extend(bullets([("Input", excerpt(serialized, 200))]))
            if len(serialized) > SUMMARY_VALUE_INLINE_LIMIT:
                art = ctx.store.write_text(f"{prefix}-{i}-in", serialized, ext=ext)
                lines.append(f"[Open tool input]({ctx.rel(art)})")
            lines.append("")
        elif block.type == BLOCK_TOOL_RESULT:
            lines.extend(_summary_value("Tool Result", block.value, ctx, f"{prefix}-{i}-out"))
    return lines


def _summary_text(title: str, text: str, ctx: Ctx, prefix: str) -> list[str]:
    lines = [f"#### {title}"]
    if len(text) > SUMMARY_TEXT_INLINE_LIMIT:
        art = ctx.store.write_text(prefix, text)
        lines.extend(quote_body(excerpt(text, EXCERPT_LEN)))
        lines.append(f"[Open full artifact]({ctx.rel(art)})")
        lines.append("")
        return lines
    lines.extend(quote_body(text))
    return lines


def _summary_value(title: str, value: Any, ctx: Ctx, prefix: str) -> list[str]:
    lines = [f"#### {title}"]
    serialized, ext = serialize_value(value)
    summary = excerpt(serialized, EXCERPT_LEN) if serialized not in ("", "(empty)") else "(empty)"
    lines.extend(quote_body(summary))
    if len(serialized) > SUMMARY_VALUE_INLINE_LIMIT:
        art = ctx.store.write_text(prefix, serialized, ext=ext)
        lines.append(f"[Open full artifact]({ctx.rel(art)})")
        lines.append("")
    return lines


# ============================================================ 公共区块

def usage_bullets(usage: Usage, extra_metrics: list[tuple[str, Any]] | None = None) -> list[str]:
    items: list[tuple[str, Any]] = [
        ("Input tokens", format_int(usage.input_tokens)),
        ("Output tokens", format_int(usage.output_tokens)),
        ("Cache read tokens", format_int(usage.cache_read_tokens)),
        ("Cache creation tokens", format_int(usage.cache_creation_tokens)),
    ]
    if usage.reasoning_tokens:
        items.append(("Reasoning tokens", format_int(usage.reasoning_tokens)))
    if usage.cost_usd:
        items.append(("Cost USD", f"{usage.cost_usd:.6f}"))
    # extra_metrics 是适配器已格式化好的 (label, value) 列表，渲染器只 extend、不解释语义。
    items.extend(extra_metrics or [])
    return bullets(items)


def counts_bullets(agent_or_session: Any) -> list[str]:
    if isinstance(agent_or_session, Session):
        events = agent_or_session.all_events()
        subagent = sum(len(a.events) for a in agent_or_session.agents if a.kind == AGENT_SUBAGENT)
    else:
        events = agent_or_session.events
        subagent = len(events) if agent_or_session.kind == AGENT_SUBAGENT else 0
    user = sum(1 for e in events if e.kind == KIND_USER)
    assistant = sum(1 for e in events if e.kind == KIND_ASSISTANT)
    return bullets(
        [
            ("Total events", str(len(events))),
            ("Assistant events", str(assistant)),
            ("User events", str(user)),
            ("Subagent events", str(subagent)),
        ]
    )


def session_meta_bullets(session: Session) -> list[tuple[str, Any]]:
    return [
        ("Platform", session.platform),
        ("Session ID", session.session_id),
        ("Working directory", session.cwd),
        ("Git branch", session.git_branch),
        ("Started at", format_timestamp(session.started_at)),
        ("Last event at", format_timestamp(session.last_event_at)),
        ("Last synced at", format_timestamp(utcnow())),
        ("Models", ", ".join(session.models()) or "-"),
    ]


def usage_payload(session: Session, agent: Agent | None) -> dict[str, Any]:
    target: Any = agent if agent is not None else session
    usage = (agent.usage_total() if agent else session.usage_total())
    if isinstance(target, Session):
        events = target.all_events()
    else:
        events = target.events
    # 时间范围按 target 取（agent 级 usage.json 用 agent 自己的首/末事件，与其 summary.md header 一致）
    started = agent.first_ts() if agent is not None else session.started_at
    last_event = agent.last_ts() if agent is not None else session.last_event_at
    payload: dict[str, Any] = {
        "version": 1,
        "platform": session.platform,
        "session_id": session.session_id,
        "title": session.title,
        "summary": session.summary,
        "started_at": format_timestamp(started),
        "last_event_at": format_timestamp(last_event),
        "last_synced_at": format_timestamp(utcnow()),
        "cwd": session.cwd,
        "git_branch": session.git_branch,
        "models": (agent.models() if agent else session.models()),
        "counts": {
            "total_events": len(events),
            "assistant_events": sum(1 for e in events if e.kind == KIND_ASSISTANT),
            "user_events": sum(1 for e in events if e.kind == KIND_USER),
        },
        "usage": usage.to_dict(),
    }
    if agent is None:
        payload["telemetry"] = session.raw_meta.get("telemetry")
    else:
        payload["agent"] = {"key": agent.key, "raw_id": agent.raw_id, "kind": agent.kind}
        payload["telemetry"] = None
    return payload
