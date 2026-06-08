"""session-extractor 单元测试（合成 fixture，无 live-session 回显噪音）。

运行：
    python3 -m unittest discover -s skills/session-extractor/scripts/tests
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))

from sessionlog import discover, layout  # noqa: E402
from sessionlog import render as R  # noqa: E402
from sessionlog import state as state_mod  # noqa: E402
from sessionlog.adapters import claude  # noqa: E402
from sessionlog.ir import (  # noqa: E402
    AGENT_MAIN, AGENT_SUBAGENT, BLOCK_TEXT, BLOCK_TOOL_RESULT, KIND_USER, Block, Event,
)

SID = "11111111-2222-3333-4444-555555555555"
CWD = "/work/proj"

MAIN_LINES = [
    {"type": "user", "timestamp": "2026-01-01T00:00:00Z", "sessionId": SID, "cwd": CWD,
     "gitBranch": "main",
     "message": {"role": "user", "content": [{"type": "text", "text": "<local-command-caveat>Caveat noise</local-command-caveat>"}]}},
    {"type": "user", "timestamp": "2026-01-01T00:00:01Z", "cwd": CWD,
     "message": {"role": "user", "content": [{"type": "text", "text": "Help me build a parser"}]}},
    {"type": "assistant", "timestamp": "2026-01-01T00:00:02Z",
     "message": {"role": "assistant", "model": "claude-x",
                 "usage": {"input_tokens": 10, "output_tokens": 5,
                           "cache_read_input_tokens": 3, "cache_creation_input_tokens": 2},
                 "content": [
                     {"type": "thinking", "thinking": ""},          # 空 thinking -> 不应渲染
                     {"type": "text", "text": "Sure, here is how."},
                     {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
                 ]}},
    {"type": "user", "timestamp": "2026-01-01T00:00:03Z",
     "message": {"role": "user", "content": [
         {"type": "tool_result", "tool_use_id": "t1", "is_error": False, "content": "file1\nfile2"}]}},
    {"type": "assistant", "isSidechain": True, "agentId": "explore-1",
     "timestamp": "2026-01-01T00:00:04Z",
     "message": {"role": "assistant", "model": "claude-x",
                 "content": [{"type": "text", "text": "subagent working"}]}},
    {"type": "file-history-snapshot", "timestamp": "2026-01-01T00:00:05Z",
     "snapshot": {"messageId": "m1"}},
]


def _write_fixture(root: Path) -> tuple[dict[str, str], Path]:
    """构造 <config>/projects/<enc>/<sid>.jsonl，返回 (env, cwd)。"""
    proj = root / "projects" / "-work-proj"
    proj.mkdir(parents=True)
    lines = [json.dumps(rec, ensure_ascii=False) for rec in MAIN_LINES]
    lines.append("this-is-not-json")  # 故意的坏行 -> parse_warnings
    (proj / f"{SID}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = {"CLAUDE_CONFIG_DIR": str(root), "CLAUDE_CODE_SESSION_ID": SID, "CLAUDECODE": "1"}
    return env, Path(CWD)


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "cfg"
        self.env, self.cwd = _write_fixture(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _session(self):
        refs = claude.locate(self.env, self.cwd, None, False, config_dir=str(self.root))
        self.assertEqual(len(refs), 1)
        return claude.parse(refs[0], env=self.env, config_dir=str(self.root))

    def test_platform_detection(self):
        self.assertEqual(discover.detect_platform(self.env), "claude")

    def test_locate_exact_session(self):
        refs = claude.locate(self.env, self.cwd, None, False, config_dir=str(self.root))
        self.assertEqual(refs[0].session_id, SID)

    def test_locate_missing_session_id_fails_loud(self):
        env = dict(self.env)
        env.pop("CLAUDE_CODE_SESSION_ID")
        with self.assertRaises(RuntimeError):
            claude.locate(env, self.cwd, None, False, config_dir=str(self.root))

    def test_title_skips_command_noise(self):
        session = self._session()
        self.assertEqual(session.title, "Claude Session: Help me build a parser")

    def test_agents_main_and_subagent(self):
        session = self._session()
        kinds = {a.key: a.kind for a in session.agents}
        self.assertEqual(kinds.get("main"), AGENT_MAIN)
        self.assertEqual(kinds.get("explore-1"), AGENT_SUBAGENT)

    def test_metadata_and_usage(self):
        session = self._session()
        self.assertEqual(session.cwd, CWD)
        self.assertEqual(session.git_branch, "main")
        self.assertEqual(session.models(), ["claude-x"])
        usage = session.main_agent().usage_total()
        self.assertEqual(usage.input_tokens, 10)
        self.assertEqual(usage.output_tokens, 5)

    def test_parse_warning_counted(self):
        session = self._session()
        self.assertEqual(session.raw_meta.get("parse_warnings"), 1)

    def test_platform_detection_codex_opencode(self):
        import os as _os
        self.assertEqual(discover.detect_platform({"CODEX_SANDBOX": "seatbelt"}), "codex")
        self.assertEqual(discover.detect_platform({"CODEX_THREAD_ID": "t"}), "codex")  # 非沙箱 codex
        self.assertEqual(discover.detect_platform({"OPENCODE": "1"}), "opencode")
        self.assertEqual(discover.detect_platform({"OPENCODE_RUN_ID": "x"}), "opencode")
        # 嵌套：最内层执行标识优先
        self.assertEqual(discover.detect_platform({"CODEX_SANDBOX": "seatbelt", "CLAUDE_CODE_SESSION_ID": "x"}), "codex")
        # 存活性闸门：残留(已死)的 OPENCODE_PID + claude id -> 仍判 claude（macOS pid_max < 99999）
        self.assertEqual(discover.detect_platform({"CLAUDE_CODE_SESSION_ID": "x", "OPENCODE_PID": "4000000"}), "claude")
        # 活 OPENCODE_PID（本进程）-> opencode
        self.assertEqual(discover.detect_platform({"OPENCODE_PID": str(_os.getpid())}), "opencode")
        with self.assertRaises(RuntimeError):
            discover.detect_platform({})


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "cfg"
        self.out = Path(self.tmp.name) / "session-extractor"
        self.env, self.cwd = _write_fixture(self.root)
        refs = claude.locate(self.env, self.cwd, None, False, config_dir=str(self.root))
        self.session = claude.parse(refs[0], env=self.env, config_dir=str(self.root))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, mode: str):
        st = {}
        if mode in ("structured", "both"):
            layout.run_structured(self.session, self.out, st)
        if mode in ("flat", "both"):
            layout.run_flat(self.session, self.out, st)
        layout.update_state(self.session, st)
        return st

    def _flat_base(self) -> Path:
        # flat 去 platform 后落在 out_root 根下、与 meta/summary 平级 -> 排除这俩定位时间戳目录
        bases = [p for p in self.out.iterdir() if p.is_dir() and p.name not in ("meta", "summary")]
        self.assertEqual(len(bases), 1)
        return bases[0]

    def test_structured_files_exist(self):
        self._run("structured")
        base = self.out / "meta" / "sessions" / "2026" / "01" / SID
        self.assertTrue((base / "index.md").is_file())
        self.assertTrue((base / "merged" / "session.md").is_file())
        self.assertTrue((base / "agents" / "main" / "session.md").is_file())
        self.assertTrue((base / "agents" / "explore-1" / "session.md").is_file())
        sum_dirs = [p for p in (self.out / "summary").iterdir() if p.is_dir()]
        self.assertEqual(len(sum_dirs), 1)  # 单个时间戳文件夹，无 YYYY/MM 多层、无漂移

    def test_flat_files_exist(self):
        self._run("flat")
        # flat 是单个本地时间戳文件夹（时区相关）-> 用 iterdir 定位，不硬编码
        base = self._flat_base()
        self.assertTrue((base / "index.md").is_file())
        self.assertTrue((base / "main.md").is_file())
        self.assertTrue((base / "explore-1.md").is_file())

    def test_flat_is_clean_detailed_flow(self):
        # flat = 人读完整详细流水：无 Conversation 段、过滤记账 meta（file-history-snapshot）、完整内联
        self._run("flat")
        base = self._flat_base()
        main_md = (base / "main.md").read_text(encoding="utf-8")
        self.assertNotIn("## Conversation", main_md)            # 无精简对话段
        self.assertIn("## Timeline", main_md)
        self.assertNotIn("`file-history-snapshot`", main_md)    # 记账 meta 被过滤
        self.assertNotIn("Open artifact", main_md)              # 完整内联，不外溢

    def test_no_empty_thinking_section(self):
        self._run("both")
        for md in self.out.rglob("*.md"):
            text = md.read_text(encoding="utf-8")
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if line.strip() == "#### Thinking":
                    nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    self.assertNotEqual(nxt, "_Empty_", f"空 Thinking 段出现在 {md}")

    def test_agent_summary_has_meta_links(self):
        # 对齐 .agents-log：agent summary 要有 Detailed log + Detailed index 两个到 meta 的链接
        self._run("structured")
        agent_sums = [p for p in (self.out / "summary").rglob("summary.md") if p.parent.name == "main"]
        self.assertEqual(len(agent_sums), 1)
        text = agent_sums[0].read_text(encoding="utf-8")
        self.assertIn("Detailed log", text)
        self.assertIn("Detailed index", text)
        self.assertIn("meta/sessions/", text)  # 链接确实指向 meta 树

    def test_tool_call_rendered(self):
        self._run("structured")
        detail = (self.out / "meta" / "sessions" / "2026" / "01" / SID
                  / "agents" / "main" / "session.md").read_text(encoding="utf-8")
        self.assertIn("Tool Call `Bash`", detail)
        self.assertIn("file1", detail)  # tool result content

    def test_state_loss_summary_no_drift(self):
        # 回归 #3：state 丢失/损坏重建时 summary 不漂移、不产生 -02 重复树。
        self._run("structured")
        layout.run_structured(self.session, self.out, {})  # 全新空 state 模拟丢失
        sum_dirs = [p for p in (self.out / "summary").iterdir() if p.is_dir()]
        self.assertEqual(len(sum_dirs), 1)  # 单个时间戳文件夹，无 YYYY/MM 多层、无漂移

    def test_orphan_agent_pruned(self):
        # 回归 #5：agent 集合缩小后旧 per-agent 产物被清理。
        st = self._run("both")
        sub_meta = self.out / "meta" / "sessions" / "2026" / "01" / SID / "agents" / "explore-1"
        flat_base = self._flat_base()
        sub_flat = flat_base / "explore-1.md"
        self.assertTrue(sub_meta.is_dir())
        self.assertTrue(sub_flat.is_file())
        shrunk = dataclasses.replace(self.session, agents=[a for a in self.session.agents if a.key == "main"])
        layout.run_structured(shrunk, self.out, st)
        layout.run_flat(shrunk, self.out, st)
        self.assertFalse(sub_meta.exists())
        self.assertFalse(sub_flat.exists())

    def test_mode_switch_index_follows_primary(self):
        # 回归 #1：同一 session 切换 --mode 后，全局索引（meta/index.md）跟随本次实际产出的树。
        import os as _os
        state_path = self.out / "meta" / "state" / f"claude__{SID}.json"
        st: dict = {}
        layout.run_structured(self.session, self.out, st)
        st["primary_tree"] = "structured"
        layout.update_state(self.session, st)
        state_mod.save_state(state_path, st)
        layout.run_flat(self.session, self.out, st)
        st["primary_tree"] = "flat"
        layout.update_state(self.session, st)
        state_mod.save_state(state_path, st)
        layout.write_global_index(self.out, state_mod.load_state)
        idx = (self.out / "meta" / "index.md").read_text(encoding="utf-8")
        # index 在 meta/ 下，链接相对 meta/ 计算
        flat_link = _os.path.relpath(self.out / st["flat"]["entry_relpath"], self.out / "meta")
        struct_link = _os.path.relpath(self.out / st["structured"]["entry_relpath"], self.out / "meta")
        self.assertIn(f"]({flat_link})", idx)
        self.assertNotIn(f"]({struct_link})", idx)

    def test_idempotent_dir_stable(self):
        st1 = self._run("both")
        before = sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file())
        # 复用 state 再跑一次
        layout.run_structured(self.session, self.out, st1)
        layout.run_flat(self.session, self.out, st1)
        after = sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file())
        self.assertEqual(before, after)
        self.assertEqual(len([p for p in (self.out / "summary").iterdir() if p.is_dir()]), 1)

    def test_incremental_growth_idempotent(self):
        # 增量幂等（内容增长）：同一 session 追加事件后重跑，仍写同一目录、覆盖刷新、
        # 不漂移、不堆目录、.owner 稳定，新内容反映、外溢 artifact 刷新。
        st = {}
        layout.run_structured(self.session, self.out, st)
        sdir = st["structured"]["summary_dir"]
        mdir = st["structured"]["meta_session_dir"]
        owner0 = (self.out / sdir / ".owner").read_text(encoding="utf-8")
        # 模拟会话增长：main 追加一段会外溢的大输出 + 一个可识别标记
        main = self.session.main_agent()
        big = "Z" * 5000
        last_ts = main.events[-1].timestamp
        main.events.append(Event(seq=500, timestamp=last_ts, kind=KIND_USER, role="user", is_main=True,
                                 blocks=[Block(type=BLOCK_TOOL_RESULT, tool_use_id="g", value=big)]))
        main.events.append(Event(seq=501, timestamp=last_ts, kind=KIND_USER, role="user", is_main=True,
                                 blocks=[Block(type=BLOCK_TEXT, text="NEW_INCREMENTAL_MARKER")]))
        layout.run_structured(self.session, self.out, st)  # 复用 state -> 增量刷新
        # 1) 路径不漂移
        self.assertEqual(st["structured"]["summary_dir"], sdir)
        self.assertEqual(st["structured"]["meta_session_dir"], mdir)
        # 2) summary 仍只 1 个时间戳目录（不堆、无碰撞后缀）
        self.assertEqual(len([p for p in (self.out / "summary").iterdir() if p.is_dir()]), 1)
        # 3) .owner 不变
        self.assertEqual((self.out / sdir / ".owner").read_text(encoding="utf-8"), owner0)
        # 4) 新内容反映在详细时间线
        detail = (self.out / mdir / "agents" / "main" / "session.md").read_text(encoding="utf-8")
        self.assertIn("NEW_INCREMENTAL_MARKER", detail)
        # 5) 增长的大输出外溢到 meta artifacts（覆盖刷新生效）
        rendered = [f for f in (self.out / mdir / "artifacts" / "main" / "rendered").iterdir() if f.is_file()]
        self.assertTrue(any(f.read_text(encoding="utf-8") == big for f in rendered))

    def test_stamp_collision_no_clobber(self):
        # 回归：两会话 started_at 同秒、不同 sid 时，summary 不互毁（碰撞自动加 __<sid> 后缀）。
        A = self.session  # claude / SID，含 main + explore-1
        B = dataclasses.replace(
            self.session,
            session_id="99999999-aaaa-bbbb-cccc-dddddddddddd",
            platform="codex",
            agents=[a for a in self.session.agents if a.key == "main"],  # B 只有 main
        )
        layout.run_structured(A, self.out, {})
        a_sub = next(p for p in (self.out / "summary").rglob("summary.md") if p.parent.name == "explore-1")
        self.assertTrue(a_sub.is_file())
        layout.run_structured(B, self.out, {})  # 同 started_at -> 同 stamp -> 碰撞
        self.assertTrue(a_sub.is_file(), "碰撞时 A 的 subagent 产物被误删")
        sum_dirs = sorted(p.name for p in (self.out / "summary").iterdir() if p.is_dir())
        self.assertEqual(len(sum_dirs), 2, f"碰撞应产生 2 个独立 summary 目录，实际 {sum_dirs}")
        # B 的目录带 sid 后缀；A 的是纯时间戳
        self.assertTrue(any("__99999999" in d for d in sum_dirs), sum_dirs)
        # 各自 .owner 标记归属正确
        a_owner = (self.out / "summary" / next(d for d in sum_dirs if "__" not in d) / ".owner").read_text()
        self.assertIn(f"claude__{SID}", a_owner)

    def test_collision_idempotent_reuse_owner(self):
        # 碰撞后重跑 B（带 state），应复用带后缀目录、不再新建，且认得自己的 .owner。
        A = self.session
        B = dataclasses.replace(self.session, session_id="99999999-aaaa-bbbb-cccc-dddddddddddd",
                                platform="codex", agents=[a for a in self.session.agents if a.key == "main"])
        layout.run_structured(A, self.out, {})
        stB = {}
        layout.run_structured(B, self.out, stB)
        first = stB["structured"]["summary_dir"]
        layout.run_structured(B, self.out, stB)  # 复用 state
        self.assertEqual(stB["structured"]["summary_dir"], first)
        self.assertEqual(len([p for p in (self.out / "summary").iterdir() if p.is_dir()]), 2)

    def test_summary_artifacts_reuse_meta(self):
        # 对齐 .agents-log：summary 树自身不产 artifacts/rendered；超阈值外溢复用 meta 树的 rendered（同内容去重）。
        big = "X" * 5000  # 超过 SUMMARY_VALUE_INLINE_LIMIT(1200) 与 TOOL_RESULT_INLINE_LIMIT(4000)
        main = self.session.main_agent()
        main.events.append(Event(
            seq=999, timestamp=main.events[-1].timestamp, kind=KIND_USER, role="user", is_main=True,
            blocks=[Block(type=BLOCK_TOOL_RESULT, tool_use_id="big", value=big)],
        ))
        self._run("structured")
        # summary 树下不应出现任何 artifacts/rendered 目录（即便没外溢也不该有空目录）
        self.assertEqual(list((self.out / "summary").rglob("rendered")), [])
        self.assertEqual(list((self.out / "summary").rglob("artifacts")), [])
        # 外溢文件落在 meta 树、内容完整
        rendered_files = [f for f in (self.out / "meta").rglob("*") if f.is_file() and "rendered" in f.parts]
        self.assertTrue(any(f.read_text(encoding="utf-8") == big for f in rendered_files))
        # agent summary 的外溢链接跨树指向 meta
        main_sum = next(p for p in (self.out / "summary").rglob("summary.md") if p.parent.name == "main")
        txt = main_sum.read_text(encoding="utf-8")
        self.assertIn("Open full artifact", txt)
        self.assertIn("meta/sessions/", txt)


class UtilTests(unittest.TestCase):
    def test_make_agent_key_reserved(self):
        from sessionlog.util import make_agent_key
        # 保留名（会撞 flat 的 index.md/usage.json）必须避开
        self.assertEqual(make_agent_key("index", set()), "index-02")
        self.assertEqual(make_agent_key("usage", set()), "usage-02")
        self.assertEqual(make_agent_key("Euler", set()), "euler")
        self.assertEqual(make_agent_key("x", {"x"}), "x-02")
        self.assertEqual(make_agent_key("anything", set(), is_main=True), "main")

    def test_to_int(self):
        from sessionlog.util import to_int
        self.assertEqual(to_int("5"), 5)
        self.assertEqual(to_int(None), 0)
        self.assertEqual(to_int("abc"), 0)
        self.assertEqual(to_int(3.0), 3)


class CodexAdapterTests(unittest.TestCase):
    MAIN_ID = "019e0000-0000-7000-8000-000000000001"
    SUB_ID = "019e0000-0000-7000-8000-000000000002"

    def setUp(self):
        from sessionlog.adapters import codex
        self.codex = codex
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "codex"
        day = self.home / "sessions" / "2026" / "02" / "01"
        day.mkdir(parents=True)
        main = [
            {"timestamp": "2026-02-01T00:00:00Z", "type": "session_meta",
             "payload": {"id": self.MAIN_ID, "cwd": "/work/cx", "timestamp": "2026-02-01T00:00:00Z",
                         "originator": "codex_cli_rs", "git": {"branch": "main"}}},
            {"timestamp": "2026-02-01T00:00:00.5Z", "type": "session_meta",
             "payload": {"id": "ancestor-replayed", "cwd": "/work/cx"}},  # fork 重放的祖先 meta -> 应跳过
            {"timestamp": "2026-02-01T00:00:01Z", "type": "turn_context",
             "payload": {"model": "gpt-5.5", "cwd": "/work/cx"}},
            {"timestamp": "2026-02-01T00:00:02Z", "type": "response_item",
             "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Build a parser"}]}},
            {"timestamp": "2026-02-01T00:00:03Z", "type": "response_item",
             "payload": {"type": "reasoning", "summary": [], "content": None, "encrypted_content": "gAAAAblob"}},
            {"timestamp": "2026-02-01T00:00:04Z", "type": "response_item",
             "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Sure"}]}},
            {"timestamp": "2026-02-01T00:00:05Z", "type": "response_item",
             "payload": {"type": "function_call", "name": "exec_command", "arguments": "{\"cmd\": \"ls\"}", "call_id": "c1"}},
            {"timestamp": "2026-02-01T00:00:06Z", "type": "response_item",
             "payload": {"type": "function_call_output", "call_id": "c1", "output": "file1\nfile2"}},
            {"timestamp": "2026-02-01T00:00:07Z", "type": "event_msg",
             "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 10, "output_tokens": 5,
                         "reasoning_output_tokens": 2, "cached_input_tokens": 3}}}},
            {"timestamp": "2026-02-01T00:00:08Z", "type": "event_msg",
             "payload": {"type": "agent_message", "message": "Sure"}},  # 与 assistant message 重复 -> 跳过
        ]
        sub = [
            {"timestamp": "2026-02-01T00:00:10Z", "type": "session_meta",
             "payload": {"id": self.SUB_ID, "cwd": "/work/cx", "thread_source": "subagent", "agent_nickname": "Euler",
                         "source": {"subagent": {"thread_spawn": {"parent_thread_id": self.MAIN_ID, "depth": 1}}}}},
            {"timestamp": "2026-02-01T00:00:11Z", "type": "response_item",
             "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "sub working"}]}},
        ]
        (day / f"rollout-2026-02-01T00-00-00-{self.MAIN_ID}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in main) + "\n", encoding="utf-8")
        (day / f"rollout-2026-02-01T00-00-10-{self.SUB_ID}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in sub) + "\n", encoding="utf-8")
        self.env = {"CODEX_HOME": str(self.home)}

    def _session(self):
        refs = self.codex.locate(self.env, Path("/work/cx"), self.MAIN_ID, False, config_dir=str(self.home))
        self.assertEqual(len(refs), 1)
        return self.codex.parse(refs[0])

    def test_main_and_subagent(self):
        s = self._session()
        self.assertEqual(s.platform, "codex")
        kinds = {a.key: a.kind for a in s.agents}
        self.assertEqual(kinds.get("main"), AGENT_MAIN)
        self.assertEqual(kinds.get("euler"), AGENT_SUBAGENT)

    def test_model_cwd_git(self):
        s = self._session()
        self.assertIn("gpt-5.5", s.models())
        self.assertEqual(s.cwd, "/work/cx")
        self.assertEqual(s.git_branch, "main")

    def test_title_skips_injected_context(self):
        self.assertEqual(self._session().title, "Codex Session: Build a parser")

    def test_function_call_decoded_and_paired(self):
        from sessionlog.ir import BLOCK_TOOL_RESULT, BLOCK_TOOL_USE
        blocks = [b for a in self._session().agents for e in a.events for b in e.blocks]
        self.assertTrue(any(b.type == BLOCK_TOOL_USE and isinstance(b.value, dict) and b.value.get("cmd") == "ls" for b in blocks))
        self.assertTrue(any(b.type == BLOCK_TOOL_RESULT and b.tool_use_id == "c1" for b in blocks))

    def test_usage_from_token_count(self):
        u = self._session().main_agent().usage_total()
        self.assertEqual(u.output_tokens, 5)
        self.assertEqual(u.reasoning_tokens, 2)

    def test_dup_agent_message_not_double_rendered(self):
        texts = [b.text for a in self._session().agents for e in a.events for b in e.blocks if b.type == BLOCK_TEXT]
        self.assertEqual(texts.count("Sure"), 1)

    def test_malformed_thread_spawn_no_crash(self):
        # 畸形 subagent rollout（thread_spawn 非 dict）不应让 locate() 崩溃并连累所有 codex 会话
        day = self.home / "sessions" / "2026" / "02" / "01"
        bad_id = "019e0000-0000-7000-8000-0000000000ff"
        bad = [{"timestamp": "2026-02-01T00:00:20Z", "type": "session_meta",
                "payload": {"id": bad_id, "cwd": "/work/cx", "thread_source": "subagent",
                            "source": {"subagent": {"thread_spawn": "not-a-dict"}}}}]
        (day / f"rollout-2026-02-01T00-00-20-{bad_id}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in bad) + "\n", encoding="utf-8")
        self.assertEqual(self._session().main_agent().kind, AGENT_MAIN)  # 不抛即通过


class OpencodeAdapterTests(unittest.TestCase):
    def setUp(self):
        from sessionlog.adapters import opencode
        self.oc = opencode
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "share"
        db = self.data / "opencode" / "opencode.db"
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(str(db))
        con.executescript(
            "CREATE TABLE session(id TEXT PRIMARY KEY, parent_id TEXT, slug TEXT, directory TEXT, title TEXT,"
            " version TEXT, time_created INTEGER, time_updated INTEGER);"
            "CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, data TEXT, time_created INTEGER);"
            "CREATE TABLE part(id TEXT PRIMARY KEY, message_id TEXT, data TEXT, time_created INTEGER);"
        )
        con.execute("INSERT INTO session VALUES(?,?,?,?,?,?,?,?)",
                    ("ses_root", None, "quiet-planet", "/work/oc", "Build parser", "1.2.27", 1700000000000, 1700000001000))
        con.execute("INSERT INTO session VALUES(?,?,?,?,?,?,?,?)",
                    ("ses_child", "ses_root", "calm-star", "/work/oc", "Audit (@explore subagent)", "1.2.27", 1700000002000, 1700000003000))
        con.execute("INSERT INTO message VALUES(?,?,?,?)",
                    ("msg_u", "ses_root", json.dumps({"role": "user", "time": {"created": 1700000000000}}), 1700000000000))
        con.execute("INSERT INTO part VALUES(?,?,?,?)",
                    ("prt_u", "msg_u", json.dumps({"type": "text", "text": "Build a parser"}), 1700000000000))
        con.execute("INSERT INTO message VALUES(?,?,?,?)",
                    ("msg_a", "ses_root", json.dumps({"role": "assistant", "time": {"created": 1700000001000},
                     "providerID": "opencode", "modelID": "big-pickle", "cost": 0.0,
                     "tokens": {"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 3, "write": 2}}}), 1700000001000))
        con.execute("INSERT INTO part VALUES(?,?,?,?)",
                    ("prt_a1", "msg_a", json.dumps({"type": "text", "text": "Sure"}), 1700000001000))
        con.execute("INSERT INTO part VALUES(?,?,?,?)",
                    ("prt_a2", "msg_a", json.dumps({"type": "tool", "tool": "read", "callID": "c1",
                     "state": {"status": "completed", "input": {"filePath": "x.py"}, "output": "file contents"}}), 1700000001000))
        con.execute("INSERT INTO message VALUES(?,?,?,?)",
                    ("msg_c", "ses_child", json.dumps({"role": "assistant", "time": {"created": 1700000002000},
                     "providerID": "opencode", "modelID": "big-pickle"}), 1700000002000))
        con.execute("INSERT INTO part VALUES(?,?,?,?)",
                    ("prt_c", "msg_c", json.dumps({"type": "text", "text": "sub audit"}), 1700000002000))
        con.commit()
        con.close()
        self.env = {"XDG_DATA_HOME": str(self.data)}

    def _session(self, sid="ses_root"):
        refs = self.oc.locate(self.env, Path("/work/oc"), sid, False)
        self.assertEqual(len(refs), 1)
        return self.oc.parse(refs[0])

    def test_main_and_subagent(self):
        s = self._session()
        self.assertEqual(s.platform, "opencode")
        self.assertEqual(s.main_agent().kind, AGENT_MAIN)
        self.assertTrue(any(a.kind == AGENT_SUBAGENT for a in s.agents))

    def test_root_climb_from_child(self):
        self.assertEqual(self._session("ses_child").session_id, "ses_root")

    def test_user_text_from_part(self):
        s = self._session()
        texts = [b.text for e in s.main_agent().events for b in e.blocks if b.type == BLOCK_TEXT]
        self.assertIn("Build a parser", texts)

    def test_tool_input_output_blocks(self):
        from sessionlog.ir import BLOCK_TOOL_RESULT, BLOCK_TOOL_USE
        blocks = [b for a in self._session().agents for e in a.events for b in e.blocks]
        self.assertTrue(any(b.type == BLOCK_TOOL_USE and b.name == "read" for b in blocks))
        self.assertTrue(any(b.type == BLOCK_TOOL_RESULT and b.value == "file contents" for b in blocks))

    def test_usage_model_cwd(self):
        s = self._session()
        u = s.main_agent().usage_total()
        self.assertEqual(u.output_tokens, 5)
        self.assertEqual(u.cache_read_tokens, 3)
        self.assertIn("opencode/big-pickle", s.models())
        self.assertEqual(s.cwd, "/work/oc")

    def test_title_from_session(self):
        self.assertEqual(self._session().title, "Opencode Session: Build parser")

    def test_error_turn_captured(self):
        # 只有 data.error、无 part 的 assistant turn 不应被静默丢弃
        db = self.data / "opencode" / "opencode.db"
        con = sqlite3.connect(str(db))
        con.execute("INSERT INTO message VALUES(?,?,?,?)", ("msg_err", "ses_root",
                    json.dumps({"role": "assistant", "time": {"created": 1700000004000},
                                "error": {"name": "APIError", "data": {"statusCode": 404}}}), 1700000004000))
        con.commit()
        con.close()
        texts = [b.text for e in self._session().main_agent().events for b in e.blocks if b.type == BLOCK_TEXT]
        self.assertTrue(any("[error]" in t and "APIError" in t for t in texts))

    def test_nonexistent_session_fails_loud(self):
        with self.assertRaises(RuntimeError):
            self.oc.locate(self.env, Path("/work/oc"), "ses_does_not_exist", False)

    def test_parent_cycle_terminates(self):
        # parent_id 成环不应死循环（_root_id 环检测 + BFS visited）
        db = self.data / "opencode" / "opencode.db"
        con = sqlite3.connect(str(db))
        con.execute("INSERT INTO session VALUES(?,?,?,?,?,?,?,?)", ("ses_a", "ses_b", "a", "/work/oc", "A", "1", 1, 1))
        con.execute("INSERT INTO session VALUES(?,?,?,?,?,?,?,?)", ("ses_b", "ses_a", "b", "/work/oc", "B", "1", 1, 1))
        con.commit()
        con.close()
        refs = self.oc.locate(self.env, Path("/work/oc"), "ses_a", False)
        self.assertIsNotNone(self.oc.parse(refs[0]))  # 不挂起即通过


class RenderSeamTests(unittest.TestCase):
    """回归 #6：渲染器不得用字符串 'main' 当主 agent 哨兵——主 agent 判定走 Event.is_main。"""

    def _ctx(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        return R.Ctx(base / "x.md", R.ArtifactStore(base / "rendered"))

    def _event(self, source_path, is_main):
        return Event(seq=0, timestamp=None, kind="assistant", role="assistant",
                     blocks=[Block(type=BLOCK_TEXT, text="hi")], source_path=source_path, is_main=is_main)

    def test_main_agent_no_source_suffix_when_path_not_main(self):
        ctx = self._ctx()
        # 主 agent 但 source_path 是 codex/opencode 风格（非 'main'）：不应加来源后缀。
        main_md = "\n".join(R.render_event_detail(1, self._event("rollout-x.jsonl", True), ctx, show_source=True))
        self.assertNotIn("[rollout-x.jsonl]", main_md)
        convo = "\n".join(R.render_conversation([self._event("rollout-x.jsonl", True)], ctx))
        self.assertNotIn("[rollout-x.jsonl]", convo)

    def test_subagent_gets_source_suffix(self):
        ctx = self._ctx()
        sub_md = "\n".join(R.render_event_detail(2, self._event("ses_abc", False), ctx, show_source=True))
        self.assertIn("[ses_abc]", sub_md)

    def test_spill_false_inlines_full_content(self):
        # flat 用 spill=False：超阈值大内容也完整内联、不外溢成文件
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        ctx = R.Ctx(base / "x.md", R.ArtifactStore(base / "rendered"), spill=False)
        big = "X" * 50000
        out = "\n".join(R._value_section("Result", big, ctx, "p", R.TOOL_RESULT_INLINE_LIMIT))
        self.assertIn(big, out)               # 完整内联
        self.assertNotIn("Open artifact", out)  # 不外溢


if __name__ == "__main__":
    unittest.main(verbosity=2)
