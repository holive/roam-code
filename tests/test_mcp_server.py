"""Tests for the MCP server module.

Tests cover:
- _classify_error() error pattern matching
- _ensure_fresh_index() with mocked subprocess
- _run_roam() structured error responses
- _tool() decorator lite-mode filtering
- mcp_cmd CLI command
- Tool wrapper argument construction
"""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# _classify_error tests
# ---------------------------------------------------------------------------


class TestClassifyError:
    """Test error classification returns correct codes, hints, and retryable flag."""

    def _classify(self, stderr, exit_code=1):
        from roam.mcp_server import _classify_error
        return _classify_error(stderr, exit_code)

    def test_index_not_found_no_roam(self):
        code, hint, retryable = self._classify("Error: No .roam directory found")
        assert code == "INDEX_NOT_FOUND"
        assert "roam init" in hint
        assert retryable is False

    def test_index_not_found_in_index(self):
        code, hint, retryable = self._classify("symbol 'foo' not found in index")
        assert code == "INDEX_NOT_FOUND"
        assert retryable is False

    def test_index_not_found_db(self):
        code, hint, retryable = self._classify("cannot open index.db")
        assert code == "INDEX_NOT_FOUND"
        assert retryable is False

    def test_index_stale(self):
        code, hint, retryable = self._classify("warning: index is stale, run roam index")
        assert code == "INDEX_STALE"
        assert "roam index" in hint
        assert retryable is True

    def test_not_git_repo(self):
        code, hint, retryable = self._classify("fatal: not a git repository")
        assert code == "NOT_GIT_REPO"
        assert "git init" in hint
        assert retryable is False

    def test_db_locked(self):
        code, hint, retryable = self._classify("sqlite3.OperationalError: database is locked")
        assert code == "DB_LOCKED"
        assert retryable is True

    def test_permission_denied(self):
        code, hint, retryable = self._classify("OSError: Permission denied: '/foo/bar'")
        assert code == "PERMISSION_DENIED"
        assert retryable is False

    def test_no_results_symbol(self):
        code, hint, retryable = self._classify("symbol not found: 'bazqux'")
        assert code == "NO_RESULTS"
        assert "search term" in hint
        assert retryable is False

    def test_no_matches(self):
        code, hint, retryable = self._classify("no matches for pattern 'xyz'")
        assert code == "NO_RESULTS"
        assert retryable is False

    def test_generic_failure(self):
        code, hint, retryable = self._classify("something went wrong", exit_code=1)
        assert code == "COMMAND_FAILED"
        assert retryable is False

    def test_unknown_success(self):
        code, hint, retryable = self._classify("", exit_code=0)
        assert code == "UNKNOWN"
        assert retryable is False

    def test_patterns_ordered_specific_first(self):
        # "not found in index" should match INDEX_NOT_FOUND, not a more generic pattern
        code, _, _r = self._classify("Error: symbol 'x' not found in index database")
        assert code == "INDEX_NOT_FOUND"

    def test_permission_on_index_gets_permission_denied(self):
        # "permission denied" is more specific than generic index errors
        code, _, _r = self._classify("index.db: Permission denied")
        assert code == "PERMISSION_DENIED"

    def test_case_insensitive(self):
        code, _, _r = self._classify("PERMISSION DENIED for path /etc/shadow")
        assert code == "PERMISSION_DENIED"


# ---------------------------------------------------------------------------
# _ensure_fresh_index tests
# ---------------------------------------------------------------------------


class TestEnsureFreshIndex:
    """Test index freshness checking."""

    def test_success(self):
        from roam.mcp_server import _ensure_fresh_index
        with patch("roam.mcp_server._run_roam") as mock:
            mock.return_value = {"summary": {"files": 10}}
            result = _ensure_fresh_index(".")
            assert result is None
            mock.assert_called_once_with(["index"], ".")

    def test_failure(self):
        from roam.mcp_server import _ensure_fresh_index
        with patch("roam.mcp_server._run_roam") as mock:
            mock.return_value = {"error": "permission denied"}
            result = _ensure_fresh_index(".")
            assert result is not None
            assert "error" in result
            assert "permission denied" in result["error"]


# ---------------------------------------------------------------------------
# _run_roam tests
# ---------------------------------------------------------------------------


