#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MCP_URL = "https://wiki.andykong.top/mcp"
SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")
OPENCODE_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TOKEN_RE = re.compile(r"\bllmw_(?!<token-from-operator>)(?!token-from-operator\b)[A-Za-z0-9_=-]{12,}\b")

README_MARKETPLACE_ADD_COMMAND = (
    "/plugin marketplace add "
    "AndyKong2020/LLM-Wiki-Marketplace-Cloud"
)
JSON_FILES = [
    ".claude-plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
    "plugins/llm-wiki-client-claude/.claude-plugin/plugin.json",
    "plugins/llm-wiki-client-claude/.mcp.json",
    "plugins/llm-wiki-client-codex/.codex-plugin/plugin.json",
    "plugins/llm-wiki-client-codex/.mcp.json",
    "plugins/llm-wiki-client-opencode/opencode.json",
]
GENERATED_SCAN_ROOTS = [
    ".claude-plugin",
    ".agents",
    "plugins/llm-wiki-client-claude",
    "plugins/llm-wiki-client-codex",
    "plugins/llm-wiki-client-opencode",
]
GENERATED_DIFF_PATHS = [
    ".claude-plugin",
    ".agents",
    "plugins/llm-wiki-client-claude",
    "plugins/llm-wiki-client-codex",
    "plugins/llm-wiki-client-opencode",
]
TEMP_COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    ".idea",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
)
SKILL_ROOTS = [
    "plugins/llm-wiki-client-claude/skills",
    "plugins/llm-wiki-client-codex/skills",
    "plugins/llm-wiki-client-opencode/skills",
]
MOUNT_SKILLS = [
    "plugins/llm-wiki-client-claude/skills/llm-wiki-cloud-mount/SKILL.md",
    "plugins/llm-wiki-client-codex/skills/llm-wiki-cloud-mount/SKILL.md",
    "plugins/llm-wiki-client-opencode/skills/llm-wiki-cloud-mount/SKILL.md",
]
SKIP_TOKEN_PARTS = {".git", ".idea"}
SKIP_TOKEN_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff"}


class ValidationError(Exception):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def rel_to(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def read_text(relative_path: str) -> str:
    path = ROOT / relative_path
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"missing file: {relative_path}")
    except UnicodeDecodeError as exc:
        fail(f"invalid UTF-8 in {relative_path}: {exc}")
    raise AssertionError("unreachable")


def read_version() -> str:
    version = read_text("VERSION").strip()
    if not SEMVER_RE.fullmatch(version):
        fail(f"invalid VERSION semver: {version}")
    return version


def load_json(relative_path: str) -> Any:
    try:
        return json.loads(read_text(relative_path))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {relative_path}: {exc.msg}")


def load_json_files() -> dict[str, Any]:
    return {relative_path: load_json(relative_path) for relative_path in JSON_FILES}


