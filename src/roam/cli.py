"""Click CLI entry point with lazy-loaded subcommands."""

from __future__ import annotations

import os
import sys

# Fix Unicode output on Windows consoles (cp1253, cp1252, etc.)
if sys.platform == "win32" and not os.environ.get("PYTHONIOENCODING"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import click


# Lazy-loading command group: imports command modules only when invoked.
# This avoids importing networkx (~500ms) on every CLI call.
# ~37 commands focused on agent codebase comprehension.
_COMMANDS = {
    # setup
    "init":         ("roam.commands.cmd_init",         "init"),
    "index":        ("roam.commands.cmd_index",        "index"),
    "reset":        ("roam.commands.cmd_reset",        "reset"),
    "clean":        ("roam.commands.cmd_clean",         "clean"),
    "config":       ("roam.commands.cmd_config",        "config"),
    "doctor":       ("roam.commands.cmd_doctor",        "doctor"),
    "mcp":          ("roam.mcp_server",                 "mcp_cmd"),
    "mcp-setup":    ("roam.commands.cmd_mcp_setup",     "mcp_setup"),
    # exploration
    "search":       ("roam.commands.cmd_search",        "search"),
    "file":         ("roam.commands.cmd_file",          "file_cmd"),
    "trace":        ("roam.commands.cmd_trace",         "trace"),
    "deps":         ("roam.commands.cmd_deps",          "deps"),
    "uses":         ("roam.commands.cmd_uses",          "uses"),
    "impact":       ("roam.commands.cmd_impact",        "impact"),
    "endpoints":    ("roam.commands.cmd_endpoints",     "endpoints"),
    "understand":   ("roam.commands.cmd_understand",    "understand"),
    # workflow
    "preflight":    ("roam.commands.cmd_preflight",     "preflight"),
    "diff":         ("roam.commands.cmd_diff",          "diff_cmd"),
    "affected-tests": ("roam.commands.cmd_affected_tests", "affected_tests"),
    "affected":     ("roam.commands.cmd_affected",      "affected"),
    "context":      ("roam.commands.cmd_context",       "context"),
    "diagnose":     ("roam.commands.cmd_diagnose",      "diagnose"),
    "pr-risk":      ("roam.commands.cmd_pr_risk",       "pr_risk"),
    "pr-diff":      ("roam.commands.cmd_pr_diff",       "pr_diff"),
    "syntax-check": ("roam.commands.cmd_syntax_check",  "syntax_check"),
    # quality
    "health":       ("roam.commands.cmd_health",        "health"),
    "debt":         ("roam.commands.cmd_debt",          "debt"),
    "complexity":   ("roam.commands.cmd_complexity",    "complexity"),
    "dead":         ("roam.commands.cmd_dead",          "dead"),
    "algo":         ("roam.commands.cmd_math",          "math_cmd"),
    "math":         ("roam.commands.cmd_math",          "math_cmd"),
    "weather":      ("roam.commands.cmd_weather",       "weather"),
    # architecture
    "map":          ("roam.commands.cmd_map",           "map_cmd"),
    "layers":       ("roam.commands.cmd_layers",        "layers"),
    "clusters":     ("roam.commands.cmd_clusters",      "clusters"),
    "effects":      ("roam.commands.cmd_effects",       "effects"),
    "entry-points": ("roam.commands.cmd_entry_points",  "entry_points"),
    "visualize":    ("roam.commands.cmd_visualize",     "visualize"),
}

# Command categories for organized --help display
_CATEGORIES = {
    "Setup": [
        "init", "index", "reset", "clean", "config", "doctor",
        "mcp", "mcp-setup",
    ],
    "Exploration": [
        "search", "file", "trace", "deps", "uses", "impact",
        "endpoints", "understand",
    ],
    "Workflow": [
        "preflight", "diff", "affected-tests", "affected",
        "context", "diagnose", "pr-risk", "pr-diff",
        "syntax-check",
    ],
    "Quality": [
        "health", "debt", "complexity", "dead", "algo",
        "weather",
    ],
    "Architecture": [
        "map", "layers", "clusters", "effects",
        "entry-points", "visualize",
    ],
}

_PLUGIN_COMMANDS_LOADED = False


def _ensure_plugin_commands_loaded() -> None:
    """Merge discovered plugin commands into the CLI command map once."""
    global _PLUGIN_COMMANDS_LOADED
    if _PLUGIN_COMMANDS_LOADED:
        return
    _PLUGIN_COMMANDS_LOADED = True

    try:
        from roam.plugins import get_plugin_commands

        for cmd_name, target in get_plugin_commands().items():
            if cmd_name in _COMMANDS:
                continue
            _COMMANDS[cmd_name] = target
    except Exception:
        # Plugin loading should never break core CLI behavior.
        return


class LazyGroup(click.Group):
    """A Click group that lazy-loads command modules on first access."""

    def list_commands(self, ctx):
        _ensure_plugin_commands_loaded()
        return sorted(_COMMANDS.keys())

    def get_command(self, ctx, cmd_name):
        _ensure_plugin_commands_loaded()
        if cmd_name not in _COMMANDS:
            return None
        module_path, attr_name = _COMMANDS[cmd_name]
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name)

    def invoke(self, ctx):
        """Override invoke to map unhandled exceptions to standardized exit codes.

        RoamError subclasses (IndexMissingError, GateFailureError, etc.) carry
        their own exit_code and are handled by Click's ClickException machinery.
        This override catches *unexpected* exceptions (KeyError, TypeError, etc.)
        and maps them to EXIT_ERROR (1) instead of letting Python print a traceback
        with exit code 1 (which is ambiguous).
        """
        try:
            return super().invoke(ctx)
        except click.exceptions.Exit:
            # click.Context.exit() raises this — propagate as-is
            raise
        except (click.Abort, click.ClickException, SystemExit):
            # Click-managed exceptions — propagate as-is
            raise
        except Exception as exc:
            from roam.exit_codes import EXIT_ERROR
            click.echo(f"Error: {exc}", err=True)
            ctx.exit(EXIT_ERROR)

    def format_help(self, ctx, formatter):
        """Categorized help display instead of flat alphabetical list."""
        _ensure_plugin_commands_loaded()
        self.format_usage(ctx, formatter)
        formatter.write("\n")
        if self.help:
            formatter.write(self.help + "\n\n")

        # Show all categories
        shown = set()
        for cat_name in _CATEGORIES:
            cmds = _CATEGORIES.get(cat_name, [])
            valid_cmds = [c for c in cmds if c in _COMMANDS and c not in shown]
            if not valid_cmds:
                continue
            formatter.write(f"  {cat_name}:\n")
            for cmd_name in valid_cmds:
                cmd = self.get_command(ctx, cmd_name)
                if cmd is None:
                    continue
                help_text = cmd.get_short_help_str(limit=60) if cmd else ""
                formatter.write(f"    {cmd_name:20s} {help_text}\n")
                shown.add(cmd_name)
            formatter.write("\n")

        remaining = sorted(c for c in _COMMANDS if c not in shown)
        if remaining:
            formatter.write(f"  More Commands ({len(remaining)}):\n")
            formatter.write(f"    {', '.join(remaining)}\n\n")

        formatter.write("  Run `roam <command> --help` for details on any command.\n")