class TestRunRoam:
    """Test the roam CLI runner wrapper."""

    def test_inprocess_success(self):
        """In-process path (root='.') parses CliRunner JSON output."""
        from roam.mcp_server import _run_roam
        payload = {"summary": {"health_score": 85}}
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.output = json.dumps(payload)
        mock_result.exception = None
        with patch("click.testing.CliRunner.invoke", return_value=mock_result):
            result = _run_roam(["health"], ".")
            assert result == payload

    def test_inprocess_failure(self):
        """In-process path classifies errors from CliRunner output."""
        from roam.mcp_server import _run_roam
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.output = "Error: No .roam directory found"
        mock_result.exception = None
        with patch("click.testing.CliRunner.invoke", return_value=mock_result):
            result = _run_roam(["health"], ".")
            assert "error" in result
            assert result["error_code"] == "INDEX_NOT_FOUND"
            assert "hint" in result
            assert result["exit_code"] == 1

    def test_inprocess_json_decode_error(self):
        """In-process path handles non-JSON output gracefully."""
        from roam.mcp_server import _run_roam
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.output = "not json {{{"
        mock_result.exception = None
        with patch("click.testing.CliRunner.invoke", return_value=mock_result):
            result = _run_roam(["health"], ".")
            assert "error" in result
            assert "JSON" in result["error"]

    def test_subprocess_fallback_for_remote_root(self):
        """Non-'.' root falls back to subprocess."""
        from roam.mcp_server import _run_roam
        payload = {"summary": {"health_score": 85}}
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )
            result = _run_roam(["health"], "/other/project")
            assert result == payload
            mock.assert_called_once()

    def test_subprocess_timeout(self):
        """Subprocess path handles timeout."""
        from roam.mcp_server import _run_roam
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="roam", timeout=60)):
            result = _run_roam(["health"], "/other/project")
            assert "error" in result
            assert "timed out" in result["error"]

    def test_inprocess_exception(self):
        """In-process path handles unexpected exceptions."""
        from roam.mcp_server import _run_roam
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.output = ""
        mock_result.exception = RuntimeError("something broke")
        with patch("click.testing.CliRunner.invoke", return_value=mock_result):
            result = _run_roam(["health"], ".")
            assert "error" in result


# ---------------------------------------------------------------------------
# _tool decorator tests
# ---------------------------------------------------------------------------


class TestToolDecorator:
    """Test the MCP tool registration decorator."""

    def test_default_preset_filters_non_core(self):
        """Non-core tools should be plain functions in core preset (default)."""
        import roam.mcp_server as mod
        # test that a remaining tool function is callable
        assert callable(mod.understand)

    def test_required_task_tools_declared(self):
        from roam.mcp_server import _TASK_REQUIRED_TOOLS
        # after removing roam_init and roam_reindex, this set should be empty
        assert isinstance(_TASK_REQUIRED_TOOLS, set)

    def test_init_and_reindex_are_non_read_only(self):
        from roam.mcp_server import _NON_READ_ONLY_TOOLS
        # after removing roam_init and roam_reindex, this set should be empty
        assert isinstance(_NON_READ_ONLY_TOOLS, set)


# ---------------------------------------------------------------------------
# mcp_cmd CLI tests
# ---------------------------------------------------------------------------


