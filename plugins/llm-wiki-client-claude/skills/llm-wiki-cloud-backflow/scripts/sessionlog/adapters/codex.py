"""Codex 适配器：rollout JSONL（+ 关联 subagent rollout）-> IR。

存储：${CODEX_HOME:-~/.codex}/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl
每行 {timestamp, type, payload}。要点（见 memory: platform-session-formats）：
- session_meta：line1 payload.id == 文件名 uuid；Desktop fork 会内联重放祖先史、重发多条 session_meta
  -> 规范 session = line1 id；session_meta 不渲染为时间线事件（否则巨型会话会有上百条噪音）。
- turn_context：model/effort/cwd 在这里（不在 session_meta）。
- response_item：规范对话（message/reasoning/function_call/function_call_output/custom_tool_call(_output)/…）。
  reasoning 多为加密 encrypted_content -> 占位；function_call.arguments 是二次编码 JSON 串 -> 解码。
- event_msg：token_count(用量)；user_message/agent_message 与 response_item 重复 -> 跳过。
- subagent = 独立 rollout 文件，按 source.subagent.thread_spawn.parent_thread_id 关联到父 session。
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import Any, Iterator

from ..discover import SessionRef
from ..ir import (
    AGENT_MAIN,
    AGENT_SUBAGENT,
    BLOCK_TEXT,
    BLOCK_THINKING,
    BLOCK_TOOL_RESULT,
    BLOCK_TOOL_USE,
    KIND_ASSISTANT,
    KIND_META,
    KIND_USER,
    Agent,
    Block,
    Event,
    Session,
    Usage,
)
from ..util import excerpt, make_agent_key, parse_timestamp, to_int

PLATFORM = "codex"
# codex 当前不通过 env 暴露 session id（实证）；保留几个可能的名字，将来若有则优先用。
_SESSION_ENV_KEYS = ("CODEX_SESSION_ID", "CODEX_THREAD_ID", "CODEX_ROLLOUT_ID")
_DUP_EVENT_MSG = {"user_message", "agent_message"}  # 与 response_item/message 重复
_META_EVENT_MSG = {"task_started", "task_complete", "turn_aborted", "context_compacted", "patch_apply_end"}


# --------------------------------------------------------------------------- 定位

def resolve_home(env: dict[str, str], override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    value = env.get("CODEX_HOME")
    return Path(value).expanduser() if value else Path.home() / ".codex"


def locate(
    env: dict[str, str],
    cwd: Path,
    session_id: str | None,
    all_sessions: bool,
    config_dir: str | None = None,
) -> list[SessionRef]:
    home = resolve_home(env, config_dir)
    sessions_dir = home / "sessions"
    if not sessions_dir.is_dir():
        raise FileNotFoundError(f"找不到 Codex 会话目录：{sessions_dir}（CODEX_HOME 是否正确？）")

    sid = session_id or _env_session_id(env)

    if all_sessions:
        mains = _main_rollouts_for_cwd(sessions_dir, str(cwd))
        if not mains:
            raise FileNotFoundError(f"在 {sessions_dir} 下找不到 cwd={cwd} 的 codex 会话。")
        return [_ref_for(sessions_dir, path) for path in mains]

    if sid:
        main = _rollout_by_id(sessions_dir, sid)
        if main is None:
            raise RuntimeError(f"按 session id '{sid}' 找不到 codex rollout（检查 --config-dir / CODEX_HOME）。")
    else:
        main = _most_recent_for_cwd(sessions_dir, str(cwd))
        if main is None:
            raise RuntimeError(
                f"无法确定当前 codex 会话：env 无 session id 且 cwd={cwd} 无匹配 rollout。请用 --session <id> 指定。"
            )
        # codex 无权威 session-id env：按 cwd 最近活跃推断，显式告警（可见、非静默）。
        print(
            f"[session-extractor] codex 无 session-id env，按 cwd 最近活跃推断当前会话：{main.name}"
            f"（如不对请用 --session <id>）",
            file=sys.stderr,
        )
    return [_ref_for(sessions_dir, main)]


def _env_session_id(env: dict[str, str]) -> str | None:
    for key in _SESSION_ENV_KEYS:
        if env.get(key):
            return env[key]
    return None


def _ref_for(sessions_dir: Path, main_path: Path) -> SessionRef:
    sid = _id_from_filename(main_path) or _first_meta(main_path).get("id") or main_path.stem
    subs = _subagent_rollouts(sessions_dir, str(sid))
    return SessionRef(session_id=str(sid), main_path=main_path, subagent_paths=subs)


def _id_from_filename(path: Path) -> str | None:
    # rollout-<ts>-<uuid>.jsonl -> uuid（uuid 含 4 个 '-'，取末尾 5 段）
    parts = path.stem.split("-")
    if len(parts) >= 6:
        return "-".join(parts[-5:])
    return None


def _rollout_by_id(sessions_dir: Path, sid: str) -> Path | None:
    hits = sorted(sessions_dir.rglob(f"rollout-*-{glob.escape(sid)}.jsonl"))
    return hits[0] if hits else None


def _first_meta(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if isinstance(rec, dict) and rec.get("type") == "session_meta":
                    return rec.get("payload") or {}
                return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _is_subagent_meta(meta: dict[str, Any]) -> bool:
    src = meta.get("source")
    return (isinstance(src, dict) and "subagent" in src) or meta.get("thread_source") == "subagent"


def _parent_thread_id(meta: dict[str, Any]) -> str | None:
    src = meta.get("source")
    if isinstance(src, dict):
        sub = src.get("subagent")
        spawn = sub.get("thread_spawn") if isinstance(sub, dict) else None
        if isinstance(spawn, dict):
            return spawn.get("parent_thread_id")
    return None


def _subagent_rollouts(sessions_dir: Path, parent_id: str) -> list[Path]:
    out: list[Path] = []
    for path in sessions_dir.rglob("rollout-*.jsonl"):
        meta = _first_meta(path)
        if _is_subagent_meta(meta) and _parent_thread_id(meta) == parent_id:
            out.append(path)
    return sorted(out)


def _main_rollouts_for_cwd(sessions_dir: Path, target_cwd: str) -> list[Path]:
    out: list[Path] = []
    for path in sessions_dir.rglob("rollout-*.jsonl"):
        meta = _first_meta(path)
        if not _is_subagent_meta(meta) and meta.get("cwd") == target_cwd:
            out.append(path)
    return sorted(out)


def _most_recent_for_cwd(sessions_dir: Path, target_cwd: str) -> Path | None:
    mains = _main_rollouts_for_cwd(sessions_dir, target_cwd)
    return max(mains, key=lambda p: p.stat().st_mtime) if mains else None


# --------------------------------------------------------------------------- 解析

def parse(ref: SessionRef, env: dict[str, str] | None = None, config_dir: str | None = None) -> Session:
    main_events, main_info, seq = _events_from_rollout(ref.main_path, "main", True, 0)
    main_agent = Agent(key="main", raw_id="main", kind=AGENT_MAIN, events=main_events)
    agents = [main_agent]

    used_keys = {"main"}
    for sub in ref.subagent_paths:
        sub_meta = _first_meta(sub)
        raw_id = sub_meta.get("agent_nickname") or _id_from_filename(sub) or sub.stem
        key = make_agent_key(str(raw_id), used_keys)
        used_keys.add(key)
        sub_events, _, seq = _events_from_rollout(sub, key, False, seq)
        agents.append(Agent(key=key, raw_id=str(raw_id), kind=AGENT_SUBAGENT, parent_key="main", events=sub_events))

    all_events = [e for a in agents for e in a.events]
    all_events.sort(key=lambda e: (e.timestamp.timestamp() if e.timestamp else float("inf"), e.seq))
    first_ts = next((e.timestamp for e in all_events if e.timestamp), None) or main_info.get("started")
    last_ts = None
    for e in all_events:
        if e.timestamp is not None and (last_ts is None or e.timestamp > last_ts):
            last_ts = e.timestamp

    return Session(
        platform=PLATFORM,
        session_id=ref.session_id,
        title=_derive_title(main_events, ref.session_id),
        summary=None,
        cwd=main_info.get("cwd"),
        git_branch=main_info.get("git"),
        started_at=first_ts,
        last_event_at=last_ts,
        source_paths=[str(ref.main_path)] + [str(p) for p in ref.subagent_paths],
        agents=agents,
        raw_meta={"originator": main_info.get("originator")},
    )


def _stream(path: Path) -> Iterator[tuple[dict[str, Any], int]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                yield rec, line_no


def _events_from_rollout(path: Path, source_label: str, is_main: bool, start_seq: int):
    events: list[Event] = []
    seq = start_seq
    model: str | None = None
    info: dict[str, Any] = {}

    for rec, line_no in _stream(path):
        rtype = rec.get("type")
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        ts = parse_timestamp(rec.get("timestamp"))

        if rtype == "session_meta":
            if "id" not in info:  # 只取 line1（leaf）做会话元信息；其余重放的 meta 跳过
                g = payload.get("git")
                info.update(
                    id=payload.get("id"),
                    cwd=payload.get("cwd"),
                    git=g.get("branch") if isinstance(g, dict) else None,
                    started=parse_timestamp(payload.get("timestamp")),
                    originator=payload.get("originator"),
                )
            continue
        if rtype == "turn_context":
            if payload.get("model"):
                model = payload["model"]
            if payload.get("cwd") and not info.get("cwd"):
                info["cwd"] = payload["cwd"]
            continue
        if rtype == "response_item":
            ev = _response_event(payload, ts, source_label, line_no, seq, is_main, model, rec)
        elif rtype == "event_msg":
            ev = _event_msg_event(payload, ts, source_label, line_no, seq, is_main, rec)
        elif rtype == "compacted":
            ev = Event(seq=seq, timestamp=ts, kind=KIND_META, label="compacted",
                       source_path=source_label, source_line=line_no, is_main=is_main, raw=rec)
        else:
            ev = Event(seq=seq, timestamp=ts, kind=KIND_META, label=str(rtype),
                       source_path=source_label, source_line=line_no, is_main=is_main, raw=rec)
        if ev is not None:
            events.append(ev)
            seq += 1

    info["model"] = model
    return events, info, seq


def _response_event(payload, ts, source_label, line_no, seq, is_main, model, rec) -> Event | None:
    pt = payload.get("type")
    common = dict(seq=seq, timestamp=ts, source_path=source_label, source_line=line_no, is_main=is_main, raw=rec)

    if pt == "message":
        role = str(payload.get("role") or "user")
        blocks = []
        for item in payload.get("content") or []:
            if not isinstance(item, dict):
                continue
            it = item.get("type")
            if it in ("input_text", "output_text", "text"):
                text = str(item.get("text", ""))
                if text.strip():
                    blocks.append(Block(type=BLOCK_TEXT, text=text))
        if not blocks:
            return None
        # developer/system 是注入的系统提示/指令上下文 -> KIND_META：flat 过滤掉、meta 取证树仍保留。
        kind = KIND_USER if role == "user" else KIND_ASSISTANT if role == "assistant" else KIND_META
        return Event(kind=kind, role=role, blocks=blocks, label="message",
                     model=model if role == "assistant" else None, **common)

    if pt == "reasoning":
        text = _reasoning_text(payload)
        if text:  # 有可读 summary：作为 thinking 渲染（详细+对话两处可见）
            return Event(kind=KIND_ASSISTANT, role="assistant", blocks=[Block(type=BLOCK_THINKING, text=text)],
                         label="reasoning", model=model, **common)
        # 加密不可读：留 meta 标记（详细时间线可见"发生过 reasoning"，但不污染对话摘要、不 dump 加密 blob）
        return Event(kind=KIND_META, label="reasoning", **{**common, "raw": None})

    if pt == "function_call":
        return Event(kind=KIND_ASSISTANT, role="assistant", label="function_call", model=model,
                     blocks=[Block(type=BLOCK_TOOL_USE, name=payload.get("name"),
                                   tool_id=payload.get("call_id"), value=_maybe_json(payload.get("arguments")))],
                     **common)
    if pt == "custom_tool_call":
        return Event(kind=KIND_ASSISTANT, role="assistant", label="custom_tool_call", model=model,
                     blocks=[Block(type=BLOCK_TOOL_USE, name=payload.get("name"),
                                   tool_id=payload.get("call_id"), value=payload.get("input"))],
                     **common)
    if pt in ("function_call_output", "custom_tool_call_output"):
        return Event(kind=KIND_ASSISTANT, role="tool", label=str(pt),
                     blocks=[Block(type=BLOCK_TOOL_RESULT, tool_use_id=payload.get("call_id"),
                                   value=_maybe_json(payload.get("output")))],
                     **common)

    # tool_search/web_search 是模型发起的真实工具调用（找工具/联网搜索）-> 当作工具块，进 flat 人读流水，
    # 与 function_call/custom_tool_call 一致；按 call_id 配对 call/output。
    if pt in ("tool_search_call", "web_search_call"):
        name = "tool_search" if pt == "tool_search_call" else "web_search"
        value = (_maybe_json(payload.get("arguments")) if payload.get("arguments") is not None
                 else {k: v for k, v in payload.items() if k not in ("type", "call_id", "id")})
        return Event(kind=KIND_ASSISTANT, role="assistant", label=str(pt), model=model,
                     blocks=[Block(type=BLOCK_TOOL_USE, name=name, tool_id=payload.get("call_id"), value=value)],
                     **common)
    if pt in ("tool_search_output", "web_search_output"):
        out = payload.get("output")
        if out is None:
            out = {k: v for k, v in payload.items() if k not in ("type", "call_id", "id")}
        return Event(kind=KIND_ASSISTANT, role="tool", label=str(pt),
                     blocks=[Block(type=BLOCK_TOOL_RESULT, tool_use_id=payload.get("call_id"), value=_maybe_json(out))],
                     **common)

    # 其它未知 response_item：留 meta + raw 折叠（取证用）
    return Event(kind=KIND_META, label=str(pt or "response_item"), **common)


def _event_msg_event(payload, ts, source_label, line_no, seq, is_main, rec) -> Event | None:
    pt = payload.get("type")
    common = dict(seq=seq, timestamp=ts, source_path=source_label, source_line=line_no, is_main=is_main, raw=rec)

    if pt == "token_count":
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        last = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else {}
        usage = Usage(
            input_tokens=to_int(last.get("input_tokens")),
            output_tokens=to_int(last.get("output_tokens")),
            cache_read_tokens=to_int(last.get("cached_input_tokens")),
            reasoning_tokens=to_int(last.get("reasoning_output_tokens")),
        )
        if usage.is_empty():
            return None
        return Event(kind=KIND_META, label="token_count", usage=usage, **common)

    if pt in _DUP_EVENT_MSG:
        return None  # 与 response_item/message 重复
    if pt in _META_EVENT_MSG:
        return Event(kind=KIND_META, label=str(pt), **common)
    return None  # 其它 UI 事件忽略


def _reasoning_text(payload: dict[str, Any]) -> str | None:
    """可读的 reasoning summary；加密/空则返回 None（codex 的 encrypted_content 不可恢复）。"""
    summ = payload.get("summary")
    if isinstance(summ, list):
        parts = [s.get("text") for s in summ if isinstance(s, dict) and s.get("text")]
        if parts:
            return "\n".join(parts)
    if isinstance(summ, str) and summ.strip():
        return summ
    return None


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped[0] in "{[":
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


# codex 会把环境/指令上下文作为首条 user 消息注入，不应作为标题
_NOISE_PREFIXES = ("<environment_context", "<user_instructions", "<system", "<persistent", "<exit", "## my request")


def _derive_title(events: list[Event], session_id: str) -> str:
    for event in events:
        if event.kind == KIND_USER:
            for block in event.blocks:
                text = block.text or ""
                if block.type == BLOCK_TEXT and text.strip() and not text.lstrip().lower().startswith(_NOISE_PREFIXES):
                    return f"Codex Session: {excerpt(text, 80)}"
    return f"Codex Session: {session_id}"
