"""Claude Code 适配器：transcript JSONL（+ subagents + telemetry）-> IR。

定位（locate）原则见 memory: skill-session-discovery：
- config dir = $CLAUDE_CONFIG_DIR 否则 ~/.claude（合法默认）。
- 当前 session = $CLAUDE_CODE_SESSION_ID（或 --session）；glob projects/*/<sid>.jsonl 必须恰好 1 个。
- 缺 session id 且非 --all 即报错，不按 mtime 猜。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..discover import SessionRef
from ..ir import (
    AGENT_MAIN,
    AGENT_SUBAGENT,
    BLOCK_IMAGE,
    BLOCK_RAW,
    BLOCK_TEXT,
    BLOCK_THINKING,
    BLOCK_TOOL_RESULT,
    BLOCK_TOOL_USE,
    KIND_ASSISTANT,
    KIND_META,
    KIND_SUMMARY,
    KIND_SYSTEM,
    KIND_USER,
    Agent,
    Block,
    Event,
    Session,
    Usage,
)
from ..util import excerpt, format_int, make_agent_key, parse_timestamp

PLATFORM = "claude"

_CWD_PEEK_LINES = 50
_MESSAGE_KINDS = {"user": KIND_USER, "assistant": KIND_ASSISTANT}


# --------------------------------------------------------------------------- 定位

def resolve_config_dir(env: dict[str, str], override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    value = env.get("CLAUDE_CONFIG_DIR")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".claude"


def locate(
    env: dict[str, str],
    cwd: Path,
    session_id: str | None,
    all_sessions: bool,
    config_dir: str | None = None,
) -> list[SessionRef]:
    cfg = resolve_config_dir(env, config_dir)
    projects = cfg / "projects"
    if not projects.is_dir():
        raise FileNotFoundError(
            f"找不到 Claude 项目目录：{projects}（CLAUDE_CONFIG_DIR 是否正确？）"
        )

    sid = session_id or env.get("CLAUDE_CODE_SESSION_ID")

    if all_sessions:
        if sid:
            hits = sorted(projects.glob(f"*/{sid}.jsonl"))
            project_dir = hits[0].parent if len(hits) == 1 else _project_dir_for_cwd(projects, cwd)
        else:
            project_dir = _project_dir_for_cwd(projects, cwd)
        mains = sorted(project_dir.glob("*.jsonl"))
        if not mains:
            raise FileNotFoundError(f"项目目录 {project_dir} 下没有 transcript 文件。")
        return [_ref_for(path) for path in mains]

    if not sid:
        raise RuntimeError(
            "无法确定当前 session：环境无 CLAUDE_CODE_SESSION_ID。"
            "请用 --session <id> 指定，或用 --all 处理本项目全部会话。"
        )
    hits = sorted(projects.glob(f"*/{sid}.jsonl"))
    if len(hits) != 1:
        raise RuntimeError(
            f"按 session id '{sid}' 期望命中 1 个 transcript，实际 {len(hits)} 个："
            f"{[str(h) for h in hits]}。请用 --session 指定或检查 --config-dir。"
        )
    return [_ref_for(hits[0])]


def _ref_for(main_path: Path) -> SessionRef:
    sid = main_path.stem
    subagent_dir = main_path.parent / sid / "subagents"
    subs = sorted(subagent_dir.glob("agent-*.jsonl")) if subagent_dir.is_dir() else []
    return SessionRef(session_id=sid, main_path=main_path, subagent_paths=subs)


def _project_dir_for_cwd(projects: Path, cwd: Path) -> Path:
    """不靠有损的目录名编码，而是读 transcript 内的 cwd 字段实证匹配。"""
    target = str(cwd)
    matches: list[Path] = []
    for child in sorted(projects.iterdir()):
        if not child.is_dir():
            continue
        for jsonl in child.glob("*.jsonl"):
            if _peek_cwd(jsonl) == target:
                matches.append(child)
                break
    if not matches:
        raise RuntimeError(
            f"在 {projects} 下找不到 cwd={target} 的会话；请用 --session 指定，或确认在正确的工作目录下运行。"
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"cwd={target} 匹配到多个项目目录：{[str(m) for m in matches]}；请用 --session 指定具体会话。"
        )
    return matches[0]


def _peek_cwd(jsonl: Path) -> str | None:
    try:
        with jsonl.open(encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle):
                if line_no >= _CWD_PEEK_LINES:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("cwd"):
                    return str(entry["cwd"])
    except OSError:
        return None
    return None


# --------------------------------------------------------------------------- 解析

def parse(ref: SessionRef, env: dict[str, str] | None = None, config_dir: str | None = None) -> Session:
    env = env or {}
    raw_events: list[tuple[dict[str, Any], int, str]] = []
    raw_events.extend(_load_jsonl(ref.main_path, "main"))
    for sub in ref.subagent_paths:
        raw_events.extend(_load_jsonl(sub, sub.stem))

    warnings = sum(1 for entry, _, _ in raw_events if entry.get("type") == "invalid-json")

    # 分桶：main vs 各 subagent
    buckets: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry, line_no, source_label in raw_events:
        raw_id, kind = _classify(entry, source_label)
        bucket = buckets.get(raw_id)
        if bucket is None:
            bucket = {"kind": kind, "items": []}
            buckets[raw_id] = bucket
            order.append(raw_id)
        bucket["items"].append((entry, line_no, source_label))

    ordered_ids = (["main"] if "main" in buckets else []) + sorted(
        rid for rid in order if rid != "main"
    )

    sub_labels = _subagent_labels(ref.subagent_paths)
    agents: list[Agent] = []
    used_keys: set[str] = set()
    seq = 0
    for raw_id in ordered_ids:
        bucket = buckets[raw_id]
        is_main = bucket["kind"] == AGENT_MAIN
        # subagent 用 .meta.json 的可读名（"Explore: 任务描述"）替代不透明 agentId hash
        label = raw_id if is_main else sub_labels.get(raw_id, raw_id)
        key = make_agent_key(label, used_keys, is_main=is_main)
        used_keys.add(key)
        events: list[Event] = []
        for entry, line_no, source_label in bucket["items"]:
            events.append(_to_event(entry, line_no, source_label, seq, is_main))
            seq += 1
        events.sort(key=lambda e: (e.timestamp.timestamp() if e.timestamp else float("inf"), e.seq))
        agents.append(
            Agent(
                key=key,
                raw_id=label,
                kind=bucket["kind"],
                parent_key="main" if bucket["kind"] == AGENT_SUBAGENT else None,
                events=events,
            )
        )

    all_events = [event for agent in agents for event in agent.events]
    all_events.sort(key=lambda e: (e.timestamp.timestamp() if e.timestamp else float("inf"), e.seq))
    first_ts = next((e.timestamp for e in all_events if e.timestamp), None)
    last_ts = None
    for event in all_events:
        if event.timestamp is not None and (last_ts is None or event.timestamp > last_ts):
            last_ts = event.timestamp

    common = _common_meta(all_events)
    telemetry = _ingest_telemetry(resolve_config_dir(env, config_dir), ref.session_id)

    raw_meta: dict[str, Any] = {"parse_warnings": warnings}
    extra_metrics: list[tuple[str, Any]] = []
    if telemetry is not None:
        raw_meta["telemetry"] = telemetry
        extra_metrics = _telemetry_metrics(telemetry)

    return Session(
        platform=PLATFORM,
        session_id=ref.session_id,
        title=_derive_title(all_events),
        summary=_derive_summary(all_events),
        cwd=common.get("cwd"),
        git_branch=common.get("gitBranch"),
        started_at=first_ts,
        last_event_at=last_ts,
        source_paths=[str(ref.main_path)] + [str(p) for p in ref.subagent_paths],
        agents=agents,
        raw_meta=raw_meta,
        extra_metrics=extra_metrics,
    )


def _telemetry_metrics(telemetry: dict[str, Any]) -> list[tuple[str, Any]]:
    """把 claude 专属 telemetry 字典转成 (label, value) 列表，供平台无关渲染器直接展示。"""
    return [
        ("Telemetry API success", str(telemetry.get("api_success_count", 0))),
        ("Telemetry cost USD", f"{float(telemetry.get('cost_usd', 0.0)):.6f}"),
        ("Telemetry input tokens", format_int(telemetry.get("input_tokens", 0))),
        ("Telemetry output tokens", format_int(telemetry.get("output_tokens", 0))),
        ("Telemetry duration ms", format_int(telemetry.get("duration_ms_total", 0))),
        ("Telemetry avg TTFT ms", format_int(telemetry.get("average_ttft_ms", 0))),
    ]


def _load_jsonl(path: Path, source_label: str) -> list[tuple[dict[str, Any], int, str]]:
    out: list[tuple[dict[str, Any], int, str]] = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_no, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                entry = {"type": "invalid-json", "error": str(exc), "rawLine": line}
            if not isinstance(entry, dict):
                entry = {"type": "raw-value", "value": entry}
            out.append((entry, line_no, source_label))
    return out


def _subagent_labels(subagent_paths: list[Path]) -> dict[str, str]:
    """从每个 subagent 的 .meta.json 取可读名（agentType + description），键为 agentId 与文件 stem。"""
    labels: dict[str, str] = {}
    for sub in subagent_paths:
        meta_file = sub.parent / (sub.stem + ".meta.json")
        if not meta_file.exists():
            continue
        try:
            info = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        atype = info.get("agentType")
        desc = info.get("description")
        label = f"{atype}: {desc}" if atype and desc else (desc or atype)
        if not label:
            continue
        agent_id = sub.stem[6:] if sub.stem.startswith("agent-") else sub.stem
        labels[agent_id] = str(label)
        labels[sub.stem] = str(label)  # 兼容 raw_id 退化为文件 stem 的情况
    return labels


def _classify(entry: dict[str, Any], source_label: str) -> tuple[str, str]:
    if source_label != "main":
        return str(entry.get("agentId") or source_label), AGENT_SUBAGENT
    if entry.get("isSidechain"):
        return str(entry.get("agentId") or "sidechain"), AGENT_SUBAGENT
    return "main", AGENT_MAIN


def _to_event(entry: dict[str, Any], line_no: int, source_label: str, seq: int, is_main: bool) -> Event:
    etype = str(entry.get("type") or "unknown")
    ts = parse_timestamp(entry.get("timestamp")) or _snapshot_ts(entry)
    common = dict(
        seq=seq,
        timestamp=ts,
        source_path=source_label,
        source_line=line_no,
        is_main=is_main,
        raw=entry,
    )

    if etype in _MESSAGE_KINDS:
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        blocks = [_content_block(item) for item in _normalize_content(message.get("content"))]
        if "toolUseResult" in entry and not any(b.type == BLOCK_TOOL_RESULT for b in blocks):
            blocks.append(Block(type=BLOCK_TOOL_RESULT, value=entry.get("toolUseResult")))
        return Event(
            kind=_MESSAGE_KINDS[etype],
            role=str(message.get("role") or etype),
            model=message.get("model"),
            usage=_usage(message.get("usage")),
            blocks=blocks,
            label=etype,
            **common,
        )

    if etype == "summary":
        return Event(
            kind=KIND_SUMMARY,
            blocks=[Block(type=BLOCK_TEXT, text=str(entry.get("summary", "")))],
            label=etype,
            **common,
        )

    if etype == "system":
        content = entry.get("content")
        blocks = [Block(type=BLOCK_TEXT, text=str(content))] if content not in (None, "") else []
        # 只有错误/警告级 system 算「值得读」(KIND_SYSTEM)；stop_hook_summary/turn_duration 等记账归 KIND_META，
        # 这样 flat 自动过滤掉、meta 取证树仍保留（label 仍是 system）。
        kind = KIND_SYSTEM if _is_notable_system(entry) else KIND_META
        return Event(kind=kind, blocks=blocks, label=etype, **common)

    # 其它平台事件（attachment / file-history-snapshot / last-prompt / mode 等）：
    # 归类 meta，正文留 raw，详细视图按需通用折叠。
    text = entry.get("lastPrompt")
    blocks = [Block(type=BLOCK_TEXT, text=str(text))] if isinstance(text, str) and text else []
    return Event(kind=KIND_META, blocks=blocks, label=etype, **common)


def _is_notable_system(entry: dict[str, Any]) -> bool:
    """值得在可读流水里保留的 system 事件：有错误、warning+ 级别、或 api_error/local_command 子类型。"""
    return bool(
        entry.get("error")
        or entry.get("level") in {"warning", "error", "critical"}
        or entry.get("subtype") in {"api_error", "local_command"}
    )


def _snapshot_ts(entry: dict[str, Any]):
    snap = entry.get("snapshot")
    if isinstance(snap, dict):
        return parse_timestamp(snap.get("timestamp"))
    return None


def _normalize_content(content: Any) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, dict):
        return [content]
    if isinstance(content, list):
        items: list[dict[str, Any]] = []
        for item in content:
            items.append(item if isinstance(item, dict) else {"type": "text", "text": str(item)})
        return items
    return [{"type": "text", "text": str(content)}]


def _content_block(item: dict[str, Any]) -> Block:
    ctype = str(item.get("type", "unknown"))
    if ctype == "text":
        return Block(type=BLOCK_TEXT, text=str(item.get("text", "")))
    if ctype == "thinking":
        return Block(type=BLOCK_THINKING, text=str(item.get("thinking", "")))
    if ctype == "tool_use":
        return Block(type=BLOCK_TOOL_USE, name=item.get("name"), tool_id=item.get("id"), value=item.get("input"))
    if ctype == "tool_result":
        return Block(
            type=BLOCK_TOOL_RESULT,
            tool_use_id=item.get("tool_use_id"),
            is_error=item.get("is_error"),
            value=item.get("content"),
        )
    if ctype == "image":
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        return Block(type=BLOCK_IMAGE, media_type=source.get("media_type"), data_b64=source.get("data"))
    return Block(type=BLOCK_RAW, value=item)


def _usage(usage: Any) -> Usage | None:
    if not isinstance(usage, dict):
        return None
    return Usage(
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
    )


def _common_meta(events: list[Event]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for event in events:
        entry = event.raw if isinstance(event.raw, dict) else {}
        for key in ("cwd", "gitBranch"):
            if meta.get(key) is None and entry.get(key):
                meta[key] = entry[key]
        if meta.get("cwd") and meta.get("gitBranch"):
            break
    return meta


def _derive_title(events: list[Event]) -> str:
    for event in events:
        if event.kind == KIND_SUMMARY:
            for block in event.blocks:
                if block.text:
                    return f"Claude Session: {excerpt(block.text, 80)}"
    for event in events:
        if event.kind != KIND_USER:
            continue
        for block in event.blocks:
            if block.type == BLOCK_TEXT and block.text and _meaningful(block.text):
                return f"Claude Session: {excerpt(block.text, 80)}"
    return "Claude Session: Untitled"


# 命令/系统包装类消息，不应作为会话标题
_NOISE_PREFIXES = (
    "<local-command",
    "<command-name",
    "<command-message",
    "<command-args",
    "<command-contents",
    "<bash-input",
    "<bash-stdout",
    "<bash-stderr",
    "<system-reminder",
    "caveat:",
)


def _meaningful(text: str) -> bool:
    compact = " ".join(text.split())
    if not compact or compact in {".", "..", "...", "。", "-", "--", "_", "/", "\\"}:
        return False
    if compact.lower().startswith(_NOISE_PREFIXES):
        return False
    return len(compact) > 2 or any(c.isalnum() for c in compact)


def _derive_summary(events: list[Event]) -> str | None:
    for event in events:
        if event.kind == KIND_SUMMARY:
            for block in event.blocks:
                if block.text:
                    return block.text
    return None


def _ingest_telemetry(config_dir: Path, session_id: str) -> dict[str, Any] | None:
    """读 config_dir/telemetry/*.json，按 session_id 汇总用量。目录缺失 -> None（合法可选）。"""
    telemetry_dir = config_dir / "telemetry"
    if not telemetry_dir.is_dir():
        return None
    api_success = 0
    cost = 0.0
    input_tokens = output_tokens = cached = duration = 0
    ttft: list[int] = []
    models: set[str] = set()
    seen = 0
    for path in sorted(telemetry_dir.glob("*.json")):
        try:
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                data = record.get("event_data") if isinstance(record, dict) else None
                if not isinstance(data, dict) or str(data.get("session_id")) != session_id:
                    continue
                seen += 1
                if data.get("model"):
                    models.add(str(data["model"]))
                if data.get("event_name") != "tengu_api_success":
                    continue
                api_success += 1
                meta = _embedded_json(data.get("additional_metadata"))
                if not isinstance(meta, dict):
                    continue
                cost += float(meta.get("costUSD") or 0.0)
                input_tokens += int(meta.get("inputTokens") or 0)
                output_tokens += int(meta.get("outputTokens") or 0)
                cached += int(meta.get("cachedInputTokens") or 0)
                duration += int(meta.get("durationMs") or 0)
                if meta.get("ttftMs") is not None:
                    ttft.append(int(meta["ttftMs"]))
    if seen == 0:
        return None
    return {
        "api_success_count": api_success,
        "cost_usd": round(cost, 6),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached,
        "duration_ms_total": duration,
        "average_ttft_ms": round(sum(ttft) / len(ttft)) if ttft else 0,
        "models": sorted(models),
    }


def _embedded_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "{[":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value