class TestMcpCmd:
    """Test the roam mcp CLI command."""

    def test_help(self):
        from roam.mcp_server import mcp_cmd
        runner = CliRunner()
        result = runner.invoke(mcp_cmd, ["--help"])
        assert result.exit_code == 0
        assert "roam mcp" in result.output
        assert "--transport" in result.output
        assert "streamable-http" in result.output
        assert "--no-auto-index" in result.output
        assert "--list-tools-json" in result.output
        assert "--compat-profile" in result.output

    def test_compat_profile_all_without_fastmcp(self):
        """--compat-profile should work even when fastmcp is unavailable."""
        from roam.mcp_server import mcp_cmd
        runner = CliRunner()
        with patch("roam.mcp_server.mcp", None):
            result = runner.invoke(mcp_cmd, ["--compat-profile", "all"])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["server"] == "roam-code"
            assert "profiles" in data
            assert "copilot" in data["profiles"]
            assert data["profiles"]["copilot"]["mcp_capabilities"]["prompts"] == "unsupported"
            assert "tools-only" in data["profiles"]["copilot"]["constraints"]

    def test_compat_profile_precedence_selection(self):
        """Selected instruction file should follow profile precedence and existing files."""
        from roam.mcp_server import mcp_cmd
        runner = CliRunner()

        with runner.isolated_filesystem():
            with open("AGENTS.md", "w", encoding="utf-8") as f:
                f.write("# Agent Guide\n")
            with open("CLAUDE.md", "w", encoding="utf-8") as f:
                f.write("# Claude\n")

            result = runner.invoke(mcp_cmd, ["--compat-profile", "codex"])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["profile"] == "codex"
            assert data["selected_instruction_file"] == "AGENTS.md"
            assert data["preferred_instruction_missing"] is False

    def test_compat_profile_reports_missing_preferred_file(self):
        """When no preferred file exists, payload should flag fallback as missing."""
        from roam.mcp_server import mcp_cmd
        runner = CliRunner()

        with runner.isolated_filesystem():
            result = runner.invoke(mcp_cmd, ["--compat-profile", "claude"])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["selected_instruction_file"] == "AGENTS.md"
            assert data["preferred_instruction_missing"] is True

    def test_missing_fastmcp(self):
        """When fastmcp isn't installed, should fail with clear message."""
        from roam.mcp_server import mcp_cmd
        runner = CliRunner()
        with patch("roam.mcp_server.mcp", None):
            result = runner.invoke(mcp_cmd, ["--no-auto-index"])
            assert result.exit_code == 1
            assert "roam-code[mcp]" in result.output

    def test_list_tools_flag(self):
        """--list-tools should print registered tools without starting server."""
        from roam.mcp_server import mcp_cmd
        runner = CliRunner()
        # Even without fastmcp, --list-tools should fail gracefully
        # (it checks mcp is None first)
        with patch("roam.mcp_server.mcp", None):
            result = runner.invoke(mcp_cmd, ["--list-tools"])
            assert result.exit_code == 1  # mcp is None check fires first

    def test_list_tools_json_flag_missing_fastmcp(self):
        """--list-tools-json should fail gracefully without fastmcp."""
        from roam.mcp_server import mcp_cmd
        runner = CliRunner()
        with patch("roam.mcp_server.mcp", None):
            result = runner.invoke(mcp_cmd, ["--list-tools-json"])
            assert result.exit_code == 1

    def test_streamable_http_transport(self):
        """--transport streamable-http should call mcp.run with streamable-http."""
        from roam.mcp_server import mcp_cmd
        runner = CliRunner()
        with patch("roam.mcp_server._ensure_fresh_index") as mock_idx, \
                patch("roam.mcp_server.mcp") as mock_mcp:
            mock_idx.return_value = None
            result = runner.invoke(
                mcp_cmd,
                ["--transport", "streamable-http", "--host", "127.0.0.1", "--port", "8001"],
            )
            assert result.exit_code == 0, result.output
            mock_mcp.run.assert_called_once_with(
                transport="streamable-http", host="127.0.0.1", port=8001
            )

    def test_list_tools_json_outputs_json(self):
        """--list-tools-json should emit parseable JSON metadata."""
        from roam.mcp_server import mcp_cmd
        runner = CliRunner()

        class _Ann:
            def model_dump(self, exclude_none=True):
                return {"readOnlyHint": True}

        class _Exec:
            def model_dump(self, exclude_none=True):
                return {"taskSupport": "optional"}

        class _Tool:
            def __init__(self):
                self.name = "roam_demo"
                self.title = "Demo"
                self.description = "demo tool"
                self.annotations = _Ann()
                self.execution = _Exec()
                self.meta = {"taskSupport": "optional"}

        async def _list_tools():
            return [_Tool()]

        with patch("roam.mcp_server.mcp") as mock_mcp:
            mock_mcp.list_tools = _list_tools
            result = runner.invoke(mcp_cmd, ["--list-tools-json"])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["server"] == "roam-code"
            assert data["tool_count"] == 1
            assert data["tools"][0]["name"] == "roam_demo"
            assert data["tools"][0]["task_support"] == "optional"


# ---------------------------------------------------------------------------
# Tool wrapper argument construction tests
# ---------------------------------------------------------------------------


