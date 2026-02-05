# Project Scope: `ai` CLI Companion

## 1. Mission Statement
- Deliver a local-first terminal assistant that pairs OpenAI reasoning with repository-aware tooling so developers can explore, edit, and audit codebases without leaving the shell. ([README.md](README.md), [main.py](main.py))
- Preserve user control by surfacing every automated action—plans, tool calls, diffs, and confirmations—directly in the interactive session. ([main.py](main.py))
- Keep distribution friction low via a single downloadable bundle, configurable defaults, and a self-upgrade path. ([README.md](README.md), [install.sh](install.sh))

## 2. Product Principles
- **Observable operations** – Stream responses, display numbered diffs before any write, and log tool usage so operators can intervene at each step. ([main.py](main.py))
- **Reproducible context** – Harvest repository snippets deterministically based on configured byte and line limits, ensuring consistent prompts across runs. ([contextualizer.py](contextualizer.py), [config_loader.py](config_loader.py))
- **Minimal footprint** – Depend on the OpenAI Python client plus standard library functionality; keep binaries portable through PyInstaller packaging. ([requirements.txt](requirements.txt), [README.md](README.md))

## 3. Primary Workflows
| Flow | Invocation Example | Description | Key Sources | | --- | --- | --- |
--- | | Interactive conversation | `ai` | Analyze the current repository,
stream answers, accept iterative `QR >` prompts, and support buffered
`!command` shell execution whose output is injected with your next instruction.
| [README.md](README.md), [main.py](main.py) | | Prompt-only run | `ai "how do
I write a release workflow?"` | Execute a single inference without entering
follow-up mode. | [README.md](README.md), [main.py](main.py) | | File rewrite
mode | `ai path/to/file.py "replace legacy API usage"` | Request a full-file
rewrite through the edit model, review the unified diff with line numbers, and
approve or reject changes. | [README.md](README.md), [main.py](main.py) | |
Scoped conversation | `ai docs/architecture "summarize these docs"` | Limit
context harvesting to a directory while running the conversation loop. |
[README.md](README.md), [contextualizer.py](contextualizer.py),
[main.py](main.py) | | Read-only preview | `ai --read path/to/file.py --offset
400 --limit 200` | Display bounded file slices with continuation hints. |
[README.md](README.md), [contextualizer.py](contextualizer.py),
[main.py](main.py) | | Sandboxed bash | Tool-assisted `shell` calls | Execute
guarded shell commands with time, byte, and scope restrictions from within a
session. | [bash_executor.py](bash_executor.py), [main.py](main.py) | | Self-
upgrade | `ai -u` | Fetch and reinstall the latest tagged release using the
hosted installer script. | [README.md](README.md), [main.py](main.py),
[install.sh](install.sh) |

## 4. Architectural Components
- **CLI entrypoint** – Minimal launcher that hands off to the orchestrator. ([main.py](main.py))
- **Orchestrator** – Bridges configuration, renderer selection, argument parsing, and engine execution so alternate UIs can share the same flow. ([orchestrator.py](orchestrator.py))
- **AI engine** – Core orchestration layer that gathers context, manages the Responses loop, dispatches tools, and applies mutations via the injected renderer. ([ai_engine.py](ai_engine.py))
- **Context harvesting** – Collects representative file snippets, enforces byte/line caps, and formats content for prompt injection. ([contextualizer.py](contextualizer.py))
- **Sandboxed execution layer** – Validates bash commands against disallowed patterns, enforces repo-relative execution, and truncates oversized output. ([bash_executor.py](bash_executor.py))
- **Configuration loader** – Resolves XDG-aware config files, merges defaults, and applies environment overrides for the shared model, bash settings, and context limits. ([config_loader.py](config_loader.py), [config_paths.py](config_paths.py))
- **Version metadata** – Provides the runtime semantic version string for CLI reporting and release automation. ([_version.py](_version.py))
- **Distribution tooling** – Shell installer fetches tagged PyInstaller bundles, installs shims, and manages upgrades. ([install.sh](install.sh), [README.md](README.md))

## 5. Configuration & Environment
- Default configuration lives at `~/.config/ai/config.json` (honoring `XDG_CONFIG_HOME`) and includes API credentials, a shared model identifier, and context window defaults. ([README.md](README.md), [config_loader.py](config_loader.py), [config_paths.py](config_paths.py))
- Environment variables such as `OPENAI_API_KEY`, `AI_MODEL`, `AI_COLOR`, `AI_BASH_MAX_*`, and `AI_CONTEXT_*` override built-in defaults at runtime. ([README.md](README.md), [config_loader.py](config_loader.py))
- Conversation transcripts are staged in `/tmp/chat_history_*.txt` during interactive sessions and cleaned up on exit. ([main.py](main.py))

