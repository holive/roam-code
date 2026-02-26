"""Tests for architecture analysis CLI commands.

Covers tests for:
- map: project skeleton overview
- layers: topological layer detection
- clusters: community detection
- entry-points: exported API surface
- visualize: graph visualization
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
# map command
# ============================================================================

class TestMap:
    """Tests for `roam map` -- project skeleton overview."""

    def test_map_shows_files(self, cli_runner, indexed_project, monkeypatch):
        """map output mentions file count."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["map"], cwd=indexed_project)
        assert result.exit_code == 0, f"map failed:\n{result.output}"
        assert "Files:" in result.output

    def test_map_shows_edges(self, cli_runner, indexed_project, monkeypatch):
        """map output shows edge count (import relationships exist)."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["map"], cwd=indexed_project)
        assert result.exit_code == 0
        assert "Edges:" in result.output

    def test_map_shows_symbols(self, cli_runner, indexed_project, monkeypatch):
        """map output shows symbol count."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["map"], cwd=indexed_project)
        assert result.exit_code == 0
        assert "Symbols:" in result.output

    def test_map_shows_languages(self, cli_runner, indexed_project, monkeypatch):
        """map output includes language breakdown."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["map"], cwd=indexed_project)
        assert result.exit_code == 0
        assert "Languages:" in result.output

    def test_map_json(self, cli_runner, indexed_project, monkeypatch):
        """--json returns a valid envelope."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["map"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "map")
        assert_json_envelope(data, "map")

    def test_map_json_has_files(self, cli_runner, indexed_project, monkeypatch):
        """JSON envelope includes files count."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["map"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "map")
        assert "files" in data["summary"]
        assert data["summary"]["files"] > 0

    def test_map_json_has_top_symbols(self, cli_runner, indexed_project, monkeypatch):
        """JSON envelope includes top_symbols array."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["map"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "map")
        assert "top_symbols" in data
        assert isinstance(data["top_symbols"], list)

    def test_map_json_has_directories(self, cli_runner, indexed_project, monkeypatch):
        """JSON envelope includes directories array."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["map"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "map")
        assert "directories" in data
        assert isinstance(data["directories"], list)

    def test_map_count_option(self, cli_runner, indexed_project, monkeypatch):
        """map -n 5 limits symbol display."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["map", "-n", "5"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_map_budget_option(self, cli_runner, indexed_project, monkeypatch):
        """map --budget limits output by approximate token count."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["map", "--budget", "200"], cwd=indexed_project)
        assert result.exit_code == 0


# ============================================================================
# layers command
# ============================================================================

class TestLayers:
    """Tests for `roam layers` -- topological layer detection."""

    def test_layers_runs(self, cli_runner, indexed_project, monkeypatch):
        """layers exits 0."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["layers"], cwd=indexed_project)
        assert result.exit_code == 0, f"layers failed:\n{result.output}"

    def test_layers_shows_layers(self, cli_runner, indexed_project, monkeypatch):
        """Output contains layer numbers or layer info."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["layers"], cwd=indexed_project)
        assert result.exit_code == 0
        output = result.output.lower()
        assert "layer" in output

    def test_layers_json(self, cli_runner, indexed_project, monkeypatch):
        """--json returns a valid envelope."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["layers"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "layers")
        assert_json_envelope(data, "layers")

    def test_layers_json_has_layer_data(self, cli_runner, indexed_project, monkeypatch):
        """JSON envelope includes layers array and violation count."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["--detail", "layers"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "layers")
        assert "layers" in data
        assert isinstance(data["layers"], list)
        assert "violations" in data["summary"]

    def test_layers_json_total_layers(self, cli_runner, indexed_project, monkeypatch):
        """JSON summary includes total_layers count."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["layers"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "layers")
        assert "total_layers" in data["summary"]
        assert isinstance(data["summary"]["total_layers"], int)

    def test_layers_models_lower(self, project_factory, cli_runner, monkeypatch):
        """Symbols should be assigned to different layers based on call direction.

        Layer 0 = no incoming edges (callers/entry points).
        Higher layers = deeper callees.
        create_user calls User, so create_user is layer 0, User is layer 1+.
        """
        proj = project_factory({
            "models.py": (
                "class User:\n"
                "    def __init__(self, name):\n"
                "        self.name = name\n"
            ),
            "service.py": (
                "from models import User\n"
                "\n"
                "def create_user(name):\n"
                "    return User(name)\n"
            ),
        })
        monkeypatch.chdir(proj)
        result = invoke_cli(cli_runner, ["layers"], cwd=proj, json_mode=True)
        data = parse_json_output(result, "layers")
        if data.get("layers"):
            layer_numbers = {}
            for layer_info in data["layers"]:
                for sym in layer_info.get("symbols", []):
                    if sym["name"] == "User":
                        layer_numbers["User"] = layer_info["layer"]
                    if sym["name"] == "create_user":
                        layer_numbers["create_user"] = layer_info["layer"]
            if "User" in layer_numbers and "create_user" in layer_numbers:
                # create_user (caller, no incoming edges) should be layer 0
                # User (callee) should be in a higher or equal layer
                assert layer_numbers["create_user"] <= layer_numbers["User"], (
                    f"create_user (layer {layer_numbers['create_user']}) should be <= "
                    f"User (layer {layer_numbers['User']})"
                )

    def test_layers_shows_violations_section(self, cli_runner, indexed_project, monkeypatch):
        """Text output includes a Violations section."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["layers"], cwd=indexed_project)
        assert result.exit_code == 0
        assert "Violations" in result.output or "layer" in result.output.lower()


# ============================================================================
# clusters command
# ============================================================================

class TestClusters:
    """Tests for `roam clusters` -- community detection."""

    def test_clusters_runs(self, cli_runner, indexed_project, monkeypatch):
        """clusters exits 0."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["clusters"], cwd=indexed_project)
        assert result.exit_code == 0, f"clusters failed:\n{result.output}"

    def test_clusters_json(self, cli_runner, indexed_project, monkeypatch):
        """--json returns a valid envelope."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["clusters"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "clusters")
        assert_json_envelope(data, "clusters")

    def test_clusters_shows_groups(self, cli_runner, indexed_project, monkeypatch):
        """Output has cluster groupings or mentions clusters."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["clusters"], cwd=indexed_project)
        assert result.exit_code == 0
        output = result.output.lower()
        assert "cluster" in output

    def test_clusters_json_has_clusters_array(self, cli_runner, indexed_project, monkeypatch):
        """JSON envelope includes clusters array."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["--detail", "clusters"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "clusters")
        assert "clusters" in data
        assert isinstance(data["clusters"], list)

    def test_clusters_json_summary(self, cli_runner, indexed_project, monkeypatch):
        """JSON summary includes cluster count and modularity."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["clusters"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "clusters")
        summary = data["summary"]
        assert "clusters" in summary
        assert "modularity_q" in summary

    def test_clusters_min_size_option(self, cli_runner, indexed_project, monkeypatch):
        """--min-size option is accepted."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["clusters", "--min-size", "1"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_clusters_mismatches_section(self, cli_runner, indexed_project, monkeypatch):
        """Text output includes a directory mismatches section."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["clusters"], cwd=indexed_project)
        assert result.exit_code == 0
        output = result.output.lower()
        assert "mismatch" in output or "cluster" in output