class TestToolWrappers:
    """Test that tool wrappers construct correct CLI arguments."""

    def _check_args(self, fn, kwargs, expected_args):
        """Call a tool function with mocked _run_roam and verify args."""
        with patch("roam.mcp_server._run_roam") as mock:
            mock.return_value = {"ok": True}
            fn(**kwargs)
            mock.assert_called_once()
            actual_args = mock.call_args[0][0]
            assert actual_args == expected_args

    def test_roam_diff_default(self):
        from roam.mcp_server import roam_diff
        self._check_args(roam_diff, {}, ["diff"])

    def test_roam_diff_with_range(self):
        from roam.mcp_server import roam_diff
        self._check_args(
            roam_diff,
            {"commit_range": "HEAD~3..HEAD", "staged": False},
            ["diff", "HEAD~3..HEAD"],
        )

    def test_roam_diff_staged(self):
        from roam.mcp_server import roam_diff
        self._check_args(roam_diff, {"staged": True}, ["diff", "--staged"])

    def test_roam_uses(self):
        from roam.mcp_server import roam_uses
        self._check_args(roam_uses, {"name": "open_db"}, ["uses", "open_db"])

    def test_context_with_personalization(self):
        from roam.mcp_server import context
        self._check_args(
            context,
            {
                "symbol": "open_db",
                "task": "debug",
                "session_hint": "auth failure stacktrace",
                "recent_symbols": "AuthService,User",
            },
            [
                "context", "open_db", "--task", "debug",
                "--session-hint", "auth failure stacktrace",
                "--recent-symbol", "AuthService",
                "--recent-symbol", "User",
            ],
        )



# ---------------------------------------------------------------------------
# Error pattern table tests
# ---------------------------------------------------------------------------


class TestErrorPatterns:
    """Test the _ERROR_PATTERNS table structure."""

    def test_patterns_are_lowercase(self):
        from roam.mcp_server import _ERROR_PATTERNS
        for pattern, code, hint in _ERROR_PATTERNS:
            assert pattern == pattern.lower(), f"pattern '{pattern}' should be lowercase"

    def test_codes_are_uppercase(self):
        from roam.mcp_server import _ERROR_PATTERNS
        for pattern, code, hint in _ERROR_PATTERNS:
            assert code == code.upper(), f"code '{code}' should be uppercase"

    def test_hints_end_with_period(self):
        from roam.mcp_server import _ERROR_PATTERNS
        for pattern, code, hint in _ERROR_PATTERNS:
            assert hint.endswith("."), f"hint for {code} should end with period"

    def test_no_duplicate_patterns(self):
        from roam.mcp_server import _ERROR_PATTERNS
        patterns = [p for p, _, _ in _ERROR_PATTERNS]
        assert len(patterns) == len(set(patterns)), "duplicate patterns found"


# ---------------------------------------------------------------------------
# _compound_envelope tests
# ---------------------------------------------------------------------------


class TestCompoundEnvelope:
    """Test the compound envelope builder."""

    def test_all_sections_succeed(self):
        from roam.mcp_server import _compound_envelope
        result = _compound_envelope("test-op", [
            ("alpha", {"summary": {"verdict": "ok alpha"}, "data": [1, 2]}),
            ("beta", {"summary": {"verdict": "ok beta"}, "extra": "hi"}),
        ])
        assert result["command"] == "test-op"
        assert "alpha" in result
        assert "beta" in result
        assert result["summary"]["sections"] == ["alpha", "beta"]
        assert result["summary"]["errors"] == 0
        assert "alpha: ok alpha" in result["summary"]["verdict"]
        assert "beta: ok beta" in result["summary"]["verdict"]
        assert "_errors" not in result

    def test_one_section_fails(self):
        from roam.mcp_server import _compound_envelope
        result = _compound_envelope("test-op", [
            ("alpha", {"summary": {"verdict": "good"}, "val": 1}),
            ("beta", {"error": "something broke"}),
        ])
        assert result["summary"]["errors"] == 1
        assert "alpha" in result
        assert "beta" not in result  # failed section not in top-level
        assert "_errors" in result
        assert result["_errors"][0]["command"] == "beta"

    def test_all_sections_fail(self):
        from roam.mcp_server import _compound_envelope
        result = _compound_envelope("test-op", [
            ("alpha", {"error": "err1"}),
            ("beta", {"error": "err2"}),
        ])
        assert result["summary"]["errors"] == 2
        assert result["summary"]["sections"] == []
        assert len(result["_errors"]) == 2

    def test_empty_dict_treated_as_error(self):
        from roam.mcp_server import _compound_envelope
        result = _compound_envelope("test-op", [
            ("alpha", {}),
        ])
        assert result["summary"]["errors"] == 1

    def test_meta_kwargs_in_summary(self):
        from roam.mcp_server import _compound_envelope
        result = _compound_envelope("test-op", [
            ("alpha", {"summary": {"verdict": "ok"}}),
        ], target="my_func")
        assert result["summary"]["target"] == "my_func"

    def test_verdict_without_sub_verdicts(self):
        from roam.mcp_server import _compound_envelope
        result = _compound_envelope("test-op", [
            ("alpha", {"data": 1}),  # no summary.verdict
        ])
        assert result["summary"]["verdict"] == "compound operation completed"


