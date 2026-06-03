from pathlib import Path
import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator


ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def temp_repo() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="validate-release-") as temp_dir:
        repo = Path(temp_dir) / "repo"
        shutil.copytree(
            ROOT,
            repo,
            ignore=shutil.ignore_patterns(
                ".git",
                ".idea",
                "__pycache__",
                "*.pyc",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
            ),
        )
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "--all"], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Validate Release Tests",
                "-c",
                "user.email=validate-release-tests@example.invalid",
                "commit",
                "-m",
                "initial",
                "--quiet",
            ],
            cwd=repo,
            check=True,
        )
        yield repo


def run_sync(repo: Path) -> None:
    subprocess.run([sys.executable, "scripts/sync_adapters.py"], cwd=repo, check=True)


def run_validate(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/validate_release.py"],
        cwd=repo,
        text=True,
        capture_output=True,
    )


class ValidateReleaseTests(unittest.TestCase):
    def test_validate_release_passes_after_sync(self):
        with temp_repo() as repo:
            run_sync(repo)
            result = run_validate(repo)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("validate_release=ok", result.stdout)

    def test_token_scan_rejects_realistic_secret(self):
        with temp_repo() as repo:
            bad = repo / ".llm-wiki-test-secret.txt"
            token_prefix = "llmw_"
            token_body = "real_secret_value_123456"
            bad.write_text(f"LLM_WIKI_UPLOAD_TOKEN={token_prefix}{token_body}\n", encoding="utf-8")
            result = run_validate(repo)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("token-like string", result.stdout + result.stderr)

    def test_validate_release_rejects_manual_generated_file_edit(self):
        with temp_repo() as repo:
            run_sync(repo)
            generated = repo / "plugins/llm-wiki-client-claude/skills/llm-wiki-cloud-query/SKILL.md"
            original = generated.read_text(encoding="utf-8")
            generated.write_text(original + "\n<!-- stale generated validator probe -->\n", encoding="utf-8")
            result = run_validate(repo)
            self.assertNotEqual(result.returncode, 0)
            output = result.stdout + result.stderr
            self.assertIn("generated files are stale", output)
            self.assertIn("modified generated outputs", output)

    def test_validate_release_rejects_untracked_generated_extra_file(self):
        with temp_repo() as repo:
            run_sync(repo)
            extra = repo / "plugins/llm-wiki-client-claude/untracked-extra.txt"
            extra.write_text("test-only untracked generated file\n", encoding="utf-8")

            result = run_validate(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("untracked generated file", result.stdout + result.stderr)

    def test_validate_release_checks_codex_manifest_skill_root(self):
        with temp_repo() as repo:
            run_sync(repo)
            manifest = repo / "plugins/llm-wiki-client-codex/.codex-plugin/plugin.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["skills"] = "./codex/skills/"
            manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = run_validate(repo)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Codex manifest skill root", result.stdout + result.stderr)

    def test_validate_release_rejects_readme_install_command_name_mismatch(self):
        with temp_repo() as repo:
            readme = repo / "README.md"
            original = readme.read_text(encoding="utf-8")
            marketplace = json.loads((repo / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
            expected = f"/plugin install {marketplace['plugins'][0]['name']}@{marketplace['name']}"
            self.assertIn(expected, original)
            readme.write_text(
                original.replace(expected, f"/plugin install wrong-client@{marketplace['name']}", 1),
                encoding="utf-8",
            )
            result = run_validate(repo)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("README install command", result.stdout + result.stderr)

    def test_validate_release_allows_synced_generated_changes(self):
        with temp_repo() as repo:
            template = repo / "src/skills/llm-wiki-cloud-query/SKILL.md.tmpl"
            original = template.read_text(encoding="utf-8")
            template.write_text(
                original + "\nSynced generated validator probe.\n",
                encoding="utf-8",
            )
            run_sync(repo)

            result = run_validate(repo)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("validate_release=ok", result.stdout)

    def test_validate_release_allows_synced_generated_deletions(self):
        with temp_repo() as repo:
            source_path = "src/skills/llm-wiki-cloud-query/SKILL.md.tmpl"
            generated_paths = [
                "plugins/llm-wiki-client-claude/skills/llm-wiki-cloud-query/SKILL.md",
                "plugins/llm-wiki-client-codex/skills/llm-wiki-cloud-query/SKILL.md",
                "plugins/llm-wiki-client-opencode/skills/llm-wiki-cloud-query/SKILL.md",
            ]

            source = repo / source_path
            source.unlink()
            run_sync(repo)

            status_before_stage = subprocess.run(
                ["git", "status", "--short", "--", *generated_paths],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            )
            for generated_path in generated_paths:
                with self.subTest(generated_path=generated_path):
                    self.assertIn(f" D {generated_path}", status_before_stage.stdout)

            subprocess.run(["git", "add", "--all"], cwd=repo, check=True)
            status_after_stage = subprocess.run(
                ["git", "status", "--short", "--", source_path, *generated_paths],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(f"D  {source_path}", status_after_stage.stdout)
            for generated_path in generated_paths:
                with self.subTest(staged_generated_path=generated_path):
                    self.assertIn(f"D  {generated_path}", status_after_stage.stdout)

            result = run_validate(repo)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("validate_release=ok", result.stdout)

    def test_validate_release_rejects_new_generated_outputs(self):
        with temp_repo() as repo:
            source = repo / "src/skills/llm-wiki-cloud-new/SKILL.md.tmpl"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        "---",
                        "name: llm-wiki-cloud-new",
                        "description: Test-only generated skill.",
                        "version: {{version}}",
                        "---",
                        "",
                        "# Test-only Generated Skill",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "src/skills/llm-wiki-cloud-new/SKILL.md.tmpl"], cwd=repo, check=True)

            result = run_validate(repo)

            self.assertNotEqual(result.returncode, 0)
            output = result.stdout + result.stderr
            self.assertIn("generated files are stale", output)
            self.assertIn("untracked", output)

            run_sync(repo)
            subprocess.run(["git", "add", "--all"], cwd=repo, check=True)
            synced_result = run_validate(repo)
            self.assertEqual(synced_result.returncode, 0, synced_result.stdout + synced_result.stderr)
            self.assertIn("validate_release=ok", synced_result.stdout)


class DocumentationTests(unittest.TestCase):
    def test_readme_mentions_all_clients_and_install_commands(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for phrase in [
            "Claude Code",
            "Codex",
            "OpenCode",
            "llm-wiki-cloud",
            "/plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud",
            "/plugin install llm-wiki-client@llm-wiki-cloud",
            "/plugin update llm-wiki-client@llm-wiki-cloud",
            "/plugin uninstall llm-wiki-client@llm-wiki-cloud",
            "/plugin marketplace remove llm-wiki-cloud",
            "claude plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud",
            "claude plugin install llm-wiki-client@llm-wiki-cloud",
            "claude plugin update llm-wiki-client@llm-wiki-cloud",
            "claude plugin uninstall llm-wiki-client@llm-wiki-cloud",
            "claude plugin marketplace remove llm-wiki-cloud",
            "codex plugin marketplace add AndyKong2020/LLM-Wiki-Marketplace-Cloud",
            "codex plugin marketplace upgrade llm-wiki-cloud",
            "codex plugin add llm-wiki-client@llm-wiki-cloud",
            "codex plugin remove llm-wiki-client@llm-wiki-cloud",
            "codex plugin marketplace remove llm-wiki-cloud",
            "bootstrap.sh | bash",
            "uninstall.sh | bash",
            "维护发布",
            "llm-wiki-cloud-mount",
            "llm-wiki-cloud-backflow",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        self.assertNotIn("llm-wiki-cloud-test", text)
        self.assertNotIn("LLM-Wiki-Marketplace-Multiclient-Test", text)
        self.assertNotIn("multiclient-test", text)
        self.assertNotIn("模拟用户使用流程", text)
        self.assertNotIn("CLAUDE_CONFIG_DIR", text)
        self.assertNotIn("CODEX_HOME", text)
        self.assertNotIn("OPENCODE_CONFIG_DIR", text)
        self.assertNotIn("python3 scripts/test_isolated_clients.py", text)
        self.assertNotIn("codex plugin marketplace upgrade\n", text)
        self.assertNotIn("/llm-wiki-client:", text)
        self.assertNotIn("/wiki-cloud-mount", text)
        self.assertNotIn("/wiki-cloud-backflow", text)


if __name__ == "__main__":
    unittest.main()
