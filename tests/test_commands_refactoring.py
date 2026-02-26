"""Tests for refactoring-related CLI commands.

Covers ~40 tests across 5 commands: dead, safe-delete, split, conventions, breaking.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))
from conftest import invoke_cli, parse_json_output, assert_json_envelope

from roam.cli import cli


# ---------------------------------------------------------------------------
# Override cli_runner fixture to handle Click 8.2+ (mix_stderr removed)
# ---------------------------------------------------------------------------

@pytest.fixture
def cli_runner():
    """Provide a Click CliRunner compatible with Click 8.2+."""
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


# ============================================================================
# dead command
# ============================================================================

class TestDead:
    """Tests for `roam dead` -- unreferenced exports."""

    def test_dead_runs(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["dead"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_dead_json(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["dead"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "dead")
        assert_json_envelope(data, "dead")

    def test_dead_json_has_confidence_arrays(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["--detail", "dead"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "dead")
        assert "high_confidence" in data
        assert "low_confidence" in data

    def test_dead_json_summary_has_counts(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["dead"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "dead")
        summary = data.get("summary", {})
        for key in ["safe", "review", "intentional"]:
            assert key in summary, f"Missing '{key}' in dead summary: {summary}"

    def test_dead_json_summary_has_unused_assignments(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["dead"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "dead")
        summary = data.get("summary", {})
        assert "unused_assignments" in summary

    def test_dead_all_flag(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["dead", "--all"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_dead_by_directory(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["dead", "--by-directory"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_dead_by_kind(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["dead", "--by-kind"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_dead_summary_only(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["dead", "--summary"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_dead_clusters(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["dead", "--clusters"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_dead_text_shows_exports(self, cli_runner, indexed_project, monkeypatch):
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["dead"], cwd=indexed_project)
        assert result.exit_code == 0
        out = result.output
        assert "Unreferenced" in out or "none" in out.lower() or "dead" in out.lower()