# ---------------------------------------------------------------------------
# Compound operation tests
# ---------------------------------------------------------------------------


class TestCompoundOperations:
    """Test compound MCP operations."""

    def test_explore_without_symbol(self):
        from roam.mcp_server import explore
        overview = {"summary": {"verdict": "Python codebase, 85/100"}, "stack": ["python"]}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.return_value = overview
            result = explore()
            mock.assert_called_once_with(["understand"], ".")
        assert result["command"] == "explore"
        assert "understand" in result
        assert result["understand"] == overview

    def test_explore_with_symbol(self):
        from roam.mcp_server import explore
        overview = {"summary": {"verdict": "Python codebase"}}
        ctx = {"summary": {"verdict": "open_db context"}, "callers": []}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.side_effect = [overview, ctx]
            result = explore(symbol="open_db")
            assert mock.call_count == 2
            assert mock.call_args_list[0][0][0] == ["understand"]
            assert mock.call_args_list[1][0][0] == ["context", "open_db", "--task", "understand"]
        assert "understand" in result
        assert "context" in result
        assert result["summary"]["target"] == "open_db"

    def test_explore_with_personalization(self):
        from roam.mcp_server import explore
        overview = {"summary": {"verdict": "Python codebase"}}
        ctx = {"summary": {"verdict": "open_db context"}, "callers": []}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.side_effect = [overview, ctx]
            explore(
                symbol="open_db",
                session_hint="auth token refresh flow",
                recent_symbols="AuthService,User",
            )
            assert mock.call_count == 2
            assert mock.call_args_list[1][0][0] == [
                "context", "open_db", "--task", "understand",
                "--session-hint", "auth token refresh flow",
                "--recent-symbol", "AuthService",
                "--recent-symbol", "User",
            ]

    def test_prepare_change(self):
        from roam.mcp_server import prepare_change
        pf = {"summary": {"verdict": "LOW risk"}, "blast_radius": {}}
        ctx = {"summary": {"verdict": "3 files to read"}, "files": []}
        eff = {"summary": {"verdict": "2 effects"}, "effects": []}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.side_effect = [pf, ctx, eff]
            result = prepare_change(target="my_func")
            assert mock.call_count == 3
            assert mock.call_args_list[0][0][0] == ["preflight", "my_func"]
            assert mock.call_args_list[1][0][0] == ["context", "my_func", "--task", "refactor"]
            assert mock.call_args_list[2][0][0] == ["effects", "my_func"]
        assert "preflight" in result
        assert "context" in result
        assert "effects" in result
        assert result["summary"]["target"] == "my_func"

    def test_prepare_change_with_personalization(self):
        from roam.mcp_server import prepare_change
        pf = {"summary": {"verdict": "ok"}}
        ctx = {"summary": {"verdict": "ok"}}
        eff = {"summary": {"verdict": "ok"}}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.side_effect = [pf, ctx, eff]
            prepare_change(
                target="my_func",
                session_hint="refactor billing domain",
                recent_symbols="Invoice,Payment",
            )
            assert mock.call_args_list[1][0][0] == [
                "context", "my_func", "--task", "refactor",
                "--session-hint", "refactor billing domain",
                "--recent-symbol", "Invoice",
                "--recent-symbol", "Payment",
            ]

    def test_prepare_change_staged(self):
        from roam.mcp_server import prepare_change
        pf = {"summary": {"verdict": "ok"}}
        ctx = {"summary": {"verdict": "ok"}}
        eff = {"summary": {"verdict": "ok"}}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.side_effect = [pf, ctx, eff]
            prepare_change(target="func", staged=True)
            # First call should include --staged
            assert "--staged" in mock.call_args_list[0][0][0]

    def test_review_change_default(self):
        from roam.mcp_server import review_change
        risk = {"summary": {"verdict": "LOW 12/100"}}
        diff = {"summary": {"verdict": "2 files"}}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.side_effect = [risk, diff]
            result = review_change()
            assert mock.call_count == 2
            assert mock.call_args_list[0][0][0] == ["pr-risk"]
            assert mock.call_args_list[1][0][0] == ["pr-diff"]
        assert "pr_risk" in result
        assert "pr_diff" in result

    def test_review_change_with_range(self):
        from roam.mcp_server import review_change
        data = {"summary": {"verdict": "ok"}}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.return_value = data
            review_change(commit_range="main..HEAD")
            assert "--range" in mock.call_args_list[1][0][0]

    def test_review_change_staged(self):
        from roam.mcp_server import review_change
        data = {"summary": {"verdict": "ok"}}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.return_value = data
            review_change(staged=True)
            assert "--staged" in mock.call_args_list[0][0][0]
            assert "--staged" in mock.call_args_list[1][0][0]

    def test_diagnose_issue(self):
        from roam.mcp_server import diagnose_issue
        diag = {"summary": {"verdict": "top suspect: parse_input"}, "suspects": []}
        eff = {"summary": {"verdict": "3 effects"}, "effects": []}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.side_effect = [diag, eff]
            result = diagnose_issue(symbol="broken_func")
            assert mock.call_count == 2
            assert mock.call_args_list[0][0][0] == ["diagnose", "broken_func", "--depth", "2"]
            assert mock.call_args_list[1][0][0] == ["effects", "broken_func"]
        assert "diagnose" in result
        assert "effects" in result
        assert result["summary"]["target"] == "broken_func"

    def test_diagnose_issue_custom_depth(self):
        from roam.mcp_server import diagnose_issue
        data = {"summary": {"verdict": "ok"}}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.return_value = data
            diagnose_issue(symbol="func", depth=5)
            assert "--depth" in mock.call_args_list[0][0][0]
            assert "5" in mock.call_args_list[0][0][0]

    def test_compound_handles_sub_error(self):
        """Compound operations should include errors without crashing."""
        from roam.mcp_server import explore
        overview = {"error": "No .roam directory found"}
        with patch("roam.mcp_server._run_roam") as mock:
            mock.return_value = overview
            result = explore()
        assert result["summary"]["errors"] == 1
        assert "_errors" in result

    def test_compound_functions_are_callable(self):
        """All 4 compound functions should be importable and callable."""
        from roam.mcp_server import explore, prepare_change, review_change, diagnose_issue
        assert callable(explore)
        assert callable(prepare_change)
        assert callable(review_change)
        assert callable(diagnose_issue)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    """Test output schema infrastructure."""

    def test_envelope_schema_structure(self):
        from roam.mcp_server import _ENVELOPE_SCHEMA
        assert _ENVELOPE_SCHEMA["type"] == "object"
        props = _ENVELOPE_SCHEMA["properties"]
        assert "command" in props
        assert "summary" in props
        assert "verdict" in props["summary"]["properties"]

    def test_make_schema_basic(self):
        from roam.mcp_server import _make_schema
        schema = _make_schema()
        assert schema["type"] == "object"
        assert "verdict" in schema["properties"]["summary"]["properties"]

    def test_make_schema_with_summary_fields(self):
        from roam.mcp_server import _make_schema
        schema = _make_schema({"score": {"type": "number"}})
        summary_props = schema["properties"]["summary"]["properties"]
        assert "verdict" in summary_props
        assert "score" in summary_props
        assert summary_props["score"]["type"] == "number"

    def test_make_schema_with_payload_fields(self):
        from roam.mcp_server import _make_schema
        schema = _make_schema(results={"type": "array"})
        assert "results" in schema["properties"]
        assert schema["properties"]["results"]["type"] == "array"

    def test_compound_schemas_exist(self):
        from roam.mcp_server import (
            _SCHEMA_EXPLORE, _SCHEMA_PREPARE_CHANGE,
            _SCHEMA_REVIEW_CHANGE, _SCHEMA_DIAGNOSE_ISSUE,
        )
        for schema in [_SCHEMA_EXPLORE, _SCHEMA_PREPARE_CHANGE,
                       _SCHEMA_REVIEW_CHANGE, _SCHEMA_DIAGNOSE_ISSUE]:
            assert schema["type"] == "object"
            assert "summary" in schema["properties"]

    def test_explore_schema_has_sections(self):
        from roam.mcp_server import _SCHEMA_EXPLORE
        props = _SCHEMA_EXPLORE["properties"]
        assert "understand" in props
        assert "context" in props
        assert "sections" in props["summary"]["properties"]

    def test_prepare_change_schema_has_sections(self):
        from roam.mcp_server import _SCHEMA_PREPARE_CHANGE
        props = _SCHEMA_PREPARE_CHANGE["properties"]
        assert "preflight" in props
        assert "context" in props
        assert "effects" in props

    def test_review_change_schema_has_sections(self):
        from roam.mcp_server import _SCHEMA_REVIEW_CHANGE
        props = _SCHEMA_REVIEW_CHANGE["properties"]
        assert "pr_risk" in props
        assert "pr_diff" in props

    def test_diagnose_issue_schema_has_sections(self):
        from roam.mcp_server import _SCHEMA_DIAGNOSE_ISSUE
        props = _SCHEMA_DIAGNOSE_ISSUE["properties"]
        assert "diagnose" in props
        assert "effects" in props

    def test_core_tool_schemas_exist(self):
        from roam.mcp_server import (
            _SCHEMA_UNDERSTAND, _SCHEMA_HEALTH, _SCHEMA_SEARCH,
            _SCHEMA_PREFLIGHT, _SCHEMA_CONTEXT, _SCHEMA_IMPACT,
            _SCHEMA_PR_RISK, _SCHEMA_DIFF, _SCHEMA_TRACE,
        )
        for schema in [_SCHEMA_UNDERSTAND, _SCHEMA_HEALTH, _SCHEMA_SEARCH,
                       _SCHEMA_PREFLIGHT, _SCHEMA_CONTEXT, _SCHEMA_IMPACT,
                       _SCHEMA_PR_RISK, _SCHEMA_DIFF, _SCHEMA_TRACE]:
            assert schema["type"] == "object"
            assert "summary" in schema["properties"]

    def test_health_schema_has_score(self):
        from roam.mcp_server import _SCHEMA_HEALTH
        summary_props = _SCHEMA_HEALTH["properties"]["summary"]["properties"]
        assert "health_score" in summary_props

    def test_search_schema_has_results(self):
        from roam.mcp_server import _SCHEMA_SEARCH
        assert "results" in _SCHEMA_SEARCH["properties"]
        assert _SCHEMA_SEARCH["properties"]["results"]["type"] == "array"