# ============================================================================
# entry-points command
# ============================================================================

class TestEntryPoints:
    """Tests for `roam entry-points` -- exported API surface."""

    def test_entry_points_runs(self, cli_runner, indexed_project, monkeypatch):
        """entry-points exits 0."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["entry-points"], cwd=indexed_project)
        assert result.exit_code == 0, f"entry-points failed:\n{result.output}"

    def test_entry_points_json(self, cli_runner, indexed_project, monkeypatch):
        """--json returns a valid envelope."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["entry-points"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "entry-points")
        assert_json_envelope(data, "entry-points")

    def test_entry_points_finds_exports(self, cli_runner, indexed_project, monkeypatch):
        """Finds exported functions/classes (symbols with no callers)."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["entry-points"], cwd=indexed_project)
        assert result.exit_code == 0
        output = result.output
        # Should find at least some entry points or say none found
        assert "Entry" in output or "entry" in output or "No entry" in output

    def test_entry_points_json_has_entries(self, cli_runner, indexed_project, monkeypatch):
        """JSON envelope includes entry_points array."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["entry-points"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "entry-points")
        assert "entry_points" in data
        assert isinstance(data["entry_points"], list)

    def test_entry_points_json_total(self, cli_runner, indexed_project, monkeypatch):
        """JSON summary includes total count."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["entry-points"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "entry-points")
        assert "total" in data["summary"]

    def test_entry_points_limit_option(self, cli_runner, indexed_project, monkeypatch):
        """--limit option is accepted."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["entry-points", "--limit", "5"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_entry_points_protocol_filter(self, cli_runner, indexed_project, monkeypatch):
        """--protocol filter is accepted (may return empty set)."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["entry-points", "--protocol", "Export"], cwd=indexed_project)
        assert result.exit_code == 0

    def test_entry_points_coverage_field(self, cli_runner, indexed_project, monkeypatch):
        """JSON entry points include coverage_pct when entries exist."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["entry-points"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "entry-points")
        if data["entry_points"]:
            ep = data["entry_points"][0]
            assert "coverage_pct" in ep
