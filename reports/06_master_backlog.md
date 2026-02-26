# roam-code Master Backlog v3 (Final)

> Compiled: February 2026
> Sources: 4 Opus research agents, 16 competitor audits, 7 verification passes, 7 strategy reports
> Methodology: 139 items audited → 47 killed → merged/consolidated → 3 new added → **65 active items in 11 epics + 20 someday/maybe (30+ when bundles expanded)**
> Current: v10.0.1 (87/108 competitive score, 286 stars)
> Target: v11.0.0 in 3-4 weeks

---

## Already Done (DO NOT re-add)

- [x] `roam mcp` command with `--transport`, `--list-tools` flags
- [x] MCP tool namespacing with `roam_` prefix (61 tools)
- [x] Lite mode (16 core tools, `ROAM_MCP_LITE=0` for full)
- [x] `fastmcp` optional dependency (`pip install roam-code[mcp]`)
- [x] MCP tests (50 functions, 395 lines)
- [x] Structured MCP error handling
- [x] CI workflow YAML `--json` flag fix
- [x] `PRAGMA mmap_size=268435456` (256MB memory-mapped I/O) in connection.py (#11)
- [x] Size guard on `propagation_cost()` — BFS sampling for graphs >500 nodes (#12)
- [x] O(N) → O(changed) incremental edge rebuild via `source_file_id` provenance tracking (#13)
- [x] FTS5/BM25 semantic search with `porter unicode61` tokenizer + camelCase preprocessing (#14)
- [x] DB Sprint: 7 new indexes, 1 redundant removed, UPSERT pattern, batch size 500 (#15)
- [x] In-process MCP via CliRunner — eliminates subprocess overhead per tool call (#1)
- [x] MCP tool presets: core/review/refactor/debug/architecture/full via `ROAM_MCP_PRESET` env var (#3)
- [x] All 61 MCP tool descriptions shortened to <60 tokens each (#5)
- [x] `roam_expand_toolset` meta-tool — lists presets and their tools (#6)
- [x] Compound MCP operations: `roam_explore`, `roam_prepare_change`, `roam_review_change`, `roam_diagnose` — each replaces 2-4 tool calls (#2)
- [x] Structured return schemas (`output_schema`) on all MCP tools — compound + core get custom schemas, rest get envelope default (#4)

---

## v11.0.0 Release Scope (3-4 weeks)

The items marked **[v11]** below ship together as a single release.
Goal: fix MCP crisis + close CI gap + launch to the world.

**What v11 achieves:**
- MCP token overhead: 36K → <3K tokens (core preset) — **92% reduction**
- Agent tool calls: 60-70% fewer (compound operations)
- MCP speed: 10-100x faster (in-process calls)
- Search: 5-10s → <10ms (FTS5/BM25) — **1000x faster**
- Incremental indexing: O(N) → O(changed) — correctness fix
- GitHub Action: SARIF + PR comments + quality gates
- Show HN launch with demo GIF, CHANGELOG, CONTRIBUTING

---

## Epic 1: MCP v2 Overhaul

> WHY: Agents with 50+ tools achieve 60% task success; with 5-7 tools = 92%.
> Our 61 tools at ~36K tokens is actively hurting agent performance.
> CKB's advantage is presets + compounds, not tool count.

| # | Item | Effort | v11? | Depends On | Status |
|---|------|--------|------|------------|--------|
| 1 | **[v11]** Replace subprocess MCP with in-process Python calls | 3d | YES | — | **DONE** |
| 2 | **[v11]** Compound MCP operations: `roam_explore`, `roam_prepare_change`, `roam_review_change`, `roam_diagnose` | 3-4d | YES | #1 | **DONE** |
| 3 | **[v11]** MCP tool presets: core (16), review (27), refactor (26), debug (27), architecture (29), full | 2-3d | YES | #1 | **DONE** |
| 4 | **[v11]** Structured return schemas on all MCP tool descriptions | 1-2d | YES | #3 | **DONE** |
| 5 | **[v11]** Shorten all tool descriptions to <60 tokens each | 1d | YES | #3 | **DONE** |
| 6 | **[v11]** `roam_expand_toolset` meta-tool for dynamic mid-session preset switching | 2-3d | YES | #3 | **DONE** |
| 7 | Batch MCP operations: `batchSearch` (10 queries), `batchGet` (50 symbols) | 2-3d | no | #1 | |
| 8 | MCP streaming Resources + async Tasks (Nov 2025 spec) | 2d | no | #1 |
| 9 | Universal `--budget N` token-cap flag on all commands | 2d | no | — |
| 10 | Universal progressive disclosure (summary + `--detail` flag) | 2-3d | no | — |

**Epic outcome:** Token overhead drops from ~36K to ~3K. Agent success rate jumps from ~60% to ~92%.

---

## Epic 2: Performance Foundations

> WHY: Incremental indexer has O(N) correctness bug. Search is 1000x slower than it should be.

| # | Item | Effort | v11? | Depends On | Status |
|---|------|--------|------|------------|--------|
| 11 | **[v11]** `PRAGMA mmap_size = 268435456` in connection.py | 1h | YES | — | **DONE** |
| 12 | **[v11]** Size guard on `propagation_cost()` in cycles.py (>500 nodes) | 1h | YES | — | **DONE** |
| 13 | **[v11]** Fix incremental edge rebuild: store per-file ref index, O(N) → O(changed) | 2-3d | YES | — | **DONE** |
| 14 | **[v11]** Replace TF-IDF with SQLite FTS5/BM25 (zero new deps) | 1-2d | YES | — | **DONE** |
| 15 | DB Sprint: add 5 missing indexes, remove 1 redundant, UPSERT pattern, batch size 500+ | 1d | no | — | **DONE** |
| 16 | Fix cycle detection to use SCC data instead of 2-cycle self-join | 3-5h | no | — | |
| 17 | Consolidate duplicated EXTENSION_MAP + schema definitions | 2h | no | — | |
| 18 | Replace bare `except` clauses with logged exception handling | 1h | no | — | |

**Epic outcome:** Everything feels instant. Correctness bugs fixed.

---

## Epic 3: CI/CD Integration

> WHY: #1 competitive gap. Every SAST tool (CodeQL, SonarQube, Semgrep, CodeScene) has CI.
> Composite action = no Docker overhead, sub-60s PR analysis, zero API keys.

| # | Item | Effort | v11? | Depends On |
|---|------|--------|------|------------|
| 19 | **[v11]** Standardized exit codes for error categories | 4-8h | YES | — |
| 20 | **[v11]** GitHub Action: composite action, SARIF upload, sticky PR comment, quality gate, SQLite cache | 2-3d | YES | #19 |
| 21 | `.pre-commit-hooks.yaml` for pre-commit framework | 1d | no | — |
| 22 | Docker image (alpine-based) | 1d | no | — |
| 23 | Inline PR comment posting via `gh` CLI | 3d | no | #20 |

**Epic outcome:** roam-code runs in CI on every PR. SARIF results in GitHub Code Scanning.

---

## Epic 4: Launch Readiness

> WHY: Must ship BEFORE Show HN. A maintained-looking repo gets 3-5x more stars.
> 34.2% of developers cite docs as #1 trust signal.

| # | Item | Effort | v11? | Depends On |
|---|------|--------|------|------------|
| 24 | **[v11]** Add GitHub repo topics (cli, static-analysis, mcp, etc.) | 10m | YES | — |
| 25 | **[v11]** Fix command count inconsistency (94 vs 95) | 10m | YES | — |
| 26 | **[v11]** Terminal demo GIF for README | 4-8h | YES | — |
| 27 | **[v11]** CHANGELOG.md (v11 + retroactive v10.x) | 2-4h | YES | — |
| 28 | **[v11]** CONTRIBUTING.md + issue/PR templates | 4-8h | YES | — |
| 29 | **[v11]** Enable GitHub Discussions | 30m | YES | — |
| 30 | **[v11]** Progress indicator during `roam init` / `roam index` | 2-4h | YES | — |

**Epic outcome:** Repo looks maintained, professional, ready for public attention.

---

## Epic 5: Growth Campaign

> WHY: 286 stars → 2000 in 90 days. Aider grew via benchmarks + Show HN.
> MCP directory listings = free distribution to 5800+ servers.

| # | Item | Effort | v11? | Depends On |
|---|------|--------|------|------------|
| 31 | **[v11]** List on MCP directories (mcp.so, PulseMCP, mcpservers.org, Smithery) | 2h | YES | Epic 1 |
| 32 | **[v11]** Show HN launch | 1h + engagement | YES | Epic 4 |
| 33 | Integration tutorials for Claude Code, Cursor, Gemini CLI | 2-3d | no | Epic 1 |
| 34 | Blog post: agent efficiency benchmarks (token savings) | 2-3d | no | Epic 1 |
| 35 | Codebase comprehension benchmark (Aider leaderboard model) | 3-5d | no | — |
| 36 | Partner outreach to Claude Code, Codex CLI, Gemini CLI teams | ongoing | no | Epic 1 |
| 37 | Benchmarks on major OSS repos (Linux kernel, React, Django) | 2-3d | no | — |

**Epic outcome:** roam-code visible on 6+ discovery channels. 200-2000 stars from Show HN.

---

## Epic 6: Ownership & Team Intelligence

> WHY: No CLI tool fuses CODEOWNERS with git blame. CKB + CodeScene own this space.
> roam-code has the graph data to do it better — 100% locally.

| # | Item | Effort | v11? | Depends On |
|---|------|--------|------|------------|
| 38 | CODEOWNERS parser + `roam codeowners` command (coverage, top owners, unowned files) | 3-4d | no | — |
| 39 | Ownership drift detection: `roam drift` (declared vs actual from time-decayed blame) | 2-3d | no | #38 |
| 40 | Knowledge loss simulation: `roam simulate-departure` (what breaks if dev X leaves?) | 3-4d | no | #38 |
| 41 | Reviewer suggestion: `roam suggest-reviewers` (multi-signal scoring) | 2-3d | no | #38, #39 |

**Epic outcome:** CodeScene-level team intelligence, 100% local, zero cost.

---

## Epic 7: Change Intelligence

> WHY: Breaking API detection = CKB exclusive we can beat with AST diff.
> Test gap analysis extends our existing test convention detection.

| # | Item | Effort | v11? | Depends On |
|---|------|--------|------|------------|
| 42 | Breaking API change detection: compare symbol signatures pre/post commit | 3-5d | no | — |
| 43 | Test gap analysis: map changed symbols to missing test coverage | 2-3d | no | — |
| 44 | Secret scanning (regex patterns for API keys, tokens, passwords) | 3-4d | no | — |

**Epic outcome:** PR review gets breaking change alerts + test gap warnings + secret leak detection.

---

## Epic 8: CLI DX Overhaul

> WHY: DX score 5.9/10. 94 commands = cognitive overload.
> Error experience is the #1 retention driver after first run.

| # | Item | Effort | v11? | Depends On |
|---|------|--------|------|------------|
| 45 | Next-step suggestions in key command output | 4-8h | no | — |
| 46 | Fuzzy command matching with typo suggestions | 4-8h | no | — |
| 47 | Usage examples in every command help text | 1-2d | no | — |
| 48 | `roam doctor` setup diagnostics command | 4-8h | no | — |
| 49 | "5 core commands" framing in `--help` output | 1-2h | no | — |
| 50 | Remediation steps in error messages | 4-8h | no | — |
| 51 | Consistent "symbol not found" handling across commands | 4-8h | no | — |
| 52 | `roam reset`/`roam clean` for index management | 2-4h | no | — |
| 53 | Windows PATH issue auto-detection | 2-4h | no | — |

**Epic outcome:** roam-code feels polished, helpful, and approachable.

---

## Epic 9: Search v2

> WHY: squirrelsoft has BM25+ONNX hybrid. After FTS5 ships in v11, upgrade path is clear.

| # | Item | Effort | v11? | Depends On |
|---|------|--------|------|------------|
| 54 | Hybrid BM25 + vector search with Reciprocal Rank Fusion | 1-2w | no | #14 |
| 55 | Search score explanation (`--explain` flag) | 2-3d | no | #14 |
| 56 | Local ONNX Runtime embedding model (optional dependency) | 2w | no | #54 |

**Epic outcome:** Best-in-class local code search. Beats squirrelsoft at their own game.

---

## Epic 10: AI Debt & Architecture Guardian

> WHY: 75% of companies face moderate-to-severe tech debt in 2026, largely from AI code.
> The "10x feature": shift from snapshot tool to continuous infrastructure layer.

| # | Item | Effort | v11? | Depends On |
|---|------|--------|------|------------|
| 57 | Vibe Code Auditor: detect AI-generated code rot (duplicated patterns, hallucinated imports, abandoned stubs, inconsistent error handling) | 2-3d | no | — |
| 58 | Continuous Architecture Guardian: daemon/Action monitoring codebase trends, drift detection, prescriptive fixes | 2-3w | no | #20 |

**Epic outcome:** roam-code becomes "the codebase X-ray that catches what AI coding misses."

---

## Epic 11: Platform Expansion

> WHY: These are high-value but depend on earlier epics being stable.

| # | Item | Effort | v11? | Depends On |
|---|------|--------|------|------------|
| 59 | Dedicated docs site (Starlight/MkDocs) | 1-2w | no | Epic 4 |
| 60 | File watcher mode (`roam watch`) with debouncing | 2-3d | no | — |
| 61 | Git hook auto-indexing (post-merge, post-checkout, post-rewrite) | 1-2d | no | — |
| 62 | VS Code extension (LSP-based) | 2-3w | no | Epic 1 |
| 63 | Kotlin upgrade to Tier 1 | 3d | no | — |
| 64 | Swift upgrade to Tier 1 | 3d | no | — |
| 65 | Auto-generate CLAUDE.md from roam index | 2-3d | no | — |

**Epic outcome:** roam-code available in more contexts: IDEs, CI, file watch, more languages.

---

## Someday/Maybe (park, revisit quarterly)

These were evaluated and deliberately deferred. Not killed — just not now.

| Item | Why Deferred |
|------|-------------|
| SBOM generation (CycloneDX/SPDX) | Enterprise feature; not core value; 2-week effort |
| Taint/data flow analysis | CodeQL/Semgrep years ahead; 2-week effort for inferior result |
| Multi-repo federation | Enterprise need; CKB owns this; massive scope |
| Near-duplicate code detector | SonarQube does it better; not differentiator |
| ADR intelligence | Niche; no user demand signal |
| Monorepo analysis (Nx/Turborepo/Bazel) | Wait for user demand |
| Web UI for graph exploration | High effort, low ROI vs CLI/MCP |
| Agent session management | Serena has memories; agents handle this themselves |
| Cost-of-change in dollars | CodeScene premium feature; hard to get right |
| Developer congestion metrics | Interesting but niche |
| Doc-symbol linking | CKB feature; no user asked for it |
| rustworkx replacement | Premature; NetworkX fine up to 50k nodes |
| Named snapshot save/diff | Niche; fingerprinting already exists |
| Color output with NO_COLOR support | Polish; low impact |
| Compact JSON for pipes | Edge case |
| All language additions (Zig, Dart, Elixir, Scala, Gleam, Lua, R, Mojo) | Demand-driven; community can contribute |
| All framework extractors (React, Django, Spring, Rails, Terraform) | Same — wait for demand |
| All CI platforms beyond GitHub (GitLab, Azure, Bitbucket, CircleCI, Jenkins, Helm) | GitHub first; expand on demand |
| JetBrains plugin | After VS Code proves the model |
| SLSA provenance + Sigstore | Enterprise hardening; later |

---

## Killed Items (47+ permanently removed)

Evaluated across 7 reports. Grouped by reason:

**Wrong layer / not our job (6):**
- AI hallucinated-reference detector — agents handle this themselves
- AI-generated code pattern detector — replaced by Vibe Code Auditor (#57)
- Rollback guidance for agents — agents have their own undo
- Agent session management — agents manage their own sessions
- Interactive `roam init` — unnecessary ceremony; `roam init` should just work
- Command namespace consolidation — too disruptive for 0 user complaints

**Not a product feature (7):**
- Counter-messaging for context windows — strategy doc, not code
- Recruit maintainers — outcome of growth, not a backlog item
- Multiple positioning content pieces — do one well, not five
- Air-gapped landing page — niche; no signal
- Evaluate CLI rename from `roam` — disruption > benefit
- Video content creation — text-first community; video later
- Product Hunt launch — after Show HN proves messaging

**Premature / too early (5):**
- Web playground/hosted demo — no demand; massive effort
- Rust/Go binary distribution — Python + pipx is fine
- Shared fitness functions community hub — no community yet
- Salesforce/Apex case studies — too niche
- VFP legacy case studies — too niche

**Low-value polish (5):**
- Color output with NO_COLOR — minimal impact
- Compact JSON for pipes — edge case
- Document alias commands — nobody asked
- Subcommand consistency — internal housekeeping
- Validate empty command arguments — defensive; low impact

**Absorbed into someday/maybe bundles (24+):**
- 8 language additions (Zig, Dart, Elixir, Scala, Gleam, Lua, R, Mojo) — demand-driven
- 5 framework extractors (React, Django, Spring, Rails, Terraform) — demand-driven
- 6 CI platforms (GitLab, Azure, Bitbucket, CircleCI, Jenkins, Helm) — GitHub first
- JetBrains plugin — after VS Code
- Multi-repo federation — enterprise; CKB territory
- SLSA provenance — enterprise hardening
- Parallelize file processing — premature optimization
- `schema_meta` table — over-engineering for now

---

## Summary Stats

| Metric | v2 Backlog | v3 Backlog | Change |
|--------|-----------|-----------|--------|
| Total active items | 139 | **54** (65 - 11 done) | -61% |
| Epics | 0 | **11** | structured |
| v11 scope | undefined | **21 items, 10 remaining** | 11/21 done (52%) |
| Someday/Maybe | 0 | **20 (30+ expanded)** | parked cleanly |
| Killed | 0 | **47+** | ruthless focus |
| P0-equivalent (v11) | 14 scattered | **21 coherent** | sequenced |
| Completed | — | **11 (Epic 2 done + Epic 1: 6/10)** | Track A+B |

---

## Quick-Win Chains (compound impact)

### Chain A: Launch Prep Sprint (1 day)
```
#24 topics (10m) → #25 cmd count (10m) → #29 Discussions (30m)
→ #27 CHANGELOG (2h) → #28 CONTRIBUTING (4h) → #26 GIF (4h)
```
**Result:** Side project → maintained open-source tool overnight.

### Chain B: DB Speed Sprint (0.5 day) — DONE
```
#11 mmap (1h) → #12 propagation guard (1h) → #15 indexes + UPSERT + batch (4h)
+ #13 O(changed) incremental fix + #14 FTS5/BM25
```
**Result:** Everything feels snappier; pairs with FTS5. **Shipped in commit 8cdad19.**

### Chain C: Discoverability Blitz (2h)
```
#24 topics (10m) → #31 MCP directories (2h)
```
**Result:** 6+ discovery channels; free organic traffic.

### Chain D: MCP Token Emergency (0.5 day)
```
#5 shorten descriptions (3h) → #3 presets (after #1) → #6 expand_toolset (3h)
```
**Result:** 36K tokens → <3K immediately.

### Chain E: Error Experience (1 day)
```
#19 exit codes (4h) → #50 remediation (4h) → #51 symbol-not-found (4h)
```
**Result:** Helpful errors → retention after first run.

---

## Critical Path Dependencies

```
Epic 1 (MCP v2):     #1 → #2 → #3 → #4,#5,#6 → #31 (MCP listings)
Epic 3 (CI/CD):      #19 → #20 → #23
Epic 4 (Launch):     #24-30 all parallel → #32 (Show HN LAST)
Epic 5 (Growth):     Epic 4 + Epic 1 → #32 → #33,#34,#35
Epic 6 (Ownership):  #38 → #39 → #40,#41
Epic 9 (Search v2):  #14 → #54 → #56
```

**v11 two-track execution plan:**
```
TRACK A (critical path, ~10 days):
  #1 in-process MCP ← DONE + #3 presets ← DONE + #5 descriptions ← DONE + #6 expand_toolset ← DONE
  → #2 compound ops ← DONE → #4 schemas ← DONE
  → #31 MCP listings (2h) → #32 Show HN (1h)

TRACK B (parallel, ~8 days):
  Week 1: #11 mmap + #12 guard + #13 incremental fix + #14 FTS5 + #15 DB sprint ← ALL DONE (8cdad19)
  Week 2: #19 exit codes (4-8h) → #20 GitHub Action (2-3d)
  Anytime: #24-30 Launch Prep (2 days total, all parallel)
```
Both tracks complete in ~3 weeks. Week 4 is buffer + Show HN launch.

---

## Positioning

**Current:** "Instant codebase comprehension for AI coding agents"

**Recommended:** "The codebase X-ray that catches what AI coding misses"

**Alternative (agent-focused):** "The computation layer AI agents cannot replicate by reading files"

**Why:** Addresses the 2026 vibe coding debt crisis. Works for both agent and human users. Positions computation (PageRank, Tarjan, entropy) as the durable moat that survives context window growth to 10M+ tokens.

---

*Source: 14 reports in reports/ directory (01-14)*
*Competitor data: 16 audit reports + 7 verification passes in reports/competitors/*
*Competitive score: 87/108 (nearest: SonarQube 46, CodeQL 43)*
