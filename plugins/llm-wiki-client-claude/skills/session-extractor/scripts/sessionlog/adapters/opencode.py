"""Opencode 适配器：只读 SQLite（opencode.db）-> IR。

存储：${XDG_DATA_HOME:-~/.local/share}/opencode/opencode.db（Drizzle SQLite）。
要点（见 memory: platform-session-formats）：
- 表 session/message/part；message.data、part.data 是 JSON TEXT 列。
- 用户可见文本在子 part(type=text) 而非 message 行；part 类型 text/reasoning/tool/step-start/step-finish。
- tool part 同时含 state.input/output（一个 part = 工具调用+结果）。
- subagent = 子 session（parent_id 指父）；时间戳是毫秒。
- **必须只读打开**（file:...?mode=ro），绝不写 WAL。

SessionRef 复用：main_path = db 文件路径，session_id = root 会话 id，子会话经 DB parent_id 解析。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from ..discover import SessionRef
from ..ir import (
    AGENT_MAIN,
    AGENT_SUBAGENT,
    BLOCK_TEXT,
    BLOCK_THINKING,
    BLOCK_TOOL_RESULT,
    BLOCK_TOOL_USE,
    KIND_ASSISTANT,
    KIND_USER,
    Agent,
    Block,
    Event,
    Session,
    Usage,
)
from ..util import excerpt, make_agent_key, ms_to_datetime, to_int

PLATFORM = "opencode"
_SESSION_ENV_KEYS = ("OPENCODE_SESSION_ID",)


# --------------------------------------------------------------------------- 定位

def resolve_db(env: dict[str, str], override: str | None = None) -> Path:
    if override:
        base = Path(override).expanduser()
        return base if base.suffix == ".db" else base / "opencode.db"
    xdg = env.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "opencode" / "opencode.db"


def locate(
    env: dict[str, str],
    cwd: Path,
    session_id: str | None,
    all_sessions: bool,
    config_dir: str | None = None,
) -> list[SessionRef]:
    db = resolve_db(env, config_dir)
    if not db.exists():
        raise FileNotFoundError(f"找不到 Opencode 数据库：{db}（XDG_DATA_HOME 是否正确？）")

    con = _connect(db)
    try:
        sid = session_id or _env_session_id(env)
        if all_sessions:
            rows = con.execute(
                "SELECT id FROM session WHERE parent_id IS NULL AND directory=? ORDER BY id",
                (str(cwd),),
            ).fetchall()
            if not rows:
                raise FileNotFoundError(f"opencode.db 里找不到 cwd={cwd} 的 root 会话。")
            return [SessionRef(session_id=r[0], main_path=db) for r in rows]

        if not sid:
            row = con.execute(
                "SELECT id FROM session WHERE directory=? ORDER BY time_updated DESC LIMIT 1",
                (str(cwd),),
            ).fetchone()
            if row is None:
                raise RuntimeError(
                    f"无法确定当前 opencode 会话：env 无 session id 且 cwd={cwd} 无匹配会话。请用 --session <id>。"
                )
            sid = row[0]
            print(
                f"[session-extractor] opencode 无 session-id env，按 cwd 最近活跃推断当前会话：{sid}"
                f"（如不对请用 --session <id>）",
                file=sys.stderr,
            )
        elif con.execute("SELECT 1 FROM session WHERE id=?", (sid,)).fetchone() is None:
            # 显式 --session 但 DB 里不存在 -> fail loud，不产出假成功的空会话
            raise RuntimeError(f"opencode.db 里找不到 session id '{sid}'。")
        root = _root_id(con, sid)
        return [SessionRef(session_id=root, main_path=db)]
    finally:
        con.close()


def _env_session_id(env: dict[str, str]) -> str | None:
    for key in _SESSION_ENV_KEYS:
        if env.get(key):
            return env[key]
    return None


def _connect(db: Path) -> sqlite3.Connection:
    # 只读 URI，绝不写 WAL/主库。
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _root_id(con: sqlite3.Connection, sid: str) -> str:
    seen: set[str] = set()
    current = sid
    while current not in seen:
        seen.add(current)
        row = con.execute("SELECT parent_id FROM session WHERE id=?", (current,)).fetchone()
        if not row or not row[0]:
            return current
        current = row[0]
    return current


# --------------------------------------------------------------------------- 解析

def parse(ref: SessionRef, env: dict[str, str] | None = None, config_dir: str | None = None) -> Session:
    con = _connect(ref.main_path)
    try:
        root_id = ref.session_id
        seq = 0
        used: set[str] = {"main"}

        main_events, seq = _events_for_session(con, root_id, "main", True, seq)
        agents = [Agent(key="main", raw_id="main", kind=AGENT_MAIN, events=main_events)]

        # 子会话（subagent）BFS 递归。visited 防 parent_id 成环导致死循环。
        visited: set[str] = {root_id}
        queue: list[tuple[str, str]] = []
        for cid in _children(con, root_id):
            if cid not in visited:
                visited.add(cid)
                queue.append((cid, "main"))
        while queue:
            cid, parent_key = queue.pop(0)
            raw_id = _session_label(con, cid)
            key = make_agent_key(raw_id, used)
            used.add(key)
            ev, seq = _events_for_session(con, cid, key, False, seq)
            agents.append(Agent(key=key, raw_id=raw_id, kind=AGENT_SUBAGENT, parent_key=parent_key, events=ev))
            for gc in _children(con, cid):
                if gc not in visited:
                    visited.add(gc)
                    queue.append((gc, key))

        meta = _session_meta(con, root_id)
        all_events = [e for a in agents for e in a.events]
        first_ts = next((e.timestamp for e in all_events if e.timestamp), None) or meta.get("created")
        last_ts = None
        for e in all_events:
            if e.timestamp is not None and (last_ts is None or e.timestamp > last_ts):
                last_ts = e.timestamp

        return Session(
            platform=PLATFORM,
            session_id=root_id,
            title=_derive_title(meta.get("title"), main_events, root_id),
            summary=None,
            cwd=meta.get("directory"),
            git_branch=None,  # opencode 不按会话存 branch
            started_at=first_ts,
            last_event_at=last_ts,
            source_paths=[f"{ref.main_path}#session={root_id}"],
            agents=agents,
            raw_meta={"opencode_version": meta.get("version")},
        )
    finally:
        con.close()


def _children(con: sqlite3.Connection, parent_id: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT id FROM session WHERE parent_id=? ORDER BY id", (parent_id,)).fetchall()]


def _session_label(con: sqlite3.Connection, sid: str) -> str:
    row = con.execute("SELECT title, slug FROM session WHERE id=?", (sid,)).fetchone()
    if row:
        return str(row[0] or row[1] or sid)
    return sid


def _session_meta(con: sqlite3.Connection, sid: str) -> dict[str, Any]:
    row = con.execute(
        "SELECT title, directory, version, time_created FROM session WHERE id=?", (sid,)).fetchone()
    if not row:
        return {}
    return {"title": row[0], "directory": row[1], "version": row[2], "created": ms_to_datetime(row[3])}


def _events_for_session(con, session_id, source_label, is_main, start_seq):
    events: list[Event] = []
    seq = start_seq
    msgs = con.execute(
        "SELECT id, data FROM message WHERE session_id=? ORDER BY time_created, id", (session_id,)).fetchall()
    for mid, mdata in msgs:
        data = _loads(mdata)
        role = str(data.get("role") or "user")
        blocks = _message_blocks(con, mid, data)
        if not blocks:
            continue
        kind = KIND_USER if role == "user" else KIND_ASSISTANT
        time = data.get("time") if isinstance(data.get("time"), dict) else {}
        events.append(Event(
            seq=seq,
            timestamp=ms_to_datetime(time.get("created")),
            kind=kind,
            role=role,
            blocks=blocks,
            model=_model(data) if role == "assistant" else None,
            usage=_usage(data) if role == "assistant" else None,
            source_path=source_label,
            source_line=None,
            is_main=is_main,
            label="message",
            raw=None,
        ))
        seq += 1
    return events, seq


def _message_blocks(con, message_id, mdata) -> list[Block]:
    blocks: list[Block] = []
    rows = con.execute("SELECT data FROM part WHERE message_id=? ORDER BY id", (message_id,)).fetchall()
    for (pdata,) in rows:
        pd = _loads(pdata)
        ptype = pd.get("type")
        if ptype == "text":
            text = str(pd.get("text", ""))
            if text.strip():
                blocks.append(Block(type=BLOCK_TEXT, text=text))
        elif ptype == "reasoning":
            text = str(pd.get("text", ""))
            if text.strip():
                blocks.append(Block(type=BLOCK_THINKING, text=text))
        elif ptype == "tool":
            state = pd.get("state") if isinstance(pd.get("state"), dict) else {}
            blocks.append(Block(type=BLOCK_TOOL_USE, name=pd.get("tool"),
                                tool_id=pd.get("callID"), value=state.get("input")))
            blocks.append(Block(type=BLOCK_TOOL_RESULT, tool_use_id=pd.get("callID"),
                                is_error=(state.get("status") == "error") or None, value=state.get("output")))
        # step-start / step-finish：结构性，跳过
    # assistant 报错且无内容时也保留一个标记（mdata 已是解析好的 message dict）
    if not blocks and isinstance(mdata, dict):
        err = mdata.get("error")
        if err:
            blocks.append(Block(type=BLOCK_TEXT, text=f"[error] {json.dumps(err, ensure_ascii=False)}"))
    return blocks


def _model(data: dict[str, Any]) -> str | None:
    provider = data.get("providerID")
    model = data.get("modelID")
    if not model and isinstance(data.get("model"), dict):
        provider = data["model"].get("providerID")
        model = data["model"].get("modelID")
    if model:
        return f"{provider}/{model}" if provider else str(model)
    return None


def _usage(data: dict[str, Any]) -> Usage | None:
    tok = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    cache = tok.get("cache") if isinstance(tok.get("cache"), dict) else {}
    try:
        cost = float(data.get("cost") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    usage = Usage(
        input_tokens=to_int(tok.get("input")),
        output_tokens=to_int(tok.get("output")),
        reasoning_tokens=to_int(tok.get("reasoning")),
        cache_read_tokens=to_int(cache.get("read")),
        cache_creation_tokens=to_int(cache.get("write")),
        cost_usd=cost,
    )
    return None if usage.is_empty() else usage


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes)):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def _derive_title(session_title: str | None, events: list[Event], session_id: str) -> str:
    if session_title and session_title.strip():
        return f"Opencode Session: {excerpt(session_title, 80)}"
    for event in events:
        if event.kind == KIND_USER:
            for block in event.blocks:
                if block.type == BLOCK_TEXT and block.text and block.text.strip():
                    return f"Opencode Session: {excerpt(block.text, 80)}"
    return f"Opencode Session: {session_id}"