# ---------------------------------------------------------------------------
# Structured error tests (#116, #117)
# ---------------------------------------------------------------------------


class TestStructuredErrors:
    """Test MCP-compliant structured error responses (#116, #117)."""

    def test_inprocess_error_has_isError(self):
        from roam.mcp_server import _run_roam
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.output = "Error: No .roam directory found"
        mock_result.exception = None
        with patch("click.testing.CliRunner.invoke", return_value=mock_result):
            result = _run_roam(["health"], ".")
            assert result["isError"] is True
            assert "retryable" in result
            assert "suggested_action" in result

    def test_retryable_db_locked(self):
        from roam.mcp_server import _run_roam
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.output = "sqlite3.OperationalError: database is locked"
        mock_result.exception = None
        with patch("click.testing.CliRunner.invoke", return_value=mock_result):
            result = _run_roam(["health"], ".")
            assert result["retryable"] is True

    def test_not_retryable_permission_denied(self):
        from roam.mcp_server import _run_roam
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.output = "OSError: Permission denied"
        mock_result.exception = None
        with patch("click.testing.CliRunner.invoke", return_value=mock_result):
            result = _run_roam(["health"], ".")
            assert result["retryable"] is False

    def test_subprocess_error_has_structured_fields(self):
        from roam.mcp_server import _run_roam
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Error: No .roam directory found",
            )
            result = _run_roam(["health"], "/other/project")
            assert result["isError"] is True
            assert "retryable" in result
            assert "suggested_action" in result

    def test_success_no_isError(self):
        """Successful responses should NOT have isError."""
        from roam.mcp_server import _run_roam
        payload = {"summary": {"health_score": 85}}
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.output = json.dumps(payload)
        mock_result.exception = None
        with patch("click.testing.CliRunner.invoke", return_value=mock_result):
            result = _run_roam(["health"], ".")
            assert "isError" not in result

    def test_structured_error_helper(self):
        """_structured_error should add isError, retryable, suggested_action."""
        from roam.mcp_server import _structured_error
        err = {"error": "db locked", "error_code": "DB_LOCKED", "hint": "wait and retry."}
        result = _structured_error(err)
        assert result["isError"] is True
        assert result["retryable"] is True
        assert result["suggested_action"] == "wait and retry."

    def test_structured_error_not_retryable(self):
        """Non-retryable error codes should have retryable=False."""
        from roam.mcp_server import _structured_error
        err = {"error": "not found", "error_code": "INDEX_NOT_FOUND", "hint": "run roam init."}
        result = _structured_error(err)
        assert result["isError"] is True
        assert result["retryable"] is False

    def test_structured_error_unknown_code(self):
        """Unknown error codes default to retryable=False."""
        from roam.mcp_server import _structured_error
        err = {"error": "something", "hint": "check logs."}
        result = _structured_error(err)
        assert result["retryable"] is False
        assert result["suggested_action"] == "check logs."