def require_dict(data: Any, relative_path: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        fail(f"expected JSON object in {relative_path}")
    return data


def get_plugin_version_from_claude_marketplace(data: Any) -> str:
    marketplace = require_dict(data, ".claude-plugin/marketplace.json")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        fail("Claude marketplace has no plugins")
    plugin = plugins[0]
    if not isinstance(plugin, dict):
        fail("Claude marketplace plugin entry is not an object")
    version = plugin.get("version")
    if not isinstance(version, str):
        fail("Claude marketplace plugin version missing")
    return version


def get_manifest_version(data: Any, relative_path: str) -> str:
    manifest = require_dict(data, relative_path)
    version = manifest.get("version")
    if not isinstance(version, str):
        fail(f"version missing in {relative_path}")
    return version


def get_name(data: dict[str, Any], relative_path: str) -> str:
    name = data.get("name")
    if not isinstance(name, str) or not name:
        fail(f"name missing in {relative_path}")
    return name


def get_marketplace_plugin_name(data: Any, relative_path: str) -> tuple[str, str]:
    marketplace = require_dict(data, relative_path)
    marketplace_name = get_name(marketplace, relative_path)
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        fail(f"marketplace has no plugins in {relative_path}")
    plugin = plugins[0]
    if not isinstance(plugin, dict):
        fail(f"marketplace plugin entry is not an object in {relative_path}")
    plugin_name = plugin.get("name")
    if not isinstance(plugin_name, str) or not plugin_name:
        fail(f"marketplace plugin name missing in {relative_path}")
    return marketplace_name, plugin_name


def get_readme_command_names(json_data: dict[str, Any]) -> tuple[str, str]:
    marketplace_names = set()
    plugin_names = set()

    for relative_path in [".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"]:
        marketplace_name, plugin_name = get_marketplace_plugin_name(json_data[relative_path], relative_path)
        marketplace_names.add(marketplace_name)
        plugin_names.add(plugin_name)

    for relative_path in [
        "plugins/llm-wiki-client-claude/.claude-plugin/plugin.json",
        "plugins/llm-wiki-client-codex/.codex-plugin/plugin.json",
    ]:
        manifest = require_dict(json_data[relative_path], relative_path)
        plugin_names.add(get_name(manifest, relative_path))

    if len(marketplace_names) != 1:
        fail(f"marketplace name mismatch across generated JSON: {sorted(marketplace_names)}")
    if len(plugin_names) != 1:
        fail(f"plugin name mismatch across generated JSON: {sorted(plugin_names)}")
    return next(iter(plugin_names)), next(iter(marketplace_names))


def parse_frontmatter(relative_path: str) -> dict[str, str]:
    text = read_text(relative_path)
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        fail(f"frontmatter missing in {relative_path}")

    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return fields
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()

    fail(f"frontmatter terminator missing in {relative_path}")


def iter_skill_files(skill_root: str) -> list[str]:
    root = ROOT / skill_root
    if not root.is_dir():
        fail(f"missing skill root: {skill_root}")
    skill_files = sorted(path for path in root.glob("*/SKILL.md") if path.is_file())
    if not skill_files:
        fail(f"no generated skills in {skill_root}")
    return [rel(path) for path in skill_files]


def check_versions(version: str, json_data: dict[str, Any]) -> None:
    version_checks = {
        ".claude-plugin/marketplace.json": get_plugin_version_from_claude_marketplace(
            json_data[".claude-plugin/marketplace.json"]
        ),
        "plugins/llm-wiki-client-claude/.claude-plugin/plugin.json": get_manifest_version(
            json_data["plugins/llm-wiki-client-claude/.claude-plugin/plugin.json"],
            "plugins/llm-wiki-client-claude/.claude-plugin/plugin.json",
        ),
        "plugins/llm-wiki-client-codex/.codex-plugin/plugin.json": get_manifest_version(
            json_data["plugins/llm-wiki-client-codex/.codex-plugin/plugin.json"],
            "plugins/llm-wiki-client-codex/.codex-plugin/plugin.json",
        ),
    }
    for relative_path, actual in version_checks.items():
        if actual != version:
            fail(f"version mismatch in {relative_path}: {actual} != {version}")

    for skill_root in SKILL_ROOTS:
        for skill_file in iter_skill_files(skill_root):
            skill_version = parse_frontmatter(skill_file).get("version")
            if skill_version != version:
                fail(f"skill version mismatch in {skill_file}: {skill_version} != {version}")


def check_codex_manifest_skill_root(json_data: dict[str, Any]) -> None:
    relative_path = "plugins/llm-wiki-client-codex/.codex-plugin/plugin.json"
    manifest = require_dict(json_data[relative_path], relative_path)
    actual = manifest.get("skills")
    expected = "./skills/"
    if actual != expected:
        fail(f"Codex manifest skill root mismatch in {relative_path}: {actual} != {expected}")


def check_readme_install_commands(json_data: dict[str, Any]) -> None:
    plugin_name, marketplace_name = get_readme_command_names(json_data)
    readme = read_text("README.md")
    expected_commands = {
        "/plugin marketplace add ": README_MARKETPLACE_ADD_COMMAND,
        "/plugin install ": f"/plugin install {plugin_name}@{marketplace_name}",
        "/plugin update ": f"/plugin update {plugin_name}@{marketplace_name}",
        "/plugin uninstall ": f"/plugin uninstall {plugin_name}@{marketplace_name}",
        "/plugin marketplace update ": f"/plugin marketplace update {marketplace_name}",
        "/plugin marketplace remove ": f"/plugin marketplace remove {marketplace_name}",
    }
    required_prefixes = {
        "/plugin marketplace add ",
        "/plugin install ",
        "/plugin update ",
        "/plugin uninstall ",
        "/plugin marketplace remove ",
    }
    readme_commands = {
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s*(/plugin\s+[^\n`]+?)\s*$", readme)
    }

    for prefix, expected in expected_commands.items():
        if prefix in required_prefixes and expected not in readme_commands:
            fail(f"README install command missing or stale in README.md: expected {expected}")
        for command in sorted(command for command in readme_commands if command.startswith(prefix)):
            if command != expected:
                fail(f"README install command mismatch in README.md: {command} != {expected}")


def check_canonical_mcp_url(json_data: dict[str, Any]) -> None:
    mcp_config = json.dumps(json_data["plugins/llm-wiki-client-claude/.mcp.json"], ensure_ascii=False)
    if CANONICAL_MCP_URL not in mcp_config:
        fail("canonical mcp url missing in plugins/llm-wiki-client-claude/.mcp.json")

    opencode_config = json.dumps(json_data["plugins/llm-wiki-client-opencode/opencode.json"], ensure_ascii=False)
    if CANONICAL_MCP_URL not in opencode_config:
        fail("canonical mcp url missing in plugins/llm-wiki-client-opencode/opencode.json")

    for mount_skill in MOUNT_SKILLS:
        if CANONICAL_MCP_URL not in read_text(mount_skill):
            fail(f"canonical mcp url missing in {mount_skill}")


def check_opencode_skill_names() -> None:
    root = ROOT / "plugins/llm-wiki-client-opencode/skills"
    if not root.is_dir():
        fail("missing OpenCode skill root: plugins/llm-wiki-client-opencode/skills")
    for skill_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if not OPENCODE_SKILL_NAME_RE.fullmatch(skill_dir.name):
            fail(f"invalid OpenCode skill directory name: {skill_dir.name}")
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            fail(f"missing OpenCode skill file: {rel(skill_file)}")
        name = parse_frontmatter(rel(skill_file)).get("name")
        if name != skill_dir.name:
            fail(f"OpenCode skill name mismatch in {rel(skill_file)}: {name} != {skill_dir.name}")
        if not OPENCODE_SKILL_NAME_RE.fullmatch(name):
            fail(f"invalid OpenCode skill name: {name}")


def check_no_command_directories() -> None:
    for scan_root in GENERATED_SCAN_ROOTS:
        root = ROOT / scan_root
        if not root.exists():
            continue
        for path in sorted(candidate for candidate in root.rglob("commands") if candidate.is_dir()):
            fail(f"unexpected command directory: {rel(path)}")


def check_no_unrendered_templates() -> None:
    for scan_root in GENERATED_SCAN_ROOTS:
        root = ROOT / scan_root
        if not root.exists():
            fail(f"missing generated root: {scan_root}")
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "{{" in text or "}}" in text:
                fail(f"unrendered template marker in {rel(path)}")


def should_skip_token_scan(path: Path) -> bool:
    if not path.is_file():
        return True
    if any(part in SKIP_TOKEN_PARTS for part in path.parts):
        return True
    return path.suffix.lower() in SKIP_TOKEN_SUFFIXES


def check_no_token_like_strings() -> None:
    for path in sorted(ROOT.rglob("*")):
        if should_skip_token_scan(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if TOKEN_RE.search(text):
            fail(f"token-like string in {rel(path)}")


def summarize_items(items: list[str], *, limit: int = 8) -> str:
    shown = items[:limit]
    more = len(items) - len(shown)
    summary = ", ".join(shown)
    if more:
        summary = f"{summary}, ... (+{more} more)"
    return summary


def run_sync_adapters(root: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/sync_adapters.py"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if detail:
            fail(f"sync_adapters.py failed: {detail}")
        fail(f"sync_adapters.py failed with exit code {result.returncode}")


def get_untracked_generated_files() -> list[str]:
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *GENERATED_DIFF_PATHS,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if detail:
            fail(f"git status failed while checking generated files: {detail}")
        fail(f"git status failed while checking generated files with exit code {result.returncode}")
    return sorted(line[3:] for line in result.stdout.splitlines() if line.startswith("?? "))


GeneratedSnapshot = dict[str, tuple[str, int, bytes | str]]


def snapshot_generated_paths(root: Path) -> GeneratedSnapshot:
    snapshot: GeneratedSnapshot = {}
    for relative_root in GENERATED_DIFF_PATHS:
        generated_root = root / relative_root
        if not generated_root.exists():
            continue
        paths = [generated_root]
        if generated_root.is_dir() and not generated_root.is_symlink():
            paths = sorted(generated_root.rglob("*"))
        for path in paths:
            if path.is_dir() and not path.is_symlink():
                continue
            relative_path = rel_to(path, root)
            if path.is_symlink():
                snapshot[relative_path] = ("symlink", 0, os.readlink(path))
                continue
            if path.is_file():
                mode = path.stat().st_mode & 0o777
                snapshot[relative_path] = ("file", mode, path.read_bytes())
    return snapshot


def describe_generated_snapshot_changes(before: GeneratedSnapshot, after: GeneratedSnapshot) -> list[str]:
    before_paths = set(before)
    after_paths = set(after)
    added = sorted(after_paths - before_paths)
    removed = sorted(before_paths - after_paths)
    modified = sorted(path for path in before_paths & after_paths if before[path] != after[path])

    details = []
    if modified:
        details.append(f"modified generated outputs: {summarize_items(modified)}")
    if added:
        details.append(f"untracked generated outputs after sync: {summarize_items(added)}")
    if removed:
        details.append(f"removed generated outputs after sync: {summarize_items(removed)}")
    return details


def check_generated_files_current() -> None:
    untracked_files = get_untracked_generated_files()
    if untracked_files:
        fail(f"untracked generated file: {summarize_items(untracked_files)}")

    current_snapshot = snapshot_generated_paths(ROOT)

    with tempfile.TemporaryDirectory(prefix="validate-release-") as temp_dir:
        temp_root = Path(temp_dir) / "repo"
        shutil.copytree(ROOT, temp_root, ignore=TEMP_COPY_IGNORE)
        run_sync_adapters(temp_root)
        expected_snapshot = snapshot_generated_paths(temp_root)

    changes = describe_generated_snapshot_changes(current_snapshot, expected_snapshot)
    if changes:
        fail(f"generated files are stale: {'; '.join(changes)}")


def validate() -> None:
    version = read_version()
    json_data = load_json_files()
    check_versions(version, json_data)
    check_codex_manifest_skill_root(json_data)
    check_readme_install_commands(json_data)
    check_canonical_mcp_url(json_data)
    check_opencode_skill_names()
    check_no_command_directories()
    check_no_unrendered_templates()
    check_no_token_like_strings()
    check_generated_files_current()


def main() -> int:
    try:
        validate()
    except ValidationError as exc:
        print(f"validate_release=failed reason={exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"validate_release=failed reason=unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("validate_release=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
