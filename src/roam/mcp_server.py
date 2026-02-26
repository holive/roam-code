"""MCP (Model Context Protocol) server for roam-code.

Exposes roam codebase-comprehension commands as structured MCP tools
so that AI coding agents can query project structure, health, dependencies,
and change-risk through a standard tool interface.

Usage:
    roam mcp                    # stdio (for Claude Code, Cursor, etc.)
    roam mcp --transport sse    # SSE on localhost:8000
    roam mcp --transport streamable-http  # Streamable HTTP on localhost:8000
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import click
from click.testing import CliRunner as _CliRunner

try:
    from fastmcp import Context as _Context
    from fastmcp import FastMCP
except ImportError:
    _Context = None
    FastMCP = None

try:
    from mcp.types import ToolAnnotations as _ToolAnnotations
except ImportError:
    _ToolAnnotations = None

try:
    from fastmcp.server.tasks.config import TaskConfig as _TaskConfig
except Exception:
    _TaskConfig = None

# ---------------------------------------------------------------------------
# All tools are always exposed (no preset system needed with 23 tools).
# ---------------------------------------------------------------------------

_CORE_TOOLS: set[str] = set()  # empty = all tools exposed
_ACTIVE_TOOLS: set[str] = set()  # empty = all tools exposed


# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

if FastMCP is not None:
    mcp = FastMCP(
        "roam-code",
        instructions=(
            "Codebase intelligence for AI coding agents. "
            "Pre-indexes symbols, call graphs, dependencies, architecture, "
            "and git history into a local SQLite DB. "
            "One tool call replaces 5-10 Glob/Grep/Read calls. "
            "Most tools are read-only; side-effect tools are explicitly marked."
        ),
    )
else:
    mcp = None


_REGISTERED_TOOLS: list[str] = []

# Tools with side effects or non-idempotent behavior.
_NON_READ_ONLY_TOOLS: set[str] = set()
_DESTRUCTIVE_TOOLS: set[str] = set()
_NON_IDEMPOTENT_TOOLS: set[str] = set()

# Tools where task execution must be used (non-blocking by default).
_TASK_REQUIRED_TOOLS: set[str] = set()

# Long-running tools where task support is useful when FastMCP task extras exist.
_TASK_OPTIONAL_TOOLS: set[str] = set()


# ---------------------------------------------------------------------------
# Client compatibility matrix (conformance profile baseline)
# ---------------------------------------------------------------------------

_KNOWN_INSTRUCTION_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    ".cursorrules",
    ".cursor/rules/roam.mdc",
)

_CLIENT_COMPAT_PROFILES: dict[str, dict] = {
    "claude": {
        "display_name": "Claude Code",
        "instruction_precedence": ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "CODEX.md"],
        "mcp_capabilities": {
            "tools": "supported",
            "resources": "supported",
            "prompts": "supported",
        },
        "remote_auth": "oauth2.1-compatible",
        "constraints": [],
    },
    "codex": {
        "display_name": "OpenAI Codex",
        "instruction_precedence": ["AGENTS.md", "CODEX.md", "CLAUDE.md", "GEMINI.md"],
        "mcp_capabilities": {
            "tools": "supported",
            "resources": "unknown",
            "prompts": "unknown",
        },
        "remote_auth": "client-dependent",
        "constraints": [],
    },
    "gemini": {
        "display_name": "Gemini CLI",
        "instruction_precedence": ["GEMINI.md", "AGENTS.md", "CLAUDE.md", "CODEX.md"],
        "mcp_capabilities": {
            "tools": "supported",
            "resources": "unknown",
            "prompts": "unknown",
        },
        "remote_auth": "client-dependent",
        "constraints": ["config-schema-strictness"],
    },
    "copilot": {
        "display_name": "GitHub Copilot Coding Agent",
        "instruction_precedence": [".github/copilot-instructions.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md"],
        "mcp_capabilities": {
            "tools": "supported",
            "resources": "unsupported",
            "prompts": "unsupported",
        },
        "remote_auth": "limited",
        "constraints": ["tools-only"],
    },
    "vscode": {
        "display_name": "VS Code Agent Mode",
        "instruction_precedence": ["AGENTS.md", "CLAUDE.md", "GEMINI.md", "CODEX.md"],
        "mcp_capabilities": {
            "tools": "supported",
            "resources": "client-dependent",
            "prompts": "client-dependent",
        },
        "remote_auth": "client-dependent",
        "constraints": [],
    },
    "cursor": {
        "display_name": "Cursor",
        "instruction_precedence": [".cursor/rules/roam.mdc", ".cursorrules", "AGENTS.md", "CLAUDE.md"],
        "mcp_capabilities": {
            "tools": "supported",
            "resources": "unknown",
            "prompts": "unknown",
        },
        "remote_auth": "client-dependent",
        "constraints": [],
    },
}


def _detect_instruction_files(root: str = ".") -> list[str]:
    """Detect known agent instruction/config files in the project root."""
    base = Path(root)
    found: list[str] = []
    for rel in _KNOWN_INSTRUCTION_FILES:
        if (base / rel).exists():
            found.append(rel)
    return found


def _select_instruction_file(precedence: list[str], existing: list[str]) -> str:
    """Pick the highest-precedence existing instruction file, else AGENTS.md."""
    for rel in precedence:
        if rel in existing:
            return rel
    return "AGENTS.md"


def _compat_profile_payload(profile: str, root: str = ".") -> dict:
    """Build MCP client compatibility payload for one profile or all profiles."""
    existing = _detect_instruction_files(root)

    def _build(name: str, data: dict) -> dict:
        selected = _select_instruction_file(data["instruction_precedence"], existing)
        return {
            "id": name,
            "display_name": data["display_name"],
            "instruction_precedence": data["instruction_precedence"],
            "selected_instruction_file": selected,
            "preferred_instruction_missing": selected not in existing,
            "mcp_capabilities": data["mcp_capabilities"],
            "remote_auth": data["remote_auth"],
            "constraints": data["constraints"],
        }

    if profile == "all":
        profiles = {name: _build(name, data) for name, data in _CLIENT_COMPAT_PROFILES.items()}
        return {
            "server": "roam-code",
            "compat_version": "2026-02-22",
            "detected_instruction_files": existing,
            "profiles": profiles,
        }

    data = _CLIENT_COMPAT_PROFILES[profile]
    payload = _build(profile, data)
    payload.update({
        "server": "roam-code",
        "compat_version": "2026-02-22",
        "detected_instruction_files": existing,
        "profile": profile,
    })
    return payload


# ---------------------------------------------------------------------------
# Output schemas — JSON Schema dicts for MCP tool return types.
# All tools default to the envelope schema; compound/core tools override.
# ---------------------------------------------------------------------------

_ENVELOPE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "command": {"type": "string"},
        "summary": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "description": "One-line result summary"},
            },
        },
    },
}


def _make_schema(summary_fields: dict | None = None, **payload_fields) -> dict:
    """Build a JSON Schema extending the standard envelope with custom fields."""
    summary_props: dict = {
        "verdict": {"type": "string", "description": "One-line result summary"},
    }
    if summary_fields:
        summary_props.update(summary_fields)

    props: dict = {
        "command": {"type": "string"},
        "summary": {"type": "object", "properties": summary_props},
    }
    if payload_fields:
        props.update(payload_fields)

    return {"type": "object", "properties": props}


# -- Compound operation schemas ------------------------------------------------

_SCHEMA_EXPLORE = _make_schema(
    {"sections": {"type": "array", "items": {"type": "string"}}},
    understand={"type": "object", "description": "Full codebase briefing"},
    context={"type": "object", "description": "Symbol context (when symbol provided)"},
)

_SCHEMA_PREPARE_CHANGE = _make_schema(
    {"sections": {"type": "array"}, "target": {"type": "string"}},
    preflight={"type": "object", "description": "Safety check: blast radius, tests, fitness"},
    context={"type": "object", "description": "Files and line ranges to read"},
    effects={"type": "object", "description": "Side effects of the target symbol"},
)

_SCHEMA_REVIEW_CHANGE = _make_schema(
    {"sections": {"type": "array"}},
    pr_risk={"type": "object", "description": "Risk score and per-file breakdown"},
    pr_diff={"type": "object", "description": "Structural graph delta"},
)

_SCHEMA_DIAGNOSE_ISSUE = _make_schema(
    {"sections": {"type": "array"}, "target": {"type": "string"}},
    diagnose={"type": "object", "description": "Root cause suspects ranked by risk"},
    effects={"type": "object", "description": "Side effects of the symbol"},
)

# -- Core tool schemas ---------------------------------------------------------

_SCHEMA_UNDERSTAND = _make_schema(
    {"health_score": {"type": "number"}, "tech_stack": {"type": "array"}},
    architecture={"type": "object"},
    hotspots={"type": "array"},
)

_SCHEMA_HEALTH = _make_schema(
    {"health_score": {"type": "number"}, "total_files": {"type": "integer"},
     "total_symbols": {"type": "integer"}},
    issues={"type": "array"},
    bottlenecks={"type": "array"},
)

_SCHEMA_SEARCH = _make_schema(
    {"total_matches": {"type": "integer"}, "query": {"type": "string"}},
    results={
        "type": "array",
        "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "kind": {"type": "string"},
            "file_path": {"type": "string"}, "line_start": {"type": "integer"},
        }},
    },
)

_SCHEMA_PREFLIGHT = _make_schema(
    {"risk_level": {"type": "string"}, "target": {"type": "string"}},
    blast_radius={"type": "object"},
    affected_tests={"type": "array"},
    complexity={"type": "object"},
)

_SCHEMA_CONTEXT = _make_schema(
    {"target": {"type": "string"}},
    definition={"type": "object"},
    callers={"type": "array"},
    callees={"type": "array"},
    files_to_read={"type": "array"},
)

_SCHEMA_IMPACT = _make_schema(
    {"total_affected": {"type": "integer"}, "target": {"type": "string"}},
    affected_symbols={"type": "array"},
    affected_files={"type": "array"},
)

_SCHEMA_PR_RISK = _make_schema(
    {"risk_score": {"type": "number"}, "risk_level": {"type": "string"}},
    per_file={"type": "array"},
)

_SCHEMA_DIFF = _make_schema(
    {"changed_files": {"type": "integer"}},
    files={"type": "array"},
    affected_symbols={"type": "array"},
)

_SCHEMA_TRACE = _make_schema(
    {"source": {"type": "string"}, "target": {"type": "string"},
     "hop_count": {"type": "integer"}},
    path={"type": "array"},
)

_SCHEMA_BATCH_SEARCH = _make_schema(
    {"queries_executed": {"type": "integer"}, "total_matches": {"type": "integer"}},
    results={
        "type": "object",
        "description": "Map of query -> list of matching symbols",
        "additionalProperties": {
            "type": "array",
            "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "kind": {"type": "string"},
                "file_path": {"type": "string"}, "line_start": {"type": "integer"},
                "pagerank": {"type": "number"},
            }},
        },
    },
    errors={
        "type": "object",
        "description": "Map of query -> error message (only present if some queries failed)",
        "additionalProperties": {"type": "string"},
    },
)

_SCHEMA_BATCH_GET = _make_schema(
    {"symbols_resolved": {"type": "integer"}, "symbols_requested": {"type": "integer"}},
    results={
        "type": "object",
        "description": "Map of symbol name -> symbol details dict",
        "additionalProperties": {"type": "object"},
    },
    errors={
        "type": "object",
        "description": "Map of symbol name -> error message for unresolved symbols",
        "additionalProperties": {"type": "string"},
    },
)



def _tool_title(name: str) -> str:
    """Convert roam tool name to a human title."""
    short = name.removeprefix("roam_").replace("_", " ")
    return short.title()


def _tool_annotations(name: str) -> dict:
    """Build MCP tool annotations with capability hints."""
    read_only = name not in _NON_READ_ONLY_TOOLS
    annotations = {
        "title": _tool_title(name),
        "readOnlyHint": read_only,
        "destructiveHint": name in _DESTRUCTIVE_TOOLS,
        "idempotentHint": name not in _NON_IDEMPOTENT_TOOLS,
        "openWorldHint": False,
    }
    return annotations


def _tool(name: str, description: str = "", output_schema: dict | None = None):
    """Register an MCP tool. All tools are always exposed."""
    def decorator(fn):
        if mcp is None:
            return fn
        _REGISTERED_TOOLS.append(name)
        kwargs: dict = {"name": name, "title": _tool_title(name)}
        if description:
            kwargs["description"] = description
        schema = output_schema if output_schema is not None else _ENVELOPE_SCHEMA
        kwargs["output_schema"] = schema
        kwargs["annotations"] = _tool_annotations(name)

        task_mode: str | None = None
        if name in _TASK_REQUIRED_TOOLS:
            task_mode = "required"
        elif name in _TASK_OPTIONAL_TOOLS:
            task_mode = "optional"
        if task_mode:
            # Metadata fallback for clients even when FastMCP task extras are absent.
            kwargs["meta"] = {"taskSupport": task_mode}
            if _TaskConfig is not None:
                kwargs["task"] = _TaskConfig(mode=task_mode)

        # Register with compatibility fallbacks:
        # 1) Full feature set
        # 2) Drop task support when tasks extras aren't installed
        # 3) Legacy FastMCP without output_schema/annotations/title/meta/task
        attempts = [dict(kwargs)]
        if "task" in kwargs:
            no_task = dict(kwargs)
            no_task.pop("task", None)
            attempts.append(no_task)
        legacy = dict(kwargs)
        for key in ("output_schema", "annotations", "title", "meta", "task"):
            legacy.pop(key, None)
        attempts.append(legacy)

        last_error: Exception | None = None
        seen: set[tuple[str, ...]] = set()
        for attempt in attempts:
            signature = tuple(sorted(attempt.keys()))
            if signature in seen:
                continue
            seen.add(signature)
            try:
                return mcp.tool(**attempt)(fn)
            except (TypeError, ImportError) as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_ERROR_PATTERNS: list[tuple[str, str, str]] = [
    # (pattern, error_code, hint) — checked in order, first match wins.
    # More specific patterns MUST come before broader ones.
    ("no .roam",            "INDEX_NOT_FOUND",  "run `roam init` to create the codebase index."),
    ("not found in index",  "INDEX_NOT_FOUND",  "run `roam init` to create the codebase index."),
    ("index is stale",      "INDEX_STALE",      "run `roam index` to refresh."),
    ("out of date",         "INDEX_STALE",      "run `roam index` to refresh."),
    ("not a git repository","NOT_GIT_REPO",     "some commands require git history. run: git init."),
    ("database is locked",  "DB_LOCKED",        "another roam process is running. wait or delete .roam/index.lock."),
    ("permission denied",   "PERMISSION_DENIED","check file permissions."),
    ("cannot open index",   "INDEX_NOT_FOUND",  "run `roam init` to create the codebase index."),
    ("symbol not found",    "NO_RESULTS",       "try a different search term or check spelling."),
    ("no matches",          "NO_RESULTS",       "try a different search term or check spelling."),
    ("no results",          "NO_RESULTS",       "try a different search term or check spelling."),
]


_RETRYABLE_CODES = {"DB_LOCKED", "INDEX_STALE"}


def _classify_error(stderr: str, exit_code: int) -> tuple[str, str, bool]:
    """Classify error and return (error_code, hint, retryable).

    Checks standardized exit codes first (more reliable than text matching),
    then falls back to text pattern matching for legacy/subprocess output.
    The *retryable* flag indicates whether the agent should retry the call
    (True for DB_LOCKED, INDEX_STALE; False for everything else).
    """
    from roam.exit_codes import (
        EXIT_USAGE, EXIT_INDEX_MISSING, EXIT_INDEX_STALE,
        EXIT_GATE_FAILURE, EXIT_PARTIAL,
    )
    # Standardized exit code mapping (takes priority)
    _EXIT_CODE_MAP: dict[int, tuple[str, str]] = {
        EXIT_USAGE: ("USAGE_ERROR", "invalid arguments or flags. check --help."),
        EXIT_INDEX_MISSING: ("INDEX_NOT_FOUND", "run `roam init` to create the codebase index."),
        EXIT_INDEX_STALE: ("INDEX_STALE", "run `roam index` to refresh."),
        EXIT_GATE_FAILURE: ("GATE_FAILURE", "quality gate check failed."),
        EXIT_PARTIAL: ("PARTIAL_FAILURE", "command completed with warnings."),
    }
    if exit_code in _EXIT_CODE_MAP:
        code, hint = _EXIT_CODE_MAP[exit_code]
        return (code, hint, code in _RETRYABLE_CODES)

    # Fall back to text pattern matching
    s = stderr.lower()
    for pattern, code, hint in _ERROR_PATTERNS:
        if pattern in s:
            return (code, hint, code in _RETRYABLE_CODES)
    if exit_code != 0:
        return ("COMMAND_FAILED", "check arguments and try again.", False)
    return ("UNKNOWN", "check the error message for details.", False)


def _structured_error(error_dict: dict) -> dict:
    """Wrap error dict with MCP-compliant structured error fields (#116, #117)."""
    error_dict["isError"] = True
    code = error_dict.get("error_code", "UNKNOWN")
    error_dict["retryable"] = code in _RETRYABLE_CODES
    error_dict["suggested_action"] = error_dict.get("hint", "check the error message")
    return error_dict


def _ensure_fresh_index(root: str = ".") -> dict | None:
    """Run incremental index to ensure freshness. Returns None on success."""
    result = _run_roam(["index"], root)
    if "error" in result:
        return {"error": f"index update failed: {result['error']}"}
    return None


def _run_roam(args: list[str], root: str = ".") -> dict:
    """Run a roam CLI command with ``--json`` and return parsed output.

    Uses in-process Click invocation (fast, no subprocess overhead) when
    *root* is ``"."``.  Falls back to subprocess for non-local roots.
    """
    if root != ".":
        return _run_roam_subprocess(args, root)
    return _run_roam_inprocess(args)


def _run_roam_inprocess(args: list[str]) -> dict:
    """Run a roam CLI command in-process via Click CliRunner (no subprocess)."""
    from roam.cli import cli as _cli

    runner = _CliRunner()
    cmd_args = ["--json"] + args
    try:
        result = runner.invoke(_cli, cmd_args, catch_exceptions=True)
    except Exception as exc:
        return _structured_error({
            "error": str(exc),
            "error_code": "UNKNOWN",
            "hint": "an unexpected error occurred.",
        })

    output = result.output.strip() if result.output else ""

    # Gate failure (exit code 5) still produces valid JSON output — the
    # command completed but found issues.  Treat it like success for output
    # parsing, but annotate the result with gate_failure=True.
    from roam.exit_codes import EXIT_GATE_FAILURE
    _success_codes = {0, EXIT_GATE_FAILURE}

    # Successful JSON output — look for JSON object in output
    if result.exit_code in _success_codes and output:
        try:
            parsed = json.loads(output)
            if result.exit_code == EXIT_GATE_FAILURE:
                parsed["gate_failure"] = True
                parsed["exit_code"] = EXIT_GATE_FAILURE
            return parsed
        except json.JSONDecodeError as exc:
            return _structured_error({
                "error": f"Failed to parse JSON output: {exc}",
                "error_code": "COMMAND_FAILED",
                "hint": "command produced invalid JSON output.",
            })

    # Error path — classify and return structured error
    error_text = output
    if result.exception:
        error_text = error_text or str(result.exception)

    error_code, hint, _retryable = _classify_error(error_text, result.exit_code)
    return _structured_error({
        "error": error_text or "command failed",
        "error_code": error_code,
        "hint": hint,
        "exit_code": result.exit_code,
        "command": "roam --json " + " ".join(args),
    })


def _run_roam_subprocess(args: list[str], root: str = ".") -> dict:
    """Run a roam CLI command via subprocess (fallback for non-local roots)."""
    from roam.exit_codes import EXIT_GATE_FAILURE
    _success_codes = {0, EXIT_GATE_FAILURE}

    cmd = ["roam", "--json"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=root,
            timeout=60,
        )
        if result.returncode in _success_codes and result.stdout.strip():
            parsed = json.loads(result.stdout)
            if result.returncode == EXIT_GATE_FAILURE:
                parsed["gate_failure"] = True
                parsed["exit_code"] = EXIT_GATE_FAILURE
            return parsed
        stderr = result.stderr.strip()
        error_code, hint, _retryable = _classify_error(stderr, result.returncode)
        return _structured_error({
            "error": stderr or "command failed",
            "error_code": error_code,
            "hint": hint,
            "exit_code": result.returncode,
            "command": " ".join(cmd),
        })
    except subprocess.TimeoutExpired:
        return _structured_error({
            "error": "Command timed out after 60s",
            "error_code": "COMMAND_FAILED",
            "hint": "the command took too long. try a smaller scope or check system load.",
        })
    except json.JSONDecodeError as exc:
        return _structured_error({
            "error": f"Failed to parse JSON output: {exc}",
            "error_code": "COMMAND_FAILED",
            "hint": "command produced invalid JSON output.",
        })
    except Exception as exc:
        return _structured_error({
            "error": str(exc),
            "error_code": "UNKNOWN",
            "hint": "an unexpected error occurred.",
        })


async def _run_roam_async(args: list[str], root: str = ".") -> dict:
    """Run a roam CLI command in a worker thread from async tool handlers."""
    return await asyncio.to_thread(_run_roam, args, root)


async def _ctx_report_progress(
    ctx: _Context | None, progress: float, total: float | None = None, message: str | None = None,
) -> None:
    """Best-effort MCP progress reporting (safe on clients without support)."""
    if ctx is None or not hasattr(ctx, "report_progress"):
        return
    try:
        await ctx.report_progress(progress=progress, total=total, message=message)
    except Exception:
        pass


async def _ctx_info(ctx: _Context | None, message: str) -> None:
    """Best-effort MCP log message to the client."""
    if ctx is None or not hasattr(ctx, "info"):
        return
    try:
        await ctx.info(message)
    except Exception:
        pass


def _coerce_yes_no(value) -> bool | None:
    """Normalize elicitation payloads into True/False when possible."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {"y", "yes", "true", "1", "continue", "proceed", "confirm"}:
            return True
        if norm in {"n", "no", "false", "0", "cancel", "stop", "decline"}:
            return False
        return None
    if isinstance(value, list):
        for item in value:
            parsed = _coerce_yes_no(item)
            if parsed is not None:
                return parsed
        return None
    if isinstance(value, dict):
        for key in ("value", "confirm", "decision", "answer", "choice"):
            if key in value:
                parsed = _coerce_yes_no(value[key])
                if parsed is not None:
                    return parsed
        for item in value.values():
            parsed = _coerce_yes_no(item)
            if parsed is not None:
                return parsed
    return None




# ===================================================================
# Compound operations -- each replaces 2-4 individual tool calls
# ===================================================================


def _compound_envelope(
    command: str,
    sub_results: list[tuple[str, dict]],
    **meta,
) -> dict:
    """Build a compound operation response from multiple sub-command results."""
    errors: list[dict] = []
    sections: dict = {}

    for name, data in sub_results:
        if not data or "error" in data:
            err_msg = data.get("error", "empty result") if data else "empty result"
            errors.append({"command": name, "error": err_msg})
        else:
            sections[name] = data

    # Build compound verdict from sub-verdicts
    verdicts: list[str] = []
    for name, data in sub_results:
        if isinstance(data, dict):
            summary = data.get("summary", {})
            if isinstance(summary, dict) and "verdict" in summary:
                verdicts.append(f"{name}: {summary['verdict']}")

    result: dict = {
        "command": command,
        "summary": {
            "verdict": " | ".join(verdicts) if verdicts else "compound operation completed",
            "sections": list(sections.keys()),
            "errors": len(errors),
            **meta,
        },
    }
    result.update(sections)

    if errors:
        result["_errors"] = errors

    return result


def _apply_budget(data: dict, budget: int) -> dict:
    """Apply token budget truncation to a compound operation result.

    Delegates to :func:`budget_truncate_json` from the formatter module.
    """
    if budget <= 0:
        return data
    from roam.output.formatter import budget_truncate_json
    return budget_truncate_json(data, budget)


def _append_context_personalization_args(args: list[str], session_hint: str = "",
                                         recent_symbols: str = "") -> list[str]:
    """Append optional context personalization flags to a roam CLI arg list."""
    if session_hint:
        args.extend(["--session-hint", session_hint])
    if recent_symbols:
        for raw in str(recent_symbols).split(","):
            sym = raw.strip()
            if sym:
                args.extend(["--recent-symbol", sym])
    return args


@_tool(name="roam_explore",
       description="Codebase exploration bundle: understand overview + optional symbol deep-dive in one call.",
       output_schema=_SCHEMA_EXPLORE)
def explore(symbol: str = "", budget: int = 0, session_hint: str = "",
            recent_symbols: str = "", root: str = ".") -> dict:
    """Full codebase exploration in one call.

    WHEN TO USE: Call this FIRST when starting work on a new codebase.
    If you have a specific symbol in mind, pass it to also get focused
    context (callers, callees, files to read). Replaces calling
    ``understand`` + ``context`` separately — saves one round-trip.

    Parameters
    ----------
    symbol:
        Optional symbol to deep-dive into after the overview.
    budget:
        Max output tokens (0 = unlimited). Truncates intelligently.
    session_hint:
        Optional conversation hint used to personalize context ranking.
    recent_symbols:
        Comma-separated recently discussed symbols for rank biasing.

    Returns: codebase overview (tech stack, architecture, health) and
    optionally focused context for the given symbol.
    """
    budget_args = ["--budget", str(budget)] if budget else []
    overview = _run_roam(budget_args + ["understand"], root)

    if not symbol:
        result = _compound_envelope("explore", [("understand", overview)])
        return _apply_budget(result, budget)

    ctx_args = budget_args + ["context", symbol, "--task", "understand"]
    _append_context_personalization_args(
        ctx_args,
        session_hint=session_hint,
        recent_symbols=recent_symbols,
    )
    ctx = _run_roam(ctx_args, root)
    result = _compound_envelope("explore", [
        ("understand", overview),
        ("context", ctx),
    ], target=symbol)
    return _apply_budget(result, budget)


@_tool(name="roam_prepare_change",
       description="Pre-change bundle: preflight + context + effects in one call. Call BEFORE modifying code.",
       output_schema=_SCHEMA_PREPARE_CHANGE)
def prepare_change(target: str, staged: bool = False, budget: int = 0,
                   session_hint: str = "", recent_symbols: str = "",
                   root: str = ".") -> dict:
    """Everything needed before modifying code, in one call.

    WHEN TO USE: Call this BEFORE making any non-trivial code change.
    Bundles safety check (blast radius, tests, fitness), context (files
    and line ranges to read), and side effects into a single response.
    Replaces calling ``preflight`` + ``context`` + ``effects`` separately
    — saves two round-trips.

    Parameters
    ----------
    target:
        Symbol name or file path to prepare for changing.
    staged:
        If True, check staged (git add-ed) changes instead.
    budget:
        Max output tokens (0 = unlimited). Truncates intelligently.
    session_hint:
        Optional conversation hint used to personalize context ranking.
    recent_symbols:
        Comma-separated recently discussed symbols for rank biasing.

    Returns: preflight safety data, context files to read, and side
    effects of the target. Each section includes its own verdict.
    """
    budget_args = ["--budget", str(budget)] if budget else []
    pf_args = budget_args + ["preflight"]
    if target:
        pf_args.append(target)
    if staged:
        pf_args.append("--staged")

    preflight_data = _run_roam(pf_args, root)

    ctx_data: dict = {}
    effects_data: dict = {}
    if target:
        ctx_args = budget_args + ["context", target, "--task", "refactor"]
        _append_context_personalization_args(
            ctx_args,
            session_hint=session_hint,
            recent_symbols=recent_symbols,
        )
        ctx_data = _run_roam(ctx_args, root)
        effects_data = _run_roam(budget_args + ["effects", target], root)

    result = _compound_envelope("prepare-change", [
        ("preflight", preflight_data),
        ("context", ctx_data),
        ("effects", effects_data),
    ], target=target)
    return _apply_budget(result, budget)


@_tool(name="roam_review_change",
       description="Change review bundle: pr-risk + structural diff in one call.",
       output_schema=_SCHEMA_REVIEW_CHANGE)
def review_change(staged: bool = False, commit_range: str = "", budget: int = 0, root: str = ".") -> dict:
    """Review pending changes in one call.

    WHEN TO USE: Call this before committing or creating a PR.
    Bundles risk assessment and structural graph delta into a single
    response. Replaces calling ``pr_risk`` + ``pr_diff`` separately
    -- saves one round-trip.

    Parameters
    ----------
    staged:
        If True, analyze staged changes only.
    commit_range:
        Git range like ``main..HEAD`` for branch comparison.
    budget:
        Max output tokens (0 = unlimited). Truncates intelligently.

    Returns: risk score and structural delta.
    Each section includes its own verdict.
    """
    budget_args = ["--budget", str(budget)] if budget else []
    risk_args = budget_args + ["pr-risk"]
    diff_args = budget_args + ["pr-diff"]

    if staged:
        risk_args.append("--staged")
        diff_args.append("--staged")
    if commit_range:
        diff_args.extend(["--range", commit_range])

    risk_data = _run_roam(risk_args, root)
    diff_data = _run_roam(diff_args, root)

    result = _compound_envelope("review-change", [
        ("pr_risk", risk_data),
        ("pr_diff", diff_data),
    ])
    return _apply_budget(result, budget)


@_tool(name="roam_diagnose",
       description="Debug bundle: root cause suspects + side effects in one call.",
       output_schema=_SCHEMA_DIAGNOSE_ISSUE)
def diagnose_issue(symbol: str, depth: int = 2, budget: int = 0, root: str = ".") -> dict:
    """debug a failing symbol in one call.

    WHEN TO USE: call this when debugging a bug or test failure.
    bundles root-cause analysis (upstream/downstream suspects ranked
    by composite risk) with side-effect analysis into one response.
    replaces calling diagnose + effects separately — saves one round-trip.

    Parameters
    ----------
    symbol:
        the symbol suspected of being involved in the bug.
    depth:
        how many hops upstream/downstream to analyze (default 2).
    budget:
        max output tokens (0 = unlimited). truncates intelligently.

    Returns: root cause suspects ranked by risk and side effects
    of the target symbol.
    """
    budget_args = ["--budget", str(budget)] if budget else []
    diag_data = _run_roam(budget_args + ["diagnose", symbol, "--depth", str(depth)], root)
    effects_data = _run_roam(budget_args + ["effects", symbol], root)

    result = _compound_envelope("diagnose-issue", [
        ("diagnose", diag_data),
        ("effects", effects_data),
    ], target=symbol)
    return _apply_budget(result, budget)


# ===================================================================
# Batch operations — 10x fewer MCP round trips for agents
# ===================================================================

_MAX_BATCH_QUERIES = 10
_MAX_BATCH_SYMBOLS = 50

# FTS5 search SQL used by batch_search — same as resolve.fts_suggestions
_BATCH_FTS_SQL = (
    "SELECT s.name, s.qualified_name, s.kind, f.path as file_path, "
    "s.line_start, COALESCE(gm.pagerank, 0) as pagerank "
    "FROM symbol_fts sf "
    "JOIN symbols s ON sf.rowid = s.id "
    "JOIN files f ON s.file_id = f.id "
    "LEFT JOIN graph_metrics gm ON s.id = gm.symbol_id "
    "WHERE symbol_fts MATCH ? "
    "ORDER BY rank "
    "LIMIT ?"
)

# Fallback LIKE SQL when FTS5 is unavailable or returns nothing
_BATCH_LIKE_SQL = (
    "SELECT s.name, s.qualified_name, s.kind, f.path as file_path, "
    "s.line_start, COALESCE(gm.pagerank, 0) as pagerank "
    "FROM symbols s "
    "JOIN files f ON s.file_id = f.id "
    "LEFT JOIN graph_metrics gm ON s.id = gm.symbol_id "
    "WHERE s.name LIKE ? COLLATE NOCASE "
    "ORDER BY COALESCE(gm.pagerank, 0) DESC, s.name "
    "LIMIT ?"
)


def _fts_query_for(q: str) -> str:
    """Build an FTS5 MATCH expression for a raw search query string."""
    tokens = q.replace("_", " ").replace(".", " ").split()
    if tokens:
        return " OR ".join(f'"{t}"*' for t in tokens)
    return f'"{q}"*'


def _batch_search_one(conn, q: str, limit: int) -> tuple[list, str | None]:
    """Search for one query in an open DB connection.

    Returns (rows, error_or_None).  Rows are plain dicts.
    Tries FTS5 first; falls back to LIKE match if FTS5 is unavailable.
    """
    rows: list = []
    try:
        fts_q = _fts_query_for(q)
        rows = conn.execute(_BATCH_FTS_SQL, (fts_q, limit)).fetchall()
    except Exception:
        rows = []

    if not rows:
        try:
            rows = conn.execute(_BATCH_LIKE_SQL, (f"%{q}%", limit)).fetchall()
        except Exception as exc:
            return [], str(exc)

    return [
        {
            "name": r["name"],
            "qualified_name": r["qualified_name"] or "",
            "kind": r["kind"],
            "file_path": r["file_path"],
            "line_start": r["line_start"],
            "pagerank": round(float(r["pagerank"] or 0), 4),
        }
        for r in rows
    ], None


def _batch_get_one(conn, sym: str) -> tuple[dict | None, str | None]:
    """Retrieve full details for a single symbol in an open DB connection.

    Returns (details_dict, error_or_None).
    Uses the same lookup chain as find_symbol(): qualified -> name -> fuzzy.
    """
    from roam.commands.resolve import find_symbol
    from roam.db.queries import CALLERS_OF, CALLEES_OF, METRICS_FOR_SYMBOL
    from roam.output.formatter import loc

    try:
        s = find_symbol(conn, sym)
    except Exception as exc:
        return None, str(exc)

    if s is None:
        return None, f"symbol not found: {sym!r}"

    try:
        metrics = conn.execute(METRICS_FOR_SYMBOL, (s["id"],)).fetchone()
        callers = conn.execute(CALLERS_OF, (s["id"],)).fetchall()
        callees = conn.execute(CALLEES_OF, (s["id"],)).fetchall()
    except Exception as exc:
        return None, f"db error fetching details for {sym!r}: {exc}"

    details: dict = {
        "name": s["qualified_name"] or s["name"],
        "kind": s["kind"],
        "signature": s["signature"] or "",
        "location": loc(s["file_path"], s["line_start"]),
        "docstring": s["docstring"] or "",
    }
    if metrics:
        details["pagerank"] = round(float(metrics["pagerank"] or 0), 4)
        details["in_degree"] = metrics["in_degree"]
        details["out_degree"] = metrics["out_degree"]

    details["callers"] = [
        {
            "name": c["name"],
            "kind": c["kind"],
            "edge_kind": c["edge_kind"],
            "location": loc(c["file_path"], c["edge_line"]),
        }
        for c in callers
    ]
    details["callees"] = [
        {
            "name": c["name"],
            "kind": c["kind"],
            "edge_kind": c["edge_kind"],
            "location": loc(c["file_path"], c["edge_line"]),
        }
        for c in callees
    ]
    return details, None


@_tool(name="roam_batch_search",
       description="Search up to 10 patterns in one call. Replaces 10 sequential roam_search_symbol calls.",
       output_schema=_SCHEMA_BATCH_SEARCH)
def batch_search(queries: list, limit_per_query: int = 5, root: str = ".") -> dict:
    """Batch symbol search: run multiple name queries in one MCP call.

    WHEN TO USE: Use this instead of calling roam_search_symbol 3+ times
    in a row with different queries. Executes all queries over a single
    DB connection — dramatically fewer round trips for agents doing broad
    symbol discovery (e.g. finding all auth, user, and request symbols at once).

    Parameters
    ----------
    queries:
        List of name substrings to search for (up to 10). Each entry is
        treated the same as a single roam_search_symbol query.
    limit_per_query:
        Max results per query (default 5, max 50).
    root:
        Project root directory (default ".").

    Returns: per-query result lists plus aggregate match count.
    Partial failures are collected in ``errors``; remaining queries still run.
    """
    from roam.commands.resolve import ensure_index
    from roam.db.connection import open_db
    from roam.output.formatter import json_envelope, to_json

    ensure_index()

    queries_list: list[str] = [str(q) for q in (queries or [])][:_MAX_BATCH_QUERIES]
    limit = max(1, min(int(limit_per_query), 50))

    results: dict = {}
    errors: dict = {}

    if not queries_list:
        return {
            "command": "batch-search",
            "summary": {
                "verdict": "no queries provided",
                "queries_executed": 0,
                "total_matches": 0,
            },
            "results": {},
            "errors": {},
        }

    try:
        with open_db(readonly=True) as conn:
            for q in queries_list:
                rows, err = _batch_search_one(conn, q, limit)
                if err:
                    errors[q] = err
                else:
                    results[q] = rows
    except Exception as exc:
        # Index not available or other fatal DB error — return structured error
        return {
            "command": "batch-search",
            "summary": {
                "verdict": f"batch search failed: {exc}",
                "queries_executed": 0,
                "total_matches": 0,
            },
            "results": {},
            "errors": {"_fatal": str(exc)},
        }

    total_matches = sum(len(v) for v in results.values())
    verdict = (
        f"{total_matches} matches across {len(results)} queries"
        if results
        else "no matches found"
    )
    if errors:
        verdict += f", {len(errors)} queries failed"

    payload: dict = {
        "command": "batch-search",
        "summary": {
            "verdict": verdict,
            "queries_executed": len(queries_list),
            "total_matches": total_matches,
        },
        "results": results,
    }
    if errors:
        payload["errors"] = errors

    return payload


@_tool(name="roam_batch_get",
       description="Get details for up to 50 symbols in one call. Replaces 50 sequential roam_symbol calls.",
       output_schema=_SCHEMA_BATCH_GET)
def batch_get(symbols: list, root: str = ".") -> dict:
    """Batch symbol detail retrieval: fetch multiple symbol definitions in one MCP call.

    WHEN TO USE: Use this instead of calling a symbol lookup tool 3+ times.
    Common pattern: after roam_batch_search or roam_search_symbol returns
    several candidates, call this to get callers/callees/metrics for all of
    them at once instead of one tool call per symbol.

    Parameters
    ----------
    symbols:
        List of symbol names or qualified names to look up (up to 50).
        Accepts the same formats as roam_symbol: bare name, qualified name,
        or ``file.py:SymbolName`` syntax.
    root:
        Project root directory (default ".").

    Returns: per-symbol detail dicts with callers, callees, pagerank, and
    location. Unresolved symbols appear in ``errors``; resolved symbols
    appear in ``results``.
    """
    from roam.commands.resolve import ensure_index
    from roam.db.connection import open_db

    ensure_index()

    symbols_list: list[str] = [str(s) for s in (symbols or [])][:_MAX_BATCH_SYMBOLS]

    results: dict = {}
    errors: dict = {}

    if not symbols_list:
        return {
            "command": "batch-get",
            "summary": {
                "verdict": "no symbols provided",
                "symbols_requested": 0,
                "symbols_resolved": 0,
            },
            "results": {},
            "errors": {},
        }

    try:
        with open_db(readonly=True) as conn:
            for sym in symbols_list:
                details, err = _batch_get_one(conn, sym)
                if err or details is None:
                    errors[sym] = err or "not found"
                else:
                    results[sym] = details
    except Exception as exc:
        return {
            "command": "batch-get",
            "summary": {
                "verdict": f"batch get failed: {exc}",
                "symbols_requested": len(symbols_list),
                "symbols_resolved": 0,
            },
            "results": {},
            "errors": {"_fatal": str(exc)},
        }

    resolved = len(results)
    verdict = f"{resolved}/{len(symbols_list)} symbols resolved"
    if errors:
        verdict += f", {len(errors)} not found"

    payload: dict = {
        "command": "batch-get",
        "summary": {
            "verdict": verdict,
            "symbols_requested": len(symbols_list),
            "symbols_resolved": resolved,
        },
        "results": results,
    }
    if errors:
        payload["errors"] = errors

    return payload


# ===================================================================
# Tier 1 tools -- the most valuable for day-to-day AI agent work
# ===================================================================




@_tool(name="roam_understand",
       description="Full codebase briefing: stack, architecture, health, hotspots. Call FIRST in a new repo.",
       output_schema=_SCHEMA_UNDERSTAND)
def understand(root: str = ".") -> dict:
    """Get a full codebase briefing in a single call.

    WHEN TO USE: Call this FIRST when you start working with a new or
    unfamiliar repository. Do NOT use Glob/Grep/Read to explore the
    codebase manually -- this tool gives you everything in one shot.

    Returns: tech stack, architecture overview (layers, clusters, entry
    points, key abstractions), health score, hotspots, naming conventions,
    design patterns, and a suggested file reading order.

    Output is ~2,000-4,000 tokens of structured JSON. After calling this,
    use `search_symbol` or `context` to drill into specific areas.
    """
    return _run_roam(["understand"], root)


@_tool(name="roam_health",
       description="Codebase health score (0-100) with issue breakdown, cycles, bottlenecks.",
       output_schema=_SCHEMA_HEALTH)
def health(root: str = ".") -> dict:
    """Get the codebase health score (0-100) with issue breakdown.

    WHEN TO USE: Call this to assess overall code quality before deciding
    where to focus refactoring effort, or to check whether recent changes
    degraded health. Do NOT call this if you already called `understand`
    (which includes health data) or `preflight` (which includes it per-symbol).

    Returns: composite health score, cycle count, god-component count,
    bottleneck symbols, dead-export count, layer violations, per-file
    health scores, and tangle ratio.
    """
    return _run_roam(["health"], root)


@_tool(name="roam_preflight",
       description="Pre-change safety check: blast radius, tests, complexity, fitness. Call BEFORE modifying code.",
       output_schema=_SCHEMA_PREFLIGHT)
def preflight(target: str = "", staged: bool = False, root: str = ".") -> dict:
    """Pre-change safety check. Call this BEFORE modifying any symbol or file.

    WHEN TO USE: Always call this before making code changes. It replaces
    5-6 separate tool calls by combining blast radius, affected tests,
    complexity, coupling, convention checks, and fitness violations into
    one response. Do NOT call `context`, `impact`, `affected_tests`, or
    `complexity_report` separately if preflight covers your need.

    Parameters
    ----------
    target:
        Symbol name or file path to check. If empty, checks all
        currently changed (unstaged) files.
    staged:
        If True, check staged (git add-ed) changes instead.

    Returns: risk level, blast radius (affected symbols and files),
    test files to run, complexity metrics, coupling data, and any
    fitness rule violations.
    """
    args = ["preflight"]
    if target:
        args.append(target)
    if staged:
        args.append("--staged")
    return _run_roam(args, root)


@_tool(name="roam_search_symbol",
       description="Find symbols by name substring. Returns kind, file, line, PageRank importance.",
       output_schema=_SCHEMA_SEARCH)
def search_symbol(query: str, root: str = ".") -> dict:
    """Find symbols by name (case-insensitive substring match).

    WHEN TO USE: Call this when you know part of a symbol name and need
    the exact qualified name, file location, or kind. Use this before
    calling `context` or `impact` to get the correct symbol identifier.
    Do NOT use Grep to search for function definitions -- this is faster
    and returns structured data with PageRank importance.

    Parameters
    ----------
    query:
        Name substring to search for (e.g., "auth", "User", "handle_request").

    Returns: matching symbols with kind (function/class/method), file path,
    line number, signature, export status, and PageRank importance score.
    """
    return _run_roam(["search", query], root)


@_tool(name="roam_context",
       description="Minimal files + line ranges needed to work with a symbol.",
       output_schema=_SCHEMA_CONTEXT)
def context(symbol: str, task: str = "", session_hint: str = "",
            recent_symbols: str = "", root: str = ".") -> dict:
    """Get the minimal context needed to work with a specific symbol.

    WHEN TO USE: Call this when you need to understand or modify a
    specific function, class, or method. Returns the exact files and
    line ranges to read -- much more targeted than `understand`.
    For pre-change safety checks, prefer `preflight` instead (it
    includes context data plus blast radius and tests).

    Parameters
    ----------
    symbol:
        Qualified or short name of the symbol to inspect.
    task:
        Optional hint: "refactor", "debug", "extend", "review", or
        "understand". Tailors output (e.g., adds complexity details
        for refactor, test coverage for debug).
    session_hint:
        Optional conversation hint used to personalize files-to-read rank.
    recent_symbols:
        Comma-separated recently discussed symbols for rank biasing.

    Returns: symbol definition, direct callers and callees, file location
    with line ranges, related tests, graph metrics (PageRank, fan-in/out,
    betweenness), and complexity metrics.
    """
    args = ["context", symbol]
    if task:
        args.extend(["--task", task])
    _append_context_personalization_args(
        args,
        session_hint=session_hint,
        recent_symbols=recent_symbols,
    )
    return _run_roam(args, root)


@_tool(name="roam_trace",
       description="Shortest dependency path between two symbols with hop details.",
       output_schema=_SCHEMA_TRACE)
def trace(source: str, target: str, root: str = ".") -> dict:
    """Find the shortest dependency path between two symbols.

    WHEN TO USE: Call this when you need to understand HOW a change in
    one symbol could affect another. Shows each hop along the path with
    symbol names, edge types, and locations.

    Parameters
    ----------
    source:
        Starting symbol name.
    target:
        Destination symbol name.

    Returns: path hops (symbol name, kind, location, edge type), total
    hop count, coupling classification (strong/moderate/weak), and any
    hub nodes encountered.
    """
    return _run_roam(["trace", source, target], root)


@_tool(name="roam_impact",
       description="Blast radius: all symbols and files affected by changing a symbol.",
       output_schema=_SCHEMA_IMPACT)
def impact(symbol: str, root: str = ".") -> dict:
    """Show the blast radius of changing a symbol.

    WHEN TO USE: Call this when you need to know everything that would
    break if a symbol's signature or behavior changed. For pre-change
    checks, prefer `preflight` which includes impact data plus tests
    and fitness checks.

    Parameters
    ----------
    symbol:
        Symbol to analyze.

    Returns: affected symbols grouped by hop distance, affected files,
    total affected count, and severity assessment.
    """
    return _run_roam(["impact", symbol], root)


@_tool(name="roam_file_info",
       description="File skeleton: all symbols with signatures, kinds, line ranges.")
def file_info(path: str, root: str = ".") -> dict:
    """Show a file skeleton: every symbol definition with its signature.

    WHEN TO USE: Call this when you need to understand what a file
    contains without reading the full source. Returns a structured
    outline that is more useful than Read for getting an overview.

    Parameters
    ----------
    path:
        File path relative to the project root.

    Returns: all symbols in the file (functions, classes, methods) with
    kind, line range, signature, export status, and parent relationships.
    Also includes per-kind counts and the file's detected language.
    """
    return _run_roam(["file", path], root)


# ===================================================================
# Tier 2 tools -- change-risk and deeper analysis
# ===================================================================


@_tool(name="roam_pr_risk",
       description="Risk score (0-100) for pending changes with per-file breakdown.",
       output_schema=_SCHEMA_PR_RISK)
def pr_risk(staged: bool = False, root: str = ".") -> dict:
    """Compute a risk score (0-100) for pending changes.

    WHEN TO USE: Call this before committing or creating a PR to assess
    risk. Analyzes the current diff and produces a risk rating (LOW /
    MODERATE / HIGH / CRITICAL) with specific risk factors.

    Parameters
    ----------
    staged:
        If True, analyze staged changes instead of working-tree diff.

    Returns: risk score, risk level, per-file breakdown (symbols changed,
    blast radius, churn), suggested reviewers, coupling surprises, and
    any new dead exports created.
    """
    args = ["pr-risk"]
    if staged:
        args.append("--staged")
    return _run_roam(args, root)


@_tool(name="roam_affected_tests",
       description="Test files that exercise changed code, with hop distance.")
def affected_tests(target: str = "", staged: bool = False, root: str = ".") -> dict:
    """Find test files that exercise the changed code.

    WHEN TO USE: Call this to know which tests to run after making
    changes. Walks reverse dependency edges from changed code to find
    test files. For a full pre-change check, prefer `preflight` which
    includes affected tests plus blast radius and fitness checks.

    Parameters
    ----------
    target:
        Symbol name or file path. If empty, uses all currently changed files.
    staged:
        If True, start from staged changes.

    Returns: test files with the symbols that link them to the change
    and the hop distance.
    """
    args = ["affected-tests"]
    if target:
        args.append(target)
    if staged:
        args.append("--staged")
    return _run_roam(args, root)


@_tool(name="roam_algo",
       description="Detect suboptimal algorithms with better alternatives and complexity analysis.")
def algo(task: str = "", confidence: str = "", root: str = ".") -> dict:
    """Detect suboptimal algorithms and suggest better approaches.

    WHEN TO USE: Call this to find code that uses naive algorithms when
    better alternatives exist (e.g., manual sort instead of built-in,
    linear scan instead of binary search, nested-loop lookup instead of
    hash join). Returns specific suggestions with complexity analysis.

    Parameters
    ----------
    task:
        Filter by task ID (e.g., "sorting", "membership", "nested-lookup").
        Empty means all tasks.
    confidence:
        Filter by confidence level: "high", "medium", or "low".

    Returns: findings grouped by algorithm category, each with current
    vs. better approach, complexity comparison, and improvement tips.
    """
    args = ["algo"]
    if task:
        args.extend(["--task", task])
    if confidence:
        args.extend(["--confidence", confidence])
    return _run_roam(args, root)


@_tool(name="roam_dead_code",
       description="Unreferenced exported symbols (dead code candidates).")
def dead_code(root: str = ".") -> dict:
    """List unreferenced exported symbols (dead code candidates).

    WHEN TO USE: Call this to find code that can be safely removed.
    Finds exported symbols with zero incoming edges, filtering out
    known entry points and framework lifecycle hooks.

    Returns: each dead symbol with kind, location, file, and a safety
    verdict indicating confidence level.
    """
    return _run_roam(["dead"], root)


@_tool(name="roam_complexity_report",
       description="Functions ranked by cognitive complexity above threshold.")
def complexity_report(threshold: int = 15, root: str = ".") -> dict:
    """Rank functions by cognitive complexity.

    WHEN TO USE: Call this to find the most complex functions that
    should be refactored. Only symbols at or above the threshold are
    included. For checking a single symbol, prefer `context` or
    `preflight` which include complexity data.

    Parameters
    ----------
    threshold:
        Minimum cognitive-complexity score to include (default 15).

    Returns: symbols ranked by complexity with score, nesting depth,
    parameter count, line count, severity label, and file location.
    """
    return _run_roam(["complexity", "--threshold", str(threshold)], root)


# ===================================================================
# MCP Resources -- static/cached summaries available at fixed URIs
# ===================================================================

if mcp is not None:

    @mcp.resource("roam://health")
    def get_health_resource() -> str:
        """Current codebase health snapshot (JSON).

        Provides the same data as the ``health`` tool but exposed as an
        MCP resource so agents can subscribe to or poll it.
        """
        data = _run_roam(["health"])
        return json.dumps(data, indent=2)

    @mcp.resource("roam://summary")
    def get_summary_resource() -> str:
        """Full codebase summary (JSON).

        Equivalent to calling the ``understand`` tool, exposed as a
        resource for agents that prefer resource-based access.
        """
        data = _run_roam(["understand"])
        return json.dumps(data, indent=2)

    @mcp.resource("roam://architecture")
    def get_architecture_resource() -> str:
        """Architectural layers and module boundaries (JSON)."""
        data = _run_roam(["layers"])
        return json.dumps(data, indent=2)

    @mcp.resource("roam://tech-stack")
    def get_tech_stack_resource() -> str:
        """Language and framework breakdown (JSON)."""
        data = _run_roam(["understand"])
        # Extract just the tech stack portion
        if isinstance(data, dict):
            return json.dumps({
                "languages": data.get("languages", {}),
                "files": data.get("files", {}),
                "frameworks": data.get("frameworks", []),
            }, indent=2)
        return json.dumps(data, indent=2)

    @mcp.resource("roam://dead-code")
    def get_dead_code_resource() -> str:
        """Dead/unreferenced symbols (JSON)."""
        data = _run_roam(["dead"])
        return json.dumps(data, indent=2)

    @mcp.resource("roam://recent-changes")
    def get_recent_changes_resource() -> str:
        """Recent git changes and their impact (JSON)."""
        data = _run_roam(["diff"])
        return json.dumps(data, indent=2)

    @mcp.resource("roam://dependencies")
    def get_dependencies_resource() -> str:
        """Module dependency graph overview (JSON)."""
        data = _run_roam(["deps"])
        return json.dumps(data, indent=2)

    @mcp.resource("roam://complexity")
    def get_complexity_resource() -> str:
        """Cognitive complexity analysis (JSON)."""
        data = _run_roam(["complexity"])
        return json.dumps(data, indent=2)


@_tool(name="roam_pr_diff",
       description="Structural graph delta of code changes: metric deltas, layer violations.")
def pr_diff(staged: bool = False, commit_range: str = "", root: str = ".") -> dict:
    """Show structural consequences of code changes (graph delta).

    WHEN TO USE: Call this during code review to understand the
    architectural impact of a PR. Shows metric deltas (health score,
    cycles, complexity), cross-cluster edges, layer violations, symbol
    changes, and graph footprint. Much richer than a text diff.

    Parameters
    ----------
    staged:
        If True, analyse only staged changes.
    commit_range:
        Git range like ``main..HEAD`` for branch comparison.

    Returns: verdict, metric deltas, edge analysis, symbol changes,
    and graph footprint.
    """
    args = ["pr-diff"]
    if staged:
        args.append("--staged")
    if commit_range:
        args.extend(["--range", commit_range])
    return _run_roam(args, root)


@_tool(name="roam_effects",
       description="Side effects of functions: DB writes, network, filesystem (direct + transitive).")
def effects(target: str = "", file: str = "", effect_type: str = "", root: str = ".") -> dict:
    """Show side effects of functions (DB writes, network, filesystem, etc.).

    WHEN TO USE: Call this to understand what a function actually DOES
    beyond its signature. Shows both direct effects (from the function
    body) and transitive effects (inherited from callees via the call
    graph). Useful for assessing change risk and understanding data flow.

    Parameters
    ----------
    target:
        Symbol name to inspect effects for.
    file:
        File path to show effects per function.
    effect_type:
        Filter by effect type (e.g. "writes_db", "network").

    Returns: classified effects (direct and transitive) for the symbol,
    file, or entire codebase.
    """
    args = ["effects"]
    if target:
        args.append(target)
    if file:
        args.extend(["--file", file])
    if effect_type:
        args.extend(["--type", effect_type])
    return _run_roam(args, root)


# ===================================================================
# Daily workflow tools
# ===================================================================


@_tool(name="roam_diff",
       description="Blast radius of uncommitted/committed changes: affected symbols, files, tests.",
       output_schema=_SCHEMA_DIFF)
def roam_diff(commit_range: str = "", staged: bool = False, root: str = ".") -> dict:
    """Blast radius of uncommitted or committed changes.

    WHEN TO USE: call after making code changes to see what's affected
    BEFORE committing. Shows affected symbols, files, tests, coupling
    warnings, and fitness violations.

    WHEN NOT TO USE: for pre-PR analysis use roam_pr_risk instead.

    Parameters
    ----------
    commit_range:
        Git range like ``HEAD~3..HEAD`` or ``main..feature``.
        Empty = uncommitted working tree changes.
    staged:
        If True, analyze git-staged changes only.
    root:
        Working directory (project root).

    Returns: changed files, affected symbols, blast radius metrics,
    per-file breakdown.
    """
    args = ["diff"]
    if commit_range:
        args.append(commit_range)
    if staged:
        args.append("--staged")
    return _run_roam(args, root)


@_tool(name="roam_uses",
       description="All consumers of a symbol: callers, importers, inheritors by edge type.")
def roam_uses(name: str, full: bool = False, root: str = ".") -> dict:
    """All consumers of a symbol: callers, importers, inheritors.

    WHEN TO USE: to find ALL places using a symbol, grouped by edge type
    (calls, imports, inheritance, trait usage). Broader than roam_impact.
    Use for planning API changes.

    Parameters
    ----------
    name:
        Symbol name. Supports partial matching.
    full:
        Show all consumers without truncation.
    root:
        Working directory (project root).

    Returns: symbol name, total_consumers, total_files, consumers
    grouped by edge kind with name, kind, and location.
    """
    args = ["uses", name]
    if full:
        args.append("--full")
    return _run_roam(args, root)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command()
@click.option('--transport', type=click.Choice(['stdio', 'sse', 'streamable-http']), default='stdio',
              help='transport protocol (default: stdio)')
@click.option('--host', default='127.0.0.1', help='host for network transports')
@click.option('--port', type=int, default=8000, help='port for network transports')
@click.option('--no-auto-index', is_flag=True, help='skip automatic index freshness check')
@click.option('--list-tools', is_flag=True, help='list registered tools and exit')
@click.option('--list-tools-json', is_flag=True,
              help='list registered tools with metadata as JSON and exit')
@click.option('--compat-profile',
              type=click.Choice(['all', 'claude', 'codex', 'gemini', 'copilot', 'vscode', 'cursor']),
              default=None,
              help='emit client compatibility profile JSON and exit')
def mcp_cmd(transport, host, port, no_auto_index, list_tools, list_tools_json, compat_profile):
    """Start the roam MCP server.

    \b
    usage:
      roam mcp                    # stdio (for Claude Code, Cursor, etc.)
      roam mcp --transport sse    # SSE on localhost:8000
      roam mcp --transport streamable-http  # Streamable HTTP on localhost:8000
      roam mcp --list-tools       # show registered tools
      roam mcp --list-tools-json  # JSON metadata for conformance checks
      roam mcp --compat-profile all  # client compatibility matrix (JSON)

    \b
    integration:
      claude mcp add roam-code -- roam mcp

    \b
    requires:
      pip install roam-code[mcp]
    """
    if compat_profile:
        payload = _compat_profile_payload(compat_profile, ".")
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    if mcp is None:
        click.echo(
            "error: fastmcp is required for the MCP server.\n"
            "install it with:  pip install roam-code[mcp]",
            err=True,
        )
        raise SystemExit(1)

    if list_tools_json:
        async def _collect_tools():
            return await mcp.list_tools()

        tools = asyncio.run(_collect_tools())
        payload_tools = []
        for tool in sorted(tools, key=lambda t: t.name):
            ann = tool.annotations.model_dump(exclude_none=True) if tool.annotations else {}
            execution = tool.execution.model_dump(exclude_none=True) if tool.execution else {}
            meta = dict(tool.meta or {})
            payload_tools.append({
                "name": tool.name,
                "title": tool.title,
                "description": tool.description,
                "annotations": ann,
                "task_support": execution.get("taskSupport") or meta.get("taskSupport"),
            })
        payload = {
            "server": "roam-code",
            "tool_count": len(payload_tools),
            "tools": payload_tools,
        }
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    if list_tools:
        click.echo(f"{len(_REGISTERED_TOOLS)} tools registered:\n")
        for t in sorted(_REGISTERED_TOOLS):
            click.echo(f"  {t}")
        return

    if not no_auto_index:
        sys.stderr.write("checking index freshness...\n")
        err = _ensure_fresh_index(".")
        if err:
            sys.stderr.write(f"warning: {err['error']}\n")
        else:
            sys.stderr.write("index is fresh.\n")

    if transport == "stdio":
        mcp.run()
    elif transport == "sse":
        mcp.run(transport="sse", host=host, port=port)
    else:
        try:
            mcp.run(transport="streamable-http", host=host, port=port)
        except TypeError:
            # Older FastMCP versions may use "http" alias.
            mcp.run(transport="http", host=host, port=port)


# ---------------------------------------------------------------------------
# MCP Prompts — show as slash commands in Claude Code, VS Code, etc.
# ---------------------------------------------------------------------------

if mcp is not None:
    try:
        @mcp.prompt(name="roam-onboard", description="Get started with a new codebase")
        def prompt_onboard() -> str:
            return (
                "I'm new to this codebase. Please run roam_explore to get an overview, "
                "then summarize the architecture, key entry points, and tech stack. "
                "Suggest 3 files I should read first to understand the codebase."
            )

        @mcp.prompt(name="roam-review", description="Review pending code changes")
        def prompt_review() -> str:
            return (
                "Review my pending code changes. Run roam_review_change to check for "
                "breaking changes, risk score, and structural impact. Then run "
                "roam_affected_tests to identify what tests I should run. "
                "Summarize findings with actionable items."
            )

        @mcp.prompt(name="roam-debug", description="Debug a failing symbol or test")
        def prompt_debug(symbol: str = "") -> str:
            target = f" for `{symbol}`" if symbol else ""
            return (
                f"Help me debug an issue{target}. Run roam_diagnose "
                f"{'with target=' + repr(symbol) + ' ' if symbol else ''}"
                "to find root cause suspects, then check the call chain and "
                "side effects. Suggest the most likely cause and a fix."
            )

        @mcp.prompt(name="roam-refactor", description="Plan a safe refactoring")
        def prompt_refactor(symbol: str = "") -> str:
            target = f" `{symbol}`" if symbol else " the target symbol"
            return (
                f"Help me safely refactor{target}. Run roam_prepare_change to check "
                "blast radius, affected tests, and side effects. Then suggest a "
                "step-by-step refactoring plan that minimizes risk."
            )

        @mcp.prompt(name="roam-health-check", description="Full codebase health assessment")
        def prompt_health_check() -> str:
            return (
                "Run a comprehensive health check on this codebase. Use roam_health "
                "for the overall score, roam_dead_code for unused code, and "
                "roam_complexity_report for complexity hotspots. Prioritize the "
                "top 3 issues I should fix first and explain why."
            )
    except (TypeError, AttributeError):
        # Older FastMCP versions may not support @mcp.prompt() — define as
        # plain functions so they're still importable for testing.
        def prompt_onboard() -> str:  # type: ignore[no-redef]
            return (
                "I'm new to this codebase. Please run roam_explore to get an overview, "
                "then summarize the architecture, key entry points, and tech stack. "
                "Suggest 3 files I should read first to understand the codebase."
            )

        def prompt_review() -> str:  # type: ignore[no-redef]
            return (
                "Review my pending code changes. Run roam_review_change to check for "
                "breaking changes, risk score, and structural impact. Then run "
                "roam_affected_tests to identify what tests I should run. "
                "Summarize findings with actionable items."
            )

        def prompt_debug(symbol: str = "") -> str:  # type: ignore[no-redef]
            target = f" for `{symbol}`" if symbol else ""
            return (
                f"Help me debug an issue{target}. Run roam_diagnose "
                f"{'with target=' + repr(symbol) + ' ' if symbol else ''}"
                "to find root cause suspects, then check the call chain and "
                "side effects. Suggest the most likely cause and a fix."
            )

        def prompt_refactor(symbol: str = "") -> str:  # type: ignore[no-redef]
            target = f" `{symbol}`" if symbol else " the target symbol"
            return (
                f"Help me safely refactor{target}. Run roam_prepare_change to check "
                "blast radius, affected tests, and side effects. Then suggest a "
                "step-by-step refactoring plan that minimizes risk."
            )

        def prompt_health_check() -> str:  # type: ignore[no-redef]
            return (
                "Run a comprehensive health check on this codebase. Use roam_health "
                "for the overall score, roam_dead_code for unused code, and "
                "roam_complexity_report for complexity hotspots. Prioritize the "
                "top 3 issues I should fix first and explain why."
            )
else:
    # FastMCP not available — define plain functions for importability.
    def prompt_onboard() -> str:
        return (
            "I'm new to this codebase. Please run roam_explore to get an overview, "
            "then summarize the architecture, key entry points, and tech stack. "
            "Suggest 3 files I should read first to understand the codebase."
        )

    def prompt_review() -> str:
        return (
            "Review my pending code changes. Run roam_review_change to check for "
            "breaking changes, risk score, and structural impact. Then run "
            "roam_affected_tests to identify what tests I should run. "
            "Summarize findings with actionable items."
        )

    def prompt_debug(symbol: str = "") -> str:
        target = f" for `{symbol}`" if symbol else ""
        return (
            f"Help me debug an issue{target}. Run roam_diagnose "
            f"{'with target=' + repr(symbol) + ' ' if symbol else ''}"
            "to find root cause suspects, then check the call chain and "
            "side effects. Suggest the most likely cause and a fix."
        )

    def prompt_refactor(symbol: str = "") -> str:
        target = f" `{symbol}`" if symbol else " the target symbol"
        return (
            f"Help me safely refactor{target}. Run roam_prepare_change to check "
            "blast radius, affected tests, and side effects. Then suggest a "
            "step-by-step refactoring plan that minimizes risk."
        )

    def prompt_health_check() -> str:
        return (
            "Run a comprehensive health check on this codebase. Use roam_health "
            "for the overall score, roam_dead_code for unused code, and "
            "roam_complexity_report for complexity hotspots. Prioritize the "
            "top 3 issues I should fix first and explain why."
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if mcp is None:
        raise SystemExit(
            "fastmcp is required for the MCP server.\n"
            "Install it with:  pip install roam-code[mcp]"
        )
    mcp.run()