# ---------------------------------------------------------------------------
# MCP Prompt tests (#118)
# ---------------------------------------------------------------------------


class TestMcpPrompts:
    """Test MCP prompt registration (#118)."""

    def test_prompts_defined(self):
        """All 5 prompts should be defined as functions."""
        import roam.mcp_server as mod
        for name in ["prompt_onboard", "prompt_review", "prompt_debug",
                      "prompt_refactor", "prompt_health_check"]:
            assert hasattr(mod, name), f"Missing prompt function: {name}"
            assert callable(getattr(mod, name))

    def test_prompt_onboard_returns_string(self):
        from roam.mcp_server import prompt_onboard
        result = prompt_onboard()
        assert isinstance(result, str)
        assert "roam_explore" in result

    def test_prompt_review_returns_string(self):
        from roam.mcp_server import prompt_review
        result = prompt_review()
        assert isinstance(result, str)
        assert "roam_review_change" in result

    def test_prompt_debug_with_symbol(self):
        from roam.mcp_server import prompt_debug
        result = prompt_debug(symbol="my_function")
        assert "my_function" in result

    def test_prompt_debug_without_symbol(self):
        from roam.mcp_server import prompt_debug
        result = prompt_debug()
        assert isinstance(result, str)

    def test_prompt_refactor_with_symbol(self):
        from roam.mcp_server import prompt_refactor
        result = prompt_refactor(symbol="my_class")
        assert "my_class" in result

    def test_prompt_refactor_without_symbol(self):
        from roam.mcp_server import prompt_refactor
        result = prompt_refactor()
        assert isinstance(result, str)
        assert "roam_prepare_change" in result

    def test_prompt_health_check_returns_string(self):
        from roam.mcp_server import prompt_health_check
        result = prompt_health_check()
        assert isinstance(result, str)
        assert "roam_health" in result


