#!/usr/bin/env python3
"""session-extractor CLI：把当前 agent 会话记录转成 Markdown 到 .session-extractor/。

用法（在某个 agent 会话内由 skill 触发，或手动）：
    python3 extract.py [--mode structured|flat|both] [--out DIR]
                       [--platform claude|codex|opencode] [--session ID | --all]
                       [--cwd DIR] [--config-dir DIR]

默认：探测平台 -> 取当前 session（env 提供身份）-> structured 形态 -> 写到 <cwd>/.session-extractor。
多次触发幂等：同一 session 始终写到同一目录并整体覆盖刷新。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sessionlog import discover, layout  # noqa: E402
from sessionlog import state as state_mod  # noqa: E402
from sessionlog.adapters import get_adapter  # noqa: E402

# 这些是「面向用户的、预期内」的错误：打印简洁信息并非零退出，不吐 traceback。
_USER_ERRORS = (NotImplementedError, FileNotFoundError, RuntimeError, ValueError)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="session-extractor", description=__doc__)
    parser.add_argument("--mode", choices=["structured", "flat", "both"], default="structured")
    parser.add_argument("--out", help="输出根目录（默认 <cwd>/.session-extractor）")
    parser.add_argument("--platform", choices=list(discover.VALID_PLATFORMS),
                        help="当前客户端（skill 场景由 agent 自行判断后显式传，首选）；省略则回退 env 自动探测")
    parser.add_argument("--session", help="指定 session id（默认取当前会话）")
    parser.add_argument("--all", action="store_true", help="处理本项目（cwd）的全部会话")
    parser.add_argument("--cwd", help="覆盖工作目录（默认当前目录）")
    parser.add_argument("--config-dir", help="覆盖平台配置/数据目录（默认按各平台 env+约定）")
    parser.add_argument("--quiet", action="store_true", help="只在出错时输出")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    env = dict(os.environ)
    # resolve() 解符号链接，便于与各平台存储里的 realpath（如 opencode 的 /private/...）匹配
    cwd = Path(args.cwd).expanduser().resolve() if args.cwd else Path.cwd().resolve()
    out_root = Path(args.out).expanduser().resolve() if args.out else (cwd / ".session-extractor")

    platform = discover.detect_platform(env, args.platform)
    if args.platform is None:
        # skill 场景应由 agent 自行判断并显式传 --platform；这里是 standalone 回退，显式提示。
        print(
            f"[session-extractor] 未显式指定 --platform，按环境变量回退判断为 '{platform}'"
            f"（skill 场景建议由 agent 自判并显式传 --platform）。",
            file=sys.stderr,
        )
    adapter = get_adapter(platform)
    refs = adapter.locate(env, cwd, args.session, args.all, config_dir=args.config_dir)
    if not refs:
        raise RuntimeError("没有找到可导出的 session。")

    # 对齐 .agents-log：state 在 meta/state/，锁在 meta/locks/。
    state_dir = out_root / "meta" / "state"
    locks_dir = out_root / "meta" / "locks"
    results: list[tuple[str, str, int, str]] = []
    for ref in refs:
        session = adapter.parse(ref, env=env, config_dir=args.config_dir)
        key = layout.state_key(session)
        state_path = state_dir / f"{key}.json"
        with state_mod.session_lock(locks_dir, key):
            st = state_mod.load_state(state_path)
            if args.mode in ("structured", "both"):
                entry = layout.run_structured(session, out_root, st)
            if args.mode in ("flat", "both"):
                entry = layout.run_flat(session, out_root, st)
            # 本次实际产出的「主树」，供全局索引选取入口（structured 优先于 flat）。
            st["primary_tree"] = "structured" if args.mode in ("structured", "both") else "flat"
            layout.update_state(session, st)
            state_mod.save_state(state_path, st)
        results.append((session.platform, session.session_id, len(session.agents), entry))

    # 全局索引「读全量 state 快照 -> 写文件」用一把保留名全局锁串行化，避免跨进程 lost-update。
    with state_mod.session_lock(locks_dir, "__global_index__"):
        index = layout.write_global_index(out_root, state_mod.load_state)

    if not args.quiet:
        print(f"session-extractor: {len(results)} session(s) [{args.mode}] -> {out_root}")
        for platform_name, sid, n_agents, entry in results:
            print(f"  [{platform_name}] {sid}  {n_agents} agent(s) -> {entry}")
        try:
            rel_index = os.path.relpath(index, Path.cwd())
        except ValueError:
            rel_index = str(index)
        print(f"  index: {rel_index}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except _USER_ERRORS as exc:
        print(f"session-extractor: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
