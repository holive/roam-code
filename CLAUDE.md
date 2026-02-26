# CLAUDE.md — roam-code development guide

## What this project is

roam-code is a CLI tool that gives AI coding agents instant codebase comprehension.
It pre-indexes symbols, call graphs, dependencies, architecture, and git history into
a local SQLite DB. 37 commands, 23 MCP tools, 15+ languages, 100% local, zero API keys.

**Package:** `roam-code` on PyPI. Entry point: `roam.cli:cli`.

## Quick reference

```bash
# Run tests
pytest tests/

# Run tests in parallel (requires pytest-xdist)
pytest tests/ -n auto

# Skip timing-sensitive perf tests
pytest tests/ -m "not slow"

# Run a single test file
pytest tests/test_comprehensive.py -x -v

# Install in dev mode
pip install -e .

# Index roam itself
roam init
roam health
```

## Architecture

### Directory layout

```
src/roam/
  cli.py              # Click CLI entry point — LazyGroup, _COMMANDS dict, _CATEGORIES
  mcp_server.py       # FastMCP server (23 tools) + `roam mcp` CLI command
  __init__.py          # Version string (reads from pyproject.toml via importlib.metadata)
  db/
    schema.py          # SQLite schema (CREATE TABLE statements)
    connection.py      # open_db(), ensure_schema(), batched_in(), migrations
    queries.py         # Named SQL constants
  index/
    indexer.py         # Full pipeline: discovery → parse → extract → resolve → metrics → health → cognitive load
    discovery.py       # git ls-files, .gitignore
    parser.py          # Tree-sitter parsing
    symbols.py         # Symbol + reference extraction
    relations.py       # Reference resolution → edges
    complexity.py      # Cognitive complexity (SonarSource-compatible)
    git_stats.py       # Churn, co-change, blame, entropy
    incremental.py     # mtime + hash change detection
    file_roles.py      # Smart file role classifier (source, test, config, docs, etc.)
    test_conventions.py # Pluggable test naming adapters (Python, Go, JS, Java, Ruby)
  bridges/
    base.py            # abstract LanguageBridge — cross-language symbol resolution
    registry.py        # bridge auto-discovery + detection
    bridge_rest_api.py # frontend HTTP calls → backend route definitions
    bridge_template.py # Jinja2/Django/ERB/Handlebars variable + include resolution
    bridge_config.py   # env var reads → .env/.yml definitions
  catalog/
    tasks.py           # universal algorithm catalog — 23 tasks with ranked solution approaches
    detectors.py       # algorithm anti-pattern detectors — query DB signals to find suboptimal patterns
  languages/
    base.py            # abstract LanguageExtractor — all languages inherit this
    registry.py        # language detection + grammar aliasing
    *_lang.py          # one file per language (python, javascript, typescript, java, go, rust, c, cpp, csharp, php, ruby, kotlin, swift, hcl, yaml, generic)
  graph/
    builder.py         # DB → NetworkX graph
    pagerank.py        # PageRank + centrality metrics
    cycles.py          # Tarjan SCC + tangle ratio
    clusters.py        # Louvain community detection
    layers.py          # topological layer detection — returns {node_id: layer_number}
    pathfinding.py     # k-shortest paths for trace
    diff.py            # graph diff for PR analysis
  symbol_search/
    tfidf.py           # zero-dependency TF-IDF semantic search
    index_embeddings.py # symbol corpus + cosine similarity
  commands/
    resolve.py         # shared symbol resolution + ensure_index()
    changed_files.py   # shared git changeset detection
    graph_helpers.py   # shared graph utilities (adjacency builders, BFS helpers)
    context_helpers.py # data-gathering helpers extracted from cmd_context.py
    cmd_*.py           # one module per CLI command (37 commands)
  output/
    formatter.py       # token-efficient text formatting, abbrev_kind(), loc(), format_table(), to_json(), json_envelope()
    mermaid.py         # Mermaid diagram generation for visualize command
tests/                 # pytest suite with ~40 test files
```

### Key patterns

- **Lazy-loading commands:** `cli.py` uses a `LazyGroup` that imports command modules only when invoked. this avoids importing networkx (~500ms) on every CLI call. register new commands in `_COMMANDS` dict and `_CATEGORIES` dict.

