"""目录布局与幂等编排：决定每个产物写到哪、复用上次路径、重建全局索引。

把「渲染单个片段」（render.py）与「整棵树落在哪 + 多次触发幂等」（本模块）分开。
状态见 .state/<platform>__<sid>.json：记录各产物相对路径，下次复用 -> 同一 session
永远写同一目录，不随月份/时间漂移。
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from . import render as R
from .ir import AGENT_SUBAGENT, KIND_ASSISTANT, KIND_META, KIND_USER, Agent, Session
from .state import STATE_VERSION
from .util import format_timestamp, utcnow


def state_key(session: Session) -> str:
    return f"{session.platform}__{session.session_id}"


def _ym(dt: datetime | None) -> tuple[str, str]:
    dt = dt or utcnow()
    return f"{dt.year:04d}", f"{dt.month:02d}"


def _stamp(session: Session) -> str:
    """单个本地时间戳文件夹名 YYYY-MM-DD_HH-MM-SS（对齐 .agents-log，summary 与 flat 共用）。
    取自 session 首事件时间、转本机本地时区（与 .agents-log 一致、不硬编码时区）；同一 session
    永得同名 -> state 丢失也不漂移；无时间戳时回退 sid 保证确定且不撞名。"""
    if session.started_at is not None:
        return session.started_at.astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    return session.session_id


# ============================================================ 文档组装

def _decorate(title: str, label: str) -> str:
    return f"{title} [{label}]"


def _metadata_block(session: Session) -> list[str]:
    return ["## Session Metadata", *R.bullets(R.session_meta_bullets(session)), ""]


def _summary_block(session: Session) -> list[str]:
    if not session.summary:
        return []
    return ["## Summary", *R.quote_body(session.summary), ""]


def build_detail_doc(session: Session, events: list, title: str, ctx: R.Ctx, show_source: bool) -> str:
    lines = [f"# {title}", ""]
    lines += _metadata_block(session)
    lines += _summary_block(session)
    lines += ["## Counts", *R.counts_bullets(session), ""]
    lines += ["## Usage", *R.usage_bullets(session.usage_total(), session.extra_metrics), ""]
    warnings = session.raw_meta.get("parse_warnings")
    if warnings:
        lines += [f"> ⚠ {warnings} 行无法解析（已作为 invalid-json 占位保留）。", ""]
    lines += R.render_timeline(events, ctx, show_source=show_source)
    return R.join(lines)


def build_meta_index(session: Session, path: Path, store: R.ArtifactStore, links: dict[str, Any]) -> None:
    ctx = R.Ctx(path, store)
    lines = [f"# {_decorate(session.title, 'meta')}", ""]
    lines += _metadata_block(session)
    lines += _summary_block(session)
    lines += [
        "## Entry Points",
        *R.bullets(
            [
                ("Merged detail", f"[Open]({ctx.rel(links['merged'])})"),
                ("Root summary", f"[Open]({ctx.rel(links['summary'])})"),
                ("Root usage JSON", f"[Open]({ctx.rel(links['usage'])})"),
            ]
        ),
        "",
        "## Agents",
        "",
    ]
    for agent in session.agents:
        ap = links["agents"][agent.key]
        lines.append(f"### `{agent.raw_id}` ({agent.kind})")
        lines += R.bullets(
            [
                ("Agent key", agent.key),
                ("Events", str(len(agent.events))),
                ("Started at", format_timestamp(agent.first_ts())),
                ("Detail", f"[Open]({ctx.rel(ap['detail'])})"),
                ("Summary", f"[Open]({ctx.rel(ap['summary'])})"),
                ("Usage JSON", f"[Open]({ctx.rel(ap['usage'])})"),
            ]
        )
        lines.append("")
    R.write_text_file(path, R.join(lines))


def build_root_summary(session: Session, path: Path, store: R.ArtifactStore, links: dict[str, Any]) -> None:
    ctx = R.Ctx(path, store)
    lines = [f"# {session.title}", ""]
    lines += R.bullets(
        R.session_meta_bullets(session)
        + [
            ("Meta index", f"[Open]({ctx.rel(links['meta_index'])})"),
            ("Merged detail", f"[Open]({ctx.rel(links['merged'])})"),
            ("Usage JSON", f"[Open]({ctx.rel(links['usage'])})"),
        ]
    )
    lines.append("")
    lines += _summary_block(session)
    lines += ["## Aggregate Usage", *R.usage_bullets(session.usage_total(), session.extra_metrics), ""]
    lines += ["## Agents", ""]
    for agent in session.agents:
        ap = links["agents"][agent.key]
        events = agent.events
        lines.append(f"### `{agent.raw_id}` ({agent.kind})")
        lines += R.bullets(
            [
                ("Agent key", agent.key),
                ("Event count", str(len(events))),
                ("Assistant events", str(sum(1 for e in events if e.kind == KIND_ASSISTANT))),
                ("User events", str(sum(1 for e in events if e.kind == KIND_USER))),
                ("Started at", format_timestamp(agent.first_ts())),
                ("Last event at", format_timestamp(agent.last_ts())),
                ("Models", ", ".join(agent.models()) or "-"),
                ("Summary", f"[Open]({ctx.rel(ap['summary'])})"),
                ("Usage JSON", f"[Open]({ctx.rel(ap['usage'])})"),
                ("Detailed log", f"[Open]({ctx.rel(ap['detail'])})"),
            ]
        )
        lines.append("")
    R.write_text_file(path, R.join(lines))


def build_agent_summary(session: Session, agent: Agent, path: Path, store: R.ArtifactStore, links: dict[str, Any]) -> None:
    ctx = R.Ctx(path, store)
    lines = [f"# {_decorate(session.title, agent.raw_id)}", ""]
    lines += R.bullets(
        [
            ("Platform", session.platform),
            ("Session ID", session.session_id),
            ("Agent", f"{agent.raw_id} ({agent.kind})"),
            ("Working directory", session.cwd),
            ("Git branch", session.git_branch),
            ("Started at", format_timestamp(agent.first_ts())),
            ("Last event at", format_timestamp(agent.last_ts())),
            ("Last synced at", format_timestamp(utcnow())),
            ("Models", ", ".join(agent.models()) or "-"),
            ("Detailed log", f"[Open]({ctx.rel(links['detail'])})"),
            ("Detailed index", f"[Open]({ctx.rel(links['index'])})"),
            ("Usage JSON", f"[Open]({ctx.rel(links['usage'])})"),
        ]
    )
    lines.append("")
    lines += ["## Usage", *R.usage_bullets(agent.usage_total(), None), ""]
    lines += ["## Conversation", ""]
    convo = R.render_conversation(agent.events, ctx)
    lines += convo or ["_No user/assistant content._", ""]
    R.write_text_file(path, R.join(lines))


# ============================================================ structured

def run_structured(session: Session, out_root: Path, state: dict[str, Any]) -> str:
    st = state.get("structured", {}) if isinstance(state.get("structured"), dict) else {}
    yyyy, mm = _ym(session.started_at)
    meta_dir_rel = st.get("meta_session_dir") or f"meta/sessions/{session.platform}/{yyyy}/{mm}/{session.session_id}"
    # summary 用单个本地时间戳文件夹（对齐 .agents-log），不再 YYYY/MM/<sid> 多层。
    # 确定性 + state 复用 + 无 _unique_dir -> state 丢失也不漂移、不堆 -02（见 fail-loud 原则）。
    summary_dir_rel = st.get("summary_dir") or f"summary/{session.platform}/{_stamp(session)}"
    meta_dir = out_root / meta_dir_rel
    summary_dir = out_root / summary_dir_rel

    # 幂等收敛：清掉上一轮写过、本轮已不在的 agent 子目录（agent 集合缩小/key 重排）。
    keys = {a.key for a in session.agents}
    _prune_agents(meta_dir / "agents", keys)
    _prune_agents(meta_dir / "artifacts", keys, reserved=("shared",))
    _prune_agents(summary_dir / "agents", keys)
    _prune_agents(summary_dir / "artifacts", keys, reserved=("shared",))

    meta_index = meta_dir / "index.md"
    merged = meta_dir / "merged" / "session.md"
    root_summary = summary_dir / "summary.md"
    root_usage = summary_dir / "usage.json"

    agent_links: dict[str, dict[str, Path]] = {}
    for agent in session.agents:
        agent_links[agent.key] = {
            "detail": meta_dir / "agents" / agent.key / "session.md",
            "summary": summary_dir / "agents" / agent.key / "summary.md",
            "usage": summary_dir / "agents" / agent.key / "usage.json",
        }

    # merged 详细时间线（含全部 agent，标注来源）
    shared_store = R.ArtifactStore(_reset(meta_dir / "artifacts" / "shared" / "rendered"))
    R.write_text_file(
        merged,
        build_detail_doc(session, session.all_events(), _decorate(session.title, "merged"), R.Ctx(merged, shared_store), show_source=True),
    )

    # meta index hub
    build_meta_index(
        session, meta_index, shared_store,
        {"merged": merged, "summary": root_summary, "usage": root_usage, "agents": agent_links},
    )

    # root summary + usage
    sum_store = R.ArtifactStore(_reset(summary_dir / "artifacts" / "shared" / "rendered"))
    build_root_summary(
        session, root_summary, sum_store,
        {"meta_index": meta_index, "merged": merged, "usage": root_usage, "agents": agent_links},
    )
    R.write_json_file(root_usage, R.usage_payload(session, None))

    # 各 agent：详细时间线 + 对话摘要 + usage
    for agent in session.agents:
        links = agent_links[agent.key]
        detail_store = R.ArtifactStore(_reset(meta_dir / "artifacts" / agent.key / "rendered"))
        R.write_text_file(
            links["detail"],
            build_detail_doc(session, agent.events, _decorate(session.title, agent.raw_id), R.Ctx(links["detail"], detail_store), show_source=False),
        )
        summary_store = R.ArtifactStore(_reset(summary_dir / "artifacts" / agent.key / "rendered"))
        build_agent_summary(session, agent, links["summary"], summary_store,
                            {"detail": links["detail"], "index": meta_index, "usage": links["usage"]})
        R.write_json_file(links["usage"], R.usage_payload(session, agent))

    state["structured"] = {
        "meta_session_dir": meta_dir_rel,
        "summary_dir": summary_dir_rel,
        "entry_relpath": os.path.relpath(meta_index, out_root),
    }
    return os.path.relpath(meta_index, out_root)


# ============================================================ flat

def build_flat_agent(session: Session, agent: Agent, path: Path, store: R.ArtifactStore) -> None:
    # flat：人读的完整详细流水 —— 完整内联（不外溢）、过滤记账噪音、单一详细时间线（不再有重复的 Conversation 段）。
    ctx = R.Ctx(path, store, spill=False)
    lines = [f"# {_decorate(session.title, agent.raw_id)}", ""]
    lines += R.bullets(
        [
            ("Platform", session.platform),
            ("Session ID", session.session_id),
            ("Agent", f"{agent.raw_id} ({agent.kind})"),
            ("Working directory", session.cwd),
            ("Git branch", session.git_branch),
            ("Started at", format_timestamp(agent.first_ts())),
            ("Last event at", format_timestamp(agent.last_ts())),
            ("Models", ", ".join(agent.models()) or "-"),
        ]
    )
    lines.append("")
    lines += ["## Usage", *R.usage_bullets(agent.usage_total(), None), ""]
    # 过滤掉记账/元事件（hook 输出 attachment、mode、permission-mode、ai-title、file-history-snapshot、last-prompt 等）
    events = [e for e in agent.events if e.kind != KIND_META]
    lines += R.render_timeline(events, ctx, show_source=False)
    R.write_text_file(path, R.join(lines))


def build_flat_index(session: Session, path: Path, agent_files: dict[str, str]) -> None:
    lines = [f"# {session.title}", ""]
    lines += R.bullets(R.session_meta_bullets(session))
    lines.append("")
    lines += _summary_block(session)
    lines += ["## Aggregate Usage", *R.usage_bullets(session.usage_total(), session.extra_metrics), ""]
    lines += ["## Agents", ""]
    for agent in session.agents:
        lines.append(f"### `{agent.raw_id}` ({agent.kind})")
        lines += R.bullets(
            [
                ("Events", str(len(agent.events))),
                ("Models", ", ".join(agent.models()) or "-"),
                ("Log", f"[Open]({agent_files[agent.key]})"),
            ]
        )
        lines.append("")
    R.write_text_file(path, R.join(lines))


def run_flat(session: Session, out_root: Path, state: dict[str, Any]) -> str:
    st = state.get("flat", {}) if isinstance(state.get("flat"), dict) else {}
    # flat 用单个本地时间戳文件夹（与 summary、.agents-log 一致；单层日期）。
    dir_rel = st.get("flat_session_dir") or f"{session.platform}/{_stamp(session)}"
    sdir = out_root / dir_rel

    # 幂等收敛：清孤儿 artifacts/<key> 与孤儿 <key>.md（agent 集合缩小/key 重排）。
    keys = {a.key for a in session.agents}
    _prune_agents(sdir / "artifacts", keys)
    keep_md = {("main" if a.kind != AGENT_SUBAGENT else a.key) for a in session.agents} | {"index"}
    if sdir.is_dir():
        for child in sdir.glob("*.md"):
            if child.stem not in keep_md:
                child.unlink()

    agent_files: dict[str, str] = {}
    for agent in session.agents:
        fname = "main.md" if agent.kind != AGENT_SUBAGENT else f"{agent.key}.md"
        agent_files[agent.key] = fname
        store = R.ArtifactStore(_reset(sdir / "artifacts" / agent.key / "rendered"))
        build_flat_agent(session, agent, sdir / fname, store)

    R.write_json_file(sdir / "usage.json", R.usage_payload(session, None))
    index = sdir / "index.md"
    build_flat_index(session, index, agent_files)

    state["flat"] = {"flat_session_dir": dir_rel, "entry_relpath": os.path.relpath(index, out_root)}
    return os.path.relpath(index, out_root)


# ============================================================ 全局索引 + state

def update_state(session: Session, state: dict[str, Any]) -> dict[str, Any]:
    state.update(
        {
            "version": STATE_VERSION,
            "platform": session.platform,
            "session_id": session.session_id,
            "title": session.title,
            "summary": session.summary,
            "cwd": session.cwd,
            "git_branch": session.git_branch,
            "models": session.models(),
            "agent_keys": [a.key for a in session.agents],
            "started_at": format_timestamp(session.started_at),
            "last_event_at": format_timestamp(session.last_event_at),
            "last_synced_at": format_timestamp(utcnow()),
            "source_paths": session.source_paths,
        }
    )
    return state


def write_global_index(out_root: Path, load_state) -> Path:
    # 对齐 .agents-log：全局索引在 meta/index.md，state 在 meta/state/。
    meta_dir = out_root / "meta"
    state_dir = meta_dir / "state"
    entries: list[dict[str, Any]] = []
    if state_dir.is_dir():
        for sf in state_dir.glob("*.json"):
            data = load_state(sf)
            if data:
                entries.append(data)
    entries.sort(key=lambda d: (d.get("last_synced_at") or "", d.get("session_id") or ""), reverse=True)

    lines = ["# session-extractor index", "", "_按需导出的 agent 会话日志_", ""]
    lines += R.bullets([("Updated at", format_timestamp(utcnow())), ("Sessions", str(len(entries)))])
    lines.append("")
    index_path = meta_dir / "index.md"
    for data in entries:
        struct = data.get("structured") or {}
        flat = data.get("flat") or {}
        # 跟随本次实际产出的树（primary_tree），而非永远偏向 structured；旧 state 无标记则维持原行为。
        if data.get("primary_tree") == "flat":
            entry_rel = flat.get("entry_relpath") or struct.get("entry_relpath")
        else:
            entry_rel = struct.get("entry_relpath") or flat.get("entry_relpath")
        if not entry_rel:
            continue
        # entry_relpath 是相对 out_root 的；index 在 meta/ 下，链接需相对 meta/ 计算。
        link = os.path.relpath(out_root / entry_rel, index_path.parent)
        title = data.get("title") or data.get("session_id") or "Untitled"
        lines.append(f"## [{title}]({link})")
        lines += R.bullets(
            [
                ("Platform", data.get("platform")),
                ("Session ID", data.get("session_id")),
                ("Last synced", data.get("last_synced_at")),
                ("Working directory", data.get("cwd")),
            ]
        )
        lines.append("")
    R.write_text_file_atomic(index_path, R.join(lines))
    return index_path


# ============================================================ 私有

def _reset(path: Path) -> Path:
    R.reset_dir(path)
    return path


def _prune_agents(parent: Path, keep: set[str], reserved: tuple[str, ...] = ()) -> None:
    """删除 parent 下不在 keep（或 reserved）中的子目录，让产物树幂等收敛到当前 agent 集。"""
    if not parent.is_dir():
        return
    allow = keep | set(reserved)
    for child in parent.iterdir():
        if child.is_dir() and child.name not in allow:
            shutil.rmtree(child)
