"""Tests for health/quality CLI commands.

Covers ~60 tests across 8 commands: health, weather, debt, complexity,
alerts, trend, fitness, snapshot. Uses CliRunner for in-process testing.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))
from conftest import invoke_cli, parse_json_output, assert_json_envelope

from roam.cli import cli


# ============================================================================
# TestHealth
# ============================================================================

class TestHealth:
    """Tests for `roam health` -- overall health score (0-100)."""

    def test_health_shows_score(self, cli_runner, indexed_project, monkeypatch):
        """roam health output should contain a numeric score."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["health"], cwd=indexed_project)
        assert result.exit_code == 0, f"health failed: {result.output}"
        assert "Health Score:" in result.output or "health" in result.output.lower()

    def test_health_verdict(self, cli_runner, indexed_project, monkeypatch):
        """roam health should contain a VERDICT line."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["health"], cwd=indexed_project)
        assert result.exit_code == 0, f"health failed: {result.output}"
        assert "VERDICT:" in result.output, (
            f"Missing VERDICT line in output:\n{result.output}"
        )

    def test_health_json(self, cli_runner, indexed_project, monkeypatch):
        """roam --json health should return a valid envelope with health_score and verdict."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["health"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "health")
        assert_json_envelope(data, "health")
        summary = data["summary"]
        assert "health_score" in summary, f"Missing health_score in summary: {summary}"
        assert "verdict" in summary, f"Missing verdict in summary: {summary}"

    def test_health_json_has_metrics(self, cli_runner, indexed_project, monkeypatch):
        """roam --json health summary should include expected metric keys."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["health"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "health")
        summary = data["summary"]
        expected_keys = ["health_score", "verdict", "tangle_ratio", "issue_count", "severity"]
        for key in expected_keys:
            assert key in summary, f"Missing '{key}' in summary: {list(summary.keys())}"

    def test_health_score_range(self, cli_runner, indexed_project, monkeypatch):
        """Health score should be between 0 and 100."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["health"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "health")
        score = data["summary"]["health_score"]
        assert 0 <= score <= 100, f"Health score out of range: {score}"

    def test_health_json_has_structural_keys(self, cli_runner, indexed_project, monkeypatch):
        """roam --json health should include top-level structural data keys."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["--detail", "health"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "health")
        # These keys should exist at top level of the envelope
        for key in ["cycles", "god_components", "bottlenecks"]:
            assert key in data, f"Missing '{key}' in JSON output: {list(data.keys())}"

    def test_health_severity_counts(self, cli_runner, indexed_project, monkeypatch):
        """roam --json health severity field should have expected levels."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["health"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "health")
        severity = data["summary"]["severity"]
        assert isinstance(severity, dict)
        for level in ["CRITICAL", "WARNING", "INFO"]:
            assert level in severity, f"Missing '{level}' in severity: {severity}"

    def test_health_text_has_sections(self, cli_runner, indexed_project, monkeypatch):
        """roam health text output should have structural sections."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["--detail", "health"], cwd=indexed_project)
        assert result.exit_code == 0
        out = result.output
        assert "=== Cycles ===" in out, f"Missing Cycles section:\n{out}"
        assert "=== God Components" in out, f"Missing God Components section:\n{out}"
        assert "=== Bottlenecks" in out, f"Missing Bottlenecks section:\n{out}"

    def test_health_no_framework_flag(self, cli_runner, indexed_project, monkeypatch):
        """roam health --no-framework should run without error."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["health", "--no-framework"], cwd=indexed_project)
        assert result.exit_code == 0, f"health --no-framework failed: {result.output}"


# ============================================================================
# TestWeather
# ============================================================================