## 6. Tooling & Safeguards
- Exposed tools (`read_file`, `write`, `write_file`, `shell`, `update_plan`, `apply_patch`) are defined for the model; write operations always flow through a diff-and-confirm loop unless instructions imply auto-apply. ([main.py](main.py))
- Numbered diffs highlight additions, deletions, and context with ANSI color, ensuring reviewers can spot precise line changes. ([main.py](main.py))
- Generated responses are scanned for fenced code blocks so implicit file proposals still require confirmation. ([main.py](main.py))
- Bash commands are rejected when they reference absolute or parent paths or include disallowed substrings; timeouts and byte caps prevent long-running or noisy commands. ([bash_executor.py](bash_executor.py), [main.py](main.py))
- Task plans can be updated mid-session to track multi-step efforts, reinforcing transparency. ([main.py](main.py))

## 7. Dependencies & Packaging
- Runtime dependency: `openai>=1.0.0`. ([requirements.txt](requirements.txt))
- PyInstaller bundles produce a standalone Linux x86_64 binary (`ai-linux-x64.tar.gz`) distributed through GitHub releases. ([README.md](README.md))
- `install.sh` bootstraps the bundle into `~/.ai`, installs a shim, and manages upgrades or version pinning. ([install.sh](install.sh), [README.md](README.md))
- A utility script (`test_funcs.py`) introduces optional plotting helpers that rely on `numpy` and `matplotlib`, which are not declared as runtime dependencies—treat as non-essential tooling. ([test_funcs.py](test_funcs.py))

## 8. Testing & Quality
- Automated coverage currently targets context slicing behaviors (offset handling, truncation, directory listings). ([tests/test_contextualizer.py](tests/test_contextualizer.py))
- There are no integration tests yet for CLI argument parsing, tool-call orchestration, diff UX, or bash sandbox enforcement—manual verification is required. ([main.py](main.py), [bash_executor.py](bash_executor.py))
- Extra scripts generating plots (`test_funcs.py`) fall outside the formal test suite and should be quarantined or gated if packaged with the binary. ([test_funcs.py](test_funcs.py))

## 9. Release & Distribution Flow
1. Tag the repository with the desired semantic version (e.g., `git tag v0.4.0`) and push the tag to trigger the release workflow. ([README.md](README.md))
2. GitHub Actions builds the PyInstaller artifact, updates `_version.py`, and publishes the bundle alongside the release. ([README.md](README.md), [_version.py](_version.py))
3. Users install or upgrade via `install.sh` (online fetch) or by supplying a pre-downloaded archive with `--binary`. ([README.md](README.md), [install.sh](install.sh))

## 10. Operational Considerations & Limitations
- The CLI requires a valid OpenAI API key provided via config or environment variable; there is no bundled model or offline inference. ([README.md](README.md), [config_loader.py](config_loader.py))
- Prebuilt binaries target Linux x86_64; other platforms must run from source. ([README.md](README.md))
- Bash mode enforces execution inside the repository tree, but users should still review commands for side effects. ([bash_executor.py](bash_executor.py))
- The assistant assumes UTF-8 text files; binary assets are skipped. ([main.py](main.py))

## 11. Future Opportunities
- Expand automated testing to cover CLI entry points, tool execution branches, and sandbox rejection cases. ([main.py](main.py), [bash_executor.py](bash_executor.py))
- Document or extend cross-platform distribution (macOS, Windows/WSL) and explore additional PyInstaller targets. ([README.md](README.md))
- Introduce structured logging or telemetry for enterprise observability of tool calls and file mutations. ([main.py](main.py))
- Modularize tool registration to allow project-specific extensions without editing `main.py`. ([main.py](main.py))

## 12. Out of Scope / Assumptions
- No native support for Windows installers or shells beyond the packaged bash workflow. ([README.md](README.md))
- The project does not manage or store OpenAI credentials beyond reading config/environment values. ([config_loader.py](config_loader.py))
- Destructive shell commands (e.g., `rm`, `sudo`) are blocked by design; users needing elevated operations must run them manually. ([bash_executor.py](bash_executor.py))
- Plot-generation helpers (`test_funcs.py`) are not part of the packaged CLI experience and may be removed or relocated without affecting core functionality. ([test_funcs.py](test_funcs.py))