- **Command template:** Every command follows this pattern:
  ```python
  from __future__ import annotations  # required for Python 3.9 compat
  import click
  from roam.db.connection import open_db
  from roam.output.formatter import to_json, json_envelope
  from roam.commands.resolve import ensure_index

  @click.command()
  @click.pass_context
  def my_cmd(ctx):
      json_mode = ctx.obj.get('json') if ctx.obj else False
      ensure_index()
      with open_db(readonly=True) as conn:
          # ... query the DB ...
          if json_mode:
              click.echo(to_json(json_envelope("my-cmd",
                  summary={"verdict": "...", ...},
                  ...
              )))
              return
          # Text output
          click.echo("VERDICT: ...")
  ```

- **`from __future__ import annotations`** — required at top of every file for Python 3.9 compatibility.

- **Batched IN-clauses:** never write raw `WHERE id IN (...)` with a list > 400 items. use `batched_in()` from `connection.py` instead.

- **`detect_layers()` returns `{node_id: layer_number}`** — a dict, not a list of sets. convert if you need per-layer groupings.

- **Verdict-first output:** key commands emit a one-line `VERDICT:` as the first text output line and include `verdict` in the JSON summary.

- **JSON envelope:** all JSON output uses `json_envelope(command_name, summary={...}, **data)`. the summary dict should include a `verdict` field. envelopes automatically include `schema` and `schema_version` fields.


## Conventions

- **Functions:** `snake_case` (100%)
- **Classes:** `PascalCase` (100%)
- **Methods:** `snake_case` (100%)
- **Imports:** absolute imports for cross-directory; `from __future__ import annotations` at top of every source file
- **Test files:** `test_*.py` in `tests/`
- **Output abbreviations:** `fn` (function), `cls` (class), `meth` (method) — via `abbrev_kind()`
- **No emojis, no colors, no box-drawing** in output — plain ASCII only for token efficiency

## Adding a new CLI command

1. Create `src/roam/commands/cmd_yourcommand.py` following the command template above
2. Register in `cli.py` → `_COMMANDS` dict: `"your-command": ("roam.commands.cmd_yourcommand", "your_command")`
3. Add to appropriate category in `_CATEGORIES` dict
4. Add MCP tool wrapper in `mcp_server.py` if useful for agents
5. Add tests

## Adding a new language

1. create `src/roam/languages/yourlang_lang.py` inheriting from `LanguageExtractor`
2. see `go_lang.py` or `php_lang.py` as clean templates
3. register in `registry.py`
4. add tests in `tests/`

## Schema changes

1. add column in `schema.py` (CREATE TABLE)
2. add migration in `connection.py` → `ensure_schema()` using `_safe_alter()`
3. populate in `indexer.py` pipeline

## Testing

- all tests must pass before committing (run `pytest tests/` to verify)
- **Parallel by default:** pytest-xdist runs auto workers (`-n auto --dist loadgroup`)
- use `-n 0` to run sequentially when debugging
- use `-m "not slow"` to skip timing-sensitive performance tests
- tests create temporary project directories with fixture files
- use `CliRunner` from Click for command tests
- run full suite: `pytest tests/`
- run specific: `pytest tests/test_comprehensive.py::TestHealth -x -v -n 0`
- mark tests needing sequential execution with `@pytest.mark.xdist_group("groupname")`

## Dependencies

- click >= 8.0 (CLI framework)
- tree-sitter >= 0.23 (AST parsing)
- tree-sitter-language-pack >= 0.6 (165+ grammars)
- networkx >= 3.0 (graph algorithms)
- Optional: fastmcp >= 2.0 (MCP server — `pip install "roam-code[mcp]"`)
- Dev: pytest >= 7.0, pytest-xdist >= 3.0, ruff >= 0.4

## Version bumping

update **one place only**: `pyproject.toml` → `version`

`__init__.py` reads it dynamically via `importlib.metadata`. README badge pulls from PyPI.

## Codebase navigation with roam

this project uses `roam` for codebase comprehension. always prefer roam over Glob/Grep/Read exploration.

before modifying any code:
1. first time in the repo: `roam understand`
2. find a symbol: `roam search <pattern>`
3. before changing a symbol: `roam preflight <name>` (blast radius + tests + complexity)
4. need files to read: `roam context <name>` (files + line ranges, prioritized)
5. debugging a failure: `roam diagnose <name>` (root cause ranking)
6. after making changes: `roam diff` (blast radius of uncommitted changes)

additional commands: `roam health` (0-100 score), `roam impact <name>` (what breaks),
`roam pr-risk` (PR risk score), `roam file <path>` (file skeleton).

run `roam --help` for all commands. use `roam --json <cmd>` for structured output.
