from __future__ import annotations

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_supported_system_adapters_are_thin_and_consistent():
    adapter_paths = [
        ".codex/AGENTS.md",
        ".claude/CLAUDE.md",
        "CURSOR.md",
        "GEMINI.md",
        "OPENCODE.md",
    ]
    for rel_path in adapter_paths:
        text = _read(rel_path)
        assert "%USERPROFILE%\\AGENTS.md" in text
        assert "docs/agents/AGENTS.md" in text
        assert len([line for line in text.splitlines() if line.strip()]) <= 6


def test_codex_config_has_no_legacy_approval_policy_or_workflow_block():
    text = _read(".codex/config.toml")
    parsed = tomllib.loads(text)
    assert isinstance(parsed, dict)
    assert 'approval_policy = "on-request"' not in text
    assert "[workflow]" not in text


def test_repo_agent_guide_is_marked_as_repo_specific_addendum():
    text = _read("docs/agents/AGENTS.md")
    assert "repo-specific addendum" in text.lower()
    assert "%USERPROFILE%\\AGENTS.md" in text


def test_repo_local_skills_supplement_global_baseline_without_legacy_commit_output():
    for rel_path in [
        ".codex/skills/architect/SKILL.md",
        ".codex/skills/developer/SKILL.md",
        ".codex/skills/reviewer/SKILL.md",
    ]:
        text = _read(rel_path)
        assert "global baseline" in text.lower()
    developer_text = _read(".codex/skills/developer/SKILL.md")
    assert "Commit message text (mandatory)" not in developer_text


def test_bootstrap_policy_files_exist_and_routing_matrix_has_expected_profiles():
    routing_path = ROOT / "policy" / "task-routing-matrix.json"
    orchestrator_path = ROOT / "policy" / "team-lead-orchestrator.md"
    assert routing_path.exists()
    assert orchestrator_path.exists()

    payload = json.loads(routing_path.read_text(encoding="utf-8"))
    assert payload["sizes"] == ["trivial", "non_trivial"]
    assert set(payload["profiles"]) == {
        "repo_change",
        "repo_read",
        "content_task",
        "general",
    }


def test_gitignore_covers_local_agent_runtime_artifacts():
    text = _read(".gitignore")
    for expected_line in [
        ".claude/settings.local.json",
        ".agent-memory/",
        ".scratchpad/",
        "coordination/tasks.jsonl",
        "coordination/state/",
        "coordination/reviews/",
        "reports/",
    ]:
        assert expected_line in text
