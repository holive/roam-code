<div align="center">

# Roam Code

**Codebase intelligence for AI coding agents. Pre-indexed symbols, call graphs, dependencies, and architecture -- queried locally, no API keys.**

*37 commands · 23 MCP tools · 15+ languages · 100% local*

[![PyPI version](https://img.shields.io/pypi/v/roam-code?style=flat-square&color=blue)](https://pypi.org/project/roam-code/)
[![GitHub stars](https://img.shields.io/github/stars/Cranot/roam-code?style=flat-square)](https://github.com/Cranot/roam-code/stargazers)
[![CI](https://github.com/Cranot/roam-code/actions/workflows/roam-ci.yml/badge.svg)](https://github.com/Cranot/roam-code/actions/workflows/roam-ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

> Forked from [CosmoHac/roam-code](https://github.com/Cranot/roam-code). This fork trims the project to its core mission: giving AI coding agents instant codebase comprehension.

</div>

---

## What is Roam?

Roam is a codebase comprehension engine for AI coding agents. It pre-indexes your project into a local SQLite database: symbols, dependencies, call graphs, architecture layers, git history, and complexity metrics. Agents query it via CLI or MCP instead of repeatedly grepping files and guessing structure.

Unlike LSPs (editor-bound, language-specific) or Sourcegraph (cloud-based search), Roam provides architecture-level graph queries offline and cross-language. It answers questions like:

- What breaks if I change this function?
- Which tests exercise this code?
- What's the shortest path between these two symbols?
- What functions write to the database?
- Where are the code hotspots (high churn + high complexity)?

```
# one-time setup
roam init

# exploration
roam search handle_payment
roam trace OrderService.create PaymentGateway.charge
roam impact calculate_tax

# workflow
roam preflight UserAuth.login
roam context UserService --task refactor
roam diff
roam pr-risk

# quality
roam health
roam debt --roi
roam algo
```

---

## Install

```bash
pip install roam-code
```

For MCP server support (Claude Code, Cursor, Windsurf):

```bash
pip install roam-code[mcp]
```

---

## Quick Start

1. **Index your project:**
   ```bash
   cd /path/to/your/project
   roam init
   ```

2. **Explore the codebase:**
   ```bash
   roam understand              # full project briefing
   roam search AuthService      # find symbols
   roam file src/api/auth.py    # file skeleton
   roam health                  # codebase health score
   ```

3. **Pre-change checks:**
   ```bash
   roam preflight login_handler # blast radius + tests + complexity
   roam context login_handler   # minimal context for safe modification
   ```

4. **Post-change analysis:**
   ```bash
   roam diff                    # blast radius of uncommitted changes
   roam pr-risk                 # risk score for PR
   ```

5. **Enable MCP for AI agents:**
   ```bash
   roam mcp-setup claude-code   # or cursor, windsurf, vscode, etc.
   ```

---

## Commands

### Setup (8 commands)

| Command | Description |
|---------|-------------|
| `init` | Initialize Roam for this project: index, config, CI workflow |
| `index` | Build or rebuild the codebase index |
| `reset` | Delete the index DB and rebuild from scratch |
| `clean` | Remove orphaned entries from the index (files no longer on disk) |
| `config` | Manage per-project roam configuration (.roam/config.json) |
| `doctor` | Diagnose environment setup: Python, dependencies, index state, disk space |
| `mcp` | Start the roam MCP server |
| `mcp-setup` | Generate MCP server config for AI coding platforms |

### Exploration (8 commands)

| Command | Description |
|---------|-------------|
| `search` | Find symbols matching a name substring (case-insensitive) |
| `file` | Show file skeleton: all definitions with signatures |
| `trace` | Show shortest path between two symbols |
| `deps` | Show file import/imported-by relationships |
| `uses` | Show all consumers of a symbol: callers, importers, inheritors |
| `impact` | Show blast radius: what breaks if a symbol changes |
| `endpoints` | List all detected REST/GraphQL/gRPC endpoints with handlers |
| `understand` | Single-call codebase comprehension -- everything in one shot |

### Workflow (9 commands)

| Command | Description |
|---------|-------------|
| `preflight` | Run a pre-change safety checklist for a symbol, file, or staged changes |
| `diff` | Show blast radius: what code is affected by your changes |
| `affected-tests` | Trace from a changed symbol or file to test files that exercise it |
| `affected` | Identify affected files/modules from a git diff via dependency graph |
| `context` | Get the minimal context needed to safely modify a symbol |
| `diagnose` | Root cause analysis for a failing symbol |
| `pr-risk` | Compute risk score for pending changes |
| `pr-diff` | Show structural impact of pending changes |
| `syntax-check` | Check files for syntax errors using tree-sitter AST parsing |

### Quality (6 commands)

| Command | Description |
|---------|-------------|
| `health` | Show code health: cycles, god components, bottlenecks |
| `debt` | Hotspot-weighted technical debt prioritization |
| `complexity` | Show cognitive complexity metrics for functions and methods |
| `dead` | Show unreferenced exported symbols (dead code) |
| `algo` | Detect suboptimal algorithms and suggest better approaches |
| `weather` | Show code hotspots: churn x complexity ranking |

### Architecture (6 commands)

| Command | Description |
|---------|-------------|
| `map` | Show project skeleton with entry points and key symbols |
| `layers` | Show dependency layers and violations |
| `clusters` | Show code clusters and directory mismatches |
| `effects` | Show what functions DO -- side-effect classification |
| `entry-points` | Entry point catalog with protocol classification |
| `visualize` | Generate a Mermaid or DOT architecture diagram |

**Note:** `math` is an alias for `algo` (backward compatibility).

---

## MCP Tools (23 tools)

Roam provides a FastMCP server with 23 tools for AI coding agents. All tools work on the local index -- no API keys, no rate limits.

**Compound operations (4):**
- `roam_explore` - overview + optional symbol deep-dive in one call
- `roam_prepare_change` - preflight + context + effects in one call
- `roam_review_change` - pr-risk + structural diff in one call
- `roam_diagnose` - root cause suspects + side effects in one call

**Batch operations (2):**
- `roam_batch_search` - search up to 10 patterns in one call
- `roam_batch_get` - get details for up to 50 symbols in one call

**Single tools (17):**
Core: `roam_understand`, `roam_health`, `roam_search_symbol`, `roam_file_info`

Workflow: `roam_preflight`, `roam_context`, `roam_diff`, `roam_affected_tests`

Graph: `roam_trace`, `roam_impact`, `roam_uses`, `roam_effects`

Quality: `roam_complexity_report`, `roam_dead_code`, `roam_algo`

PR analysis: `roam_pr_risk`, `roam_pr_diff`

Enable MCP for your agent:

```bash
# claude code
roam mcp-setup claude-code

# cursor
roam mcp-setup cursor

# windsurf
roam mcp-setup windsurf
```

---

## Languages

Roam supports 15+ languages with dedicated symbol extractors:

- **Tier 1 (full symbol + call graph):** Python, JavaScript, TypeScript/TSX, Go, Rust, Java, C, C++, C#, PHP, Ruby, Kotlin, Swift
- **Tier 2 (symbols + imports):** Scala, Vue, Svelte, YAML, HCL (Terraform), JSONC, MDX

Additional grammars are handled via a generic extractor that captures top-level definitions and imports.

---

## Architecture Overview

```
roam-code/
  src/roam/
    cli.py              # lazy-loading Click CLI with 37 commands
    mcp_server.py       # FastMCP server with 23 tools
    db/                 # SQLite schema, queries, migrations
    index/              # indexer pipeline (discovery, parsing, extraction, resolution)
    languages/          # language extractors (Python, Go, TypeScript, etc.)
    bridges/            # cross-language symbol resolution (REST API, templates, config)
    catalog/            # algorithm catalog + anti-pattern detectors
    graph/              # NetworkX graph algorithms (PageRank, cycles, layers, etc.)
    symbol_search/      # FTS5 + TF-IDF symbol search infrastructure
    commands/           # one module per CLI command
    output/             # JSON/text formatters + Mermaid diagrams
  tests/                # pytest suite (~40 test files)
```

**Key patterns:**
- **Local SQLite index** - symbols, edges, metrics, git stats stored in `.roam/index.db`
- **Incremental indexing** - only re-parses changed files (mtime + hash tracking)
- **Cross-language bridges** - resolve HTTP route calls, template includes, env var reads
- **Graph algorithms** - PageRank centrality, Tarjan SCC cycles, topological layers, k-shortest paths
- **Git-aware** - churn, co-change, blame, entropy metrics from git history

---

## JSON Output

Every command supports `--json` for structured output:

```bash
roam --json health
roam --json preflight UserService.login
roam --json search AuthService
```

All JSON responses use a standard envelope:

```json
{
  "command": "health",
  "schema": "roam.health.v1",
  "schema_version": "1.0.0",
  "summary": {
    "verdict": "HEALTHY",
    "score": 87,
    "...": "..."
  },
  "...": "..."
}
```

---

## Exit Codes

Roam uses semantic exit codes for CI/CD integration:

- `0` - Success
- `1` - Error (missing index, invalid args, unexpected exception)
- `5` - Syntax errors detected (`roam syntax-check`)

---

## Performance

- **Index build:** ~2000 files/sec on modern hardware (M1/M2/Ryzen)
- **Incremental reindex:** ~10x faster (only re-parses changed files)
- **Query latency:** <100ms for most graph queries (PageRank, cycles, layers)
- **Disk usage:** ~1-5MB per 1000 files (SQLite + FTS5 index)

---

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

Key areas:
- New language extractors (see `src/roam/languages/`)
- New bridges (cross-language symbol resolution)
- New graph algorithms (see `src/roam/graph/`)
- Performance optimizations (indexing, queries, graph algorithms)

Run tests:

```bash
pytest tests/               # full suite
pytest tests/ -n auto       # parallel (requires pytest-xdist)
pytest tests/ -m "not slow" # skip timing-sensitive perf tests
```

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Links

- **PyPI:** https://pypi.org/project/roam-code/
- **GitHub:** https://github.com/Cranot/roam-code
- **Issues:** https://github.com/Cranot/roam-code/issues
- **Discussions:** https://github.com/Cranot/roam-code/discussions