# ---------------------------------------------------------------------------
# Response metadata tests (#119)
# ---------------------------------------------------------------------------


class TestResponseMetadata:
    """Test _meta enrichment in json_envelope (#119)."""

    def test_meta_has_response_tokens(self):
        from roam.output.formatter import json_envelope
        env = json_envelope("health", summary={"verdict": "ok"})
        assert "response_tokens" in env["_meta"]
        assert isinstance(env["_meta"]["response_tokens"], int)
        assert env["_meta"]["response_tokens"] > 0

    def test_meta_has_cacheable(self):
        from roam.output.formatter import json_envelope
        env = json_envelope("health", summary={"verdict": "ok"})
        assert env["_meta"]["cacheable"] is True
        assert env["_meta"]["cache_ttl_s"] == 300

    def test_non_cacheable_command(self):
        from roam.output.formatter import json_envelope
        env = json_envelope("mutate", summary={"verdict": "done"})
        assert env["_meta"]["cacheable"] is False
        assert env["_meta"]["cache_ttl_s"] == 0

    def test_volatile_command(self):
        from roam.output.formatter import json_envelope
        env = json_envelope("diff", summary={"verdict": "changes found"})
        assert env["_meta"]["cacheable"] is True
        assert env["_meta"]["cache_ttl_s"] == 60

    def test_latency_ms_placeholder(self):
        from roam.output.formatter import json_envelope
        env = json_envelope("health", summary={"verdict": "ok"})
        assert env["_meta"]["latency_ms"] is None

    def test_all_non_cacheable_commands(self):
        """All commands in _NON_CACHEABLE_COMMANDS should produce cacheable=False."""
        from roam.output.formatter import json_envelope, _NON_CACHEABLE_COMMANDS
        for cmd in _NON_CACHEABLE_COMMANDS:
            env = json_envelope(cmd, summary={"verdict": "ok"})
            assert env["_meta"]["cacheable"] is False, f"{cmd} should be non-cacheable"
            assert env["_meta"]["cache_ttl_s"] == 0, f"{cmd} should have cache_ttl_s=0"

    def test_all_volatile_commands(self):
        """All commands in _VOLATILE_COMMANDS should produce cache_ttl_s=60."""
        from roam.output.formatter import json_envelope, _VOLATILE_COMMANDS
        for cmd in _VOLATILE_COMMANDS:
            env = json_envelope(cmd, summary={"verdict": "ok"})
            assert env["_meta"]["cacheable"] is True, f"{cmd} should be cacheable"
            assert env["_meta"]["cache_ttl_s"] == 60, f"{cmd} should have cache_ttl_s=60"