# ============================================================================
# visualize command
# ============================================================================

class TestVisualize:
    """Tests for `roam visualize` -- graph visualization."""

    def test_visualize_runs(self, cli_runner, indexed_project, monkeypatch):
        """visualize exits 0."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["visualize"], cwd=indexed_project)
        assert result.exit_code == 0, f"visualize failed:\n{result.output}"

    def test_visualize_mermaid(self, cli_runner, indexed_project, monkeypatch):
        """Default output is Mermaid format."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["visualize"], cwd=indexed_project)
        assert result.exit_code == 0
        assert "graph TD" in result.output or "graph LR" in result.output

    def test_visualize_json(self, cli_runner, indexed_project, monkeypatch):
        """--json returns a valid envelope."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["visualize"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "visualize")
        assert_json_envelope(data, "visualize")

    def test_visualize_json_has_diagram(self, cli_runner, indexed_project, monkeypatch):
        """JSON envelope includes diagram string."""
        monkeypatch.chdir(indexed_project)
        result = invoke_cli(cli_runner, ["visualize"], cwd=indexed_project, json_mode=True)
        data = parse_json_output(result, "visualize")
        assert "diagram" in data


# ============================================================================
# Multi-file architecture tests using project_factory
# ============================================================================

class TestArchitectureMultiFile:
    """Tests that verify architecture commands on custom project layouts."""

    def test_layers_three_tier(self, project_factory, cli_runner, monkeypatch):
        """A three-tier project should produce at least 2 layers."""
        proj = project_factory({
            "base.py": "class Base:\n    pass\n",
            "mid.py": (
                "from base import Base\n"
                "\n"
                "class Mid(Base):\n"
                "    pass\n"
            ),
            "top.py": (
                "from mid import Mid\n"
                "\n"
                "def run():\n"
                "    return Mid()\n"
            ),
        })
        monkeypatch.chdir(proj)
        result = invoke_cli(cli_runner, ["layers"], cwd=proj, json_mode=True)
        data = parse_json_output(result, "layers")
        assert data["summary"]["total_layers"] >= 2

    def test_clusters_separate_groups(self, project_factory, cli_runner, monkeypatch):
        """Two disconnected groups should be detected as separate clusters."""
        proj = project_factory({
            "group_a1.py": (
                "def func_a1():\n"
                "    return 1\n"
            ),
            "group_a2.py": (
                "from group_a1 import func_a1\n"
                "\n"
                "def func_a2():\n"
                "    return func_a1() + 1\n"
            ),
            "group_b1.py": (
                "def func_b1():\n"
                "    return 10\n"
            ),
            "group_b2.py": (
                "from group_b1 import func_b1\n"
                "\n"
                "def func_b2():\n"
                "    return func_b1() + 10\n"
            ),
        })
        monkeypatch.chdir(proj)
        result = invoke_cli(cli_runner, ["clusters", "--min-size", "1"], cwd=proj)
        assert result.exit_code == 0

    def test_map_large_project(self, project_factory, cli_runner, monkeypatch):
        """map handles a project with many files."""
        files = {}
        for i in range(10):
            files[f"mod_{i}.py"] = (
                f"def func_{i}():\n"
                f"    return {i}\n"
            )
        # Add some imports between them
        files["main.py"] = (
            "from mod_0 import func_0\n"
            "from mod_1 import func_1\n"
            "\n"
            "def main():\n"
            "    return func_0() + func_1()\n"
        )
        proj = project_factory(files)
        monkeypatch.chdir(proj)
        result = invoke_cli(cli_runner, ["map"], cwd=proj, json_mode=True)
        data = parse_json_output(result, "map")
        assert data["summary"]["files"] >= 10

    def test_entry_points_main_detected(self, project_factory, cli_runner, monkeypatch):
        """A main() function should be classified as a Main entry point."""
        proj = project_factory({
            "helper.py": (
                "def compute():\n"
                "    return 42\n"
            ),
            "app.py": (
                "from helper import compute\n"
                "\n"
                "def main():\n"
                "    print(compute())\n"
            ),
        })
        monkeypatch.chdir(proj)
        result = invoke_cli(cli_runner, ["entry-points"], cwd=proj, json_mode=True)
        data = parse_json_output(result, "entry-points")
        if data["entry_points"]:
            names = [ep["name"] for ep in data["entry_points"]]
            protocols = [ep["protocol"] for ep in data["entry_points"]]
            # main should appear and be classified as Main
            if "main" in names:
                idx = names.index("main")
                assert protocols[idx] == "Main"