def _run_check(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    """Eager callback for --check: run critical install checks and exit.

    Validates the five minimum requirements for roam-code to function:
      1. Python >= 3.9
      2. tree-sitter importable
      3. tree-sitter-language-pack importable
      4. git on PATH
      5. SQLite in-memory DB usable

    Exits 0 on success ("roam-code ready"), 1 on any failure.
    """
    if not value or ctx.resilient_parsing:
        return

    issues: list[str] = []

    # 1. Python version
    if sys.version_info < (3, 9):
        issues.append(
            f"Python {sys.version_info.major}.{sys.version_info.minor} < 3.9"
        )

    # 2. tree-sitter
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        issues.append("tree-sitter not installed")

    # 3. tree-sitter-language-pack
    try:
        import tree_sitter_language_pack  # noqa: F401
    except ImportError:
        issues.append("tree-sitter-language-pack not installed")

    # 4. git on PATH
    import shutil
    if not shutil.which("git"):
        issues.append("git not found in PATH")

    # 5. SQLite in-memory database
    try:
        import sqlite3
        _conn = sqlite3.connect(":memory:")
        _conn.execute("SELECT 1")
        _conn.close()
    except Exception as exc:  # pragma: no cover
        issues.append(f"SQLite error: {exc}")

    if issues:
        click.echo(f"roam-code setup incomplete: {'; '.join(issues)}")
        ctx.exit(1)
    else:
        click.echo("roam-code ready")
        ctx.exit(0)


def _check_gate(gate_expr: str, data: dict) -> bool:
    """Evaluate a gate expression like 'score>=70' against data.

    Returns True if the gate passes, False if it fails.
    Supports: key>=N, key<=N, key>N, key<N, key=N
    """
    import re
    m = re.match(r'^(\w+)\s*(>=|<=|>|<|=)\s*(\d+(?:\.\d+)?)$', gate_expr.strip())
    if not m:
        return True  # can't parse, pass by default
    key, op, val_str = m.groups()
    val = float(val_str)

    actual = data.get(key)
    if actual is None:
        return True  # key not found, pass

    actual = float(actual)
    if op == '>=': return actual >= val
    if op == '<=': return actual <= val
    if op == '>': return actual > val
    if op == '<': return actual < val
    if op == '=': return actual == val
    return True


@click.group(cls=LazyGroup)
@click.version_option(package_name="roam-code")
@click.option(
    '--check',
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_run_check,
    help='Quick setup verification: checks Python, tree-sitter, git, SQLite',
)
@click.option('--json', 'json_mode', is_flag=True, help='Output in JSON format')
@click.option('--compact', is_flag=True, help='Compact output: TSV tables, minimal JSON envelope')
@click.option('--agent', is_flag=True, help='Agent mode: compact JSON with 500-token default budget')
@click.option('--budget', type=int, default=0, help='Max output tokens (0=unlimited)')
@click.option('--include-excluded', is_flag=True, help='Include files normally excluded by .roamignore / config / built-in patterns')
@click.option('--detail', is_flag=True, help='Show full detailed output instead of compact summary')
@click.pass_context
def cli(ctx, json_mode, compact, agent, budget, include_excluded, detail):
    """Roam: Codebase comprehension tool."""

    # Agent mode is optimized for CLI-invoked sub-agents:
    # - forces JSON for machine parsing
    # - uses compact envelope to reduce token overhead
    # - defaults to 500-token budget unless user overrides with --budget
    if agent:
        json_mode = True
        compact = True
        if budget <= 0:
            budget = 500

    ctx.ensure_object(dict)
    ctx.obj['json'] = json_mode
    ctx.obj['compact'] = compact
    ctx.obj['agent'] = agent
    ctx.obj['budget'] = budget
    ctx.obj['include_excluded'] = include_excluded
    ctx.obj['detail'] = detail
