# Roam Code

Codebase intelligence for AI coding agents. Pre-indexed symbols, call graphs, dependencies, and architecture -- queried locally, no API keys.

> Forked from [CosmoHac/roam-code](https://github.com/Cranot/roam-code). This fork trims the project to its core mission: giving AI coding agents instant codebase comprehension.

## Install

```bash
pip install roam-code        # CLI only
pip install roam-code[mcp]   # CLI + MCP server for AI agents
```

## Quick Start

```bash
cd /path/to/your/project
roam init                        # one-time index
roam understand                  # full project briefing
roam search AuthService          # find symbols
roam preflight login_handler     # blast radius + tests before changing
roam context login_handler       # minimal files to read
roam diff                        # blast radius of uncommitted changes
roam pr-risk                     # risk score for PR
roam health                      # codebase health score (0-100)
```

For AI agents, enable MCP:

```bash
roam mcp-setup claude-code       # or cursor, windsurf, vscode
```

Run `roam --help` for all 37 commands. Run `roam <command> --help` for details.

## Languages

**Tier 1 (full symbol + call graph):** Python, JavaScript, TypeScript/TSX, Go, Rust, Java, C, C++, C#, PHP, Ruby, Kotlin, Swift

**Tier 2 (symbols + imports):** Scala, Vue, Svelte, YAML, HCL, JSONC, MDX

## License

MIT -- see [LICENSE](LICENSE).