class TestWeather:
    """Tests for `roam weather` -- churn x complexity hotspot ranking."""

    def test_weather_runs(self, cli_runner, indexed_project, monkeypatch):
        """roam weather should exit 0."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["weather"], cwd=indexed_project)
        assert result.exit_code == 0, f"weather failed: {result.output}"

    def test_weather_json(self, cli_runner, indexed_project, monkeypatch):
        """roam --json weather should return a valid envelope."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["weather"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "weather")
        assert_json_envelope(data, "weather")
        assert "hotspots" in data or "hotspots" in data.get("summary", {})

    def test_weather_shows_metrics(self, cli_runner, indexed_project, monkeypatch):
        """roam weather output should have structured content."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["weather"], cwd=indexed_project)
        assert result.exit_code == 0
        out = result.output
        # Either shows hotspot table or "No churn data" message
        assert ("Hotspots" in out or "Score" in out
                or "No churn data" in out), (
            f"Missing expected output in weather:\n{out}"
        )

    def test_weather_json_summary_keys(self, cli_runner, indexed_project, monkeypatch):
        """roam --json weather summary should have hotspots count."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["weather"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "weather")
        summary = data.get("summary", {})
        assert "hotspots" in summary, f"Missing 'hotspots' in summary: {summary}"

    def test_weather_limit_option(self, cli_runner, indexed_project, monkeypatch):
        """roam weather -n 5 should run without error."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["weather", "-n", "5"], cwd=indexed_project)
        assert result.exit_code == 0, f"weather -n 5 failed: {result.output}"


# ============================================================================
# TestDebt
# ============================================================================

class TestDebt:
    """Tests for `roam debt` -- technical debt overview."""

    def test_debt_runs(self, cli_runner, indexed_project, monkeypatch):
        """roam debt should exit 0."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["debt"], cwd=indexed_project)
        assert result.exit_code == 0, f"debt failed: {result.output}"

    def test_debt_json(self, cli_runner, indexed_project, monkeypatch):
        """roam --json debt should return a valid envelope."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["debt"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "debt")
        assert_json_envelope(data, "debt")
        assert "summary" in data

    def test_debt_shows_categories(self, cli_runner, indexed_project, monkeypatch):
        """roam debt output should display debt categories or file stats."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["debt"], cwd=indexed_project)
        assert result.exit_code == 0
        out = result.output
        # Should show either the debt table or "No file stats" message
        assert ("Debt" in out or "debt" in out.lower()
                or "No file stats" in out), (
            f"Missing debt categories in output:\n{out}"
        )

    def test_debt_json_summary_keys(self, cli_runner, indexed_project, monkeypatch):
        """roam --json debt summary should have expected metric keys."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["debt"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "debt")
        summary = data.get("summary", {})
        assert "total_files" in summary or "total_debt" in summary, (
            f"Missing debt stats in summary: {summary}"
        )

    def test_debt_by_kind(self, cli_runner, indexed_project, monkeypatch):
        """roam debt --by-kind should group by directory."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["debt", "--by-kind"], cwd=indexed_project)
        assert result.exit_code == 0, f"debt --by-kind failed: {result.output}"

    def test_debt_threshold(self, cli_runner, indexed_project, monkeypatch):
        """roam debt --threshold 0 should run without error."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["debt", "--threshold", "0"], cwd=indexed_project)
        assert result.exit_code == 0, f"debt --threshold 0 failed: {result.output}"

    def test_debt_json_has_items(self, cli_runner, indexed_project, monkeypatch):
        """roam --json debt should have items or groups array."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["debt"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "debt")
        assert "items" in data or "groups" in data, (
            f"Missing items/groups in debt JSON: {list(data.keys())}"
        )

    def test_debt_roi_text(self, cli_runner, indexed_project, monkeypatch):
        """roam debt --roi should print ROI estimate summary."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["debt", "--roi"], cwd=indexed_project)
        assert result.exit_code == 0, f"debt --roi failed: {result.output}"
        out = result.output
        assert "Refactoring ROI estimate" in out, f"Missing ROI estimate in output:\n{out}"
        assert "h/quarter" in out, f"Missing ROI hours in output:\n{out}"

    def test_debt_roi_json(self, cli_runner, indexed_project, monkeypatch):
        """roam --json debt --roi should include ROI summary object."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(
            cli_runner,
            ["debt", "--roi"],
            cwd=indexed_project,
            json_mode=True,
        )
        data = parse_json_output(result, "debt")
        assert "roi" in data, f"Missing roi key in debt JSON: {list(data.keys())}"
        roi = data["roi"]
        assert "estimated_hours_saved_quarter" in roi
        assert "confidence" in roi


# ============================================================================
# TestComplexity
# ============================================================================

class TestComplexity:
    """Tests for `roam complexity` -- complexity ranking."""

    def test_complexity_runs(self, cli_runner, indexed_project, monkeypatch):
        """roam complexity should exit 0."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["complexity"], cwd=indexed_project)
        assert result.exit_code == 0, f"complexity failed: {result.output}"

    def test_complexity_json(self, cli_runner, indexed_project, monkeypatch):
        """roam --json complexity should return a valid envelope."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["complexity"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "complexity")
        assert_json_envelope(data, "complexity")

    def test_complexity_shows_ranking(self, cli_runner, indexed_project, monkeypatch):
        """roam complexity should list symbols by complexity."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["complexity"], cwd=indexed_project)
        assert result.exit_code == 0
        out = result.output
        # Should show complexity data or "No matching symbols" or analysis stats
        assert ("complexity" in out.lower() or "analyzed" in out.lower()
                or "No matching" in out), (
            f"Missing complexity ranking in output:\n{out}"
        )

    def test_complexity_json_has_symbols(self, cli_runner, indexed_project, monkeypatch):
        """roam --json complexity should have symbols array."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["complexity"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "complexity")
        assert "symbols" in data or "files" in data, (
            f"Missing symbols/files in complexity JSON: {list(data.keys())}"
        )

    def test_complexity_threshold(self, cli_runner, indexed_project, monkeypatch):
        """roam complexity --threshold 0 should include all symbols."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["complexity", "--threshold", "0"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_complexity_by_file(self, cli_runner, indexed_project, monkeypatch):
        """roam complexity --by-file should group results by file."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["complexity", "--by-file"], cwd=indexed_project)
        assert result.exit_code == 0, f"complexity --by-file failed: {result.output}"

    def test_complexity_bumpy_road(self, cli_runner, indexed_project, monkeypatch):
        """roam complexity --bumpy-road should run without error."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["complexity", "--bumpy-road"], cwd=indexed_project)
        assert result.exit_code == 0, f"complexity --bumpy-road failed: {result.output}"

    def test_complexity_json_summary(self, cli_runner, indexed_project, monkeypatch):
        """roam --json complexity summary should include analysis stats."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["complexity"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "complexity")
        summary = data.get("summary", {})
        assert "total_analyzed" in summary or "files" in summary or "mode" in summary, (
            f"Missing expected keys in complexity summary: {summary}"
        )


# ============================================================================
# TestAlerts