# PROJECT SCOPE: `ai`

## Product Vision & Value Proposition
- Ship a terminal-first, Codex-inspired teammate that inspects repositories, streams reasoning, and delivers auditable file rewrites from a single binary. [`main.py`](main.py) [`README.md`](README.md)
- Emphasize transparency and operator control by surfacing context gathering, tool calls, and diff approvals directly in the CLI. [`main.py`](main.py)
- Offer easy onboarding through a curl-installable bundle, stable version semantics, and upgrade ergonomics suitable for individual developers and platform teams. [`install.sh`](install.sh) [`_version.py`](_version.py)

## Primary Personas & Scenarios
1. **Shell-native developers** seeking rapid repo reconnaissance, ad-hoc Q&A, and iterative refactors without leaving the terminal. [`README.md`](README.md)
2. **Security-conscious operators** who demand sandboxed command execution, scoped file access, and explicit confirmation before writes are committed. [`main.py`](main.py) [`bash_executor.py`](bash_executor.py)
3. **Release and DevOps engineers** responsible for packaging, distributing, and upgrading the binary across fleets while tracking semantic versions. [`install.sh`](install.sh) [`_version.py`](_version.py)

## Core Capabilities
- **Repository-aware conversations** – Automatically assemble directory listings and up to eight high-signal source files to ground prompts in the current checkout. [`contextualizer.py`](contextualizer.py) [`main.py`](main.py)
- **Scoped editing workflow** – When focused on a file, request full replacements from the edit model, render numbered diffs, and require user confirmation before persisting changes. [`main.py`](main.py)
- **Explicit tool orchestration** – Expose `read_file`, `write`, `shell`, and `update_plan` tooling to the model, printing every invocation for user review. [`main.py`](main.py)
- **Sandboxed automation** – Enforce command allowlists, reject absolute or parent paths, cap runtime/output, and format transcripts for bash-mode tasks. [`bash_executor.py`](bash_executor.py)
- **Interactive follow-ups** – Maintain conversation state, stream assistant output with colorized loaders, and collect additional instructions after each response. [`main.py`](main.py)

## Architecture Overview
| Component | Responsibility | References |
| --- | --- | --- |
| CLI Orchestrator | Parses arguments, resolves scopes, orchestrates Responses sessions, manages tool calls, renders diffs, and cleans up temp chat buffers. | [`main.py`](main.py)
| Context Engine | Detects binary assets, applies byte/line guards, prioritizes interesting files, and formats prompt/display payloads. | [`contextualizer.py`](contextualizer.py)
| Configuration Subsystem | Resolves XDG paths, hydrates defaults, and applies env overrides for models, prompts, and bash/context limits. | [`config_loader.py`](config_loader.py) [`config_paths.py`](config_paths.py)
| Sandboxed Bash Runtime | Validates commands, executes within repo scope, enforces limits, and normalizes results for display. | [`bash_executor.py`](bash_executor.py)
| Distribution Assets | Install/upgrade scripts, PATH shims, and runtime version metadata for `ai -v` and release automation. | [`install.sh`](install.sh) [`_version.py`](_version.py)

## Operational Workflows
1. **Repository conversation** – Parse CLI arguments, gather scoped context, launch an OpenAI Responses session with tool definitions, execute any requested tools, then prompt for follow-up instructions. [`main.py`](main.py) [`contextualizer.py`](contextualizer.py)
2. **File edit session** – Load target snapshot, call the edit model for full-content rewrites, strip code fences, show diffs, and write on approval (auto-applying when the instruction explicitly demands a write). [`main.py`](main.py)
3. **Sandboxed bash command** – Reject unsafe commands up front, run approved ones under deterministic locales/timeouts, truncate oversized output, and echo transcripts. [`bash_executor.py`](bash_executor.py)
4. **Installation & upgrades** – Fetch tagged or latest releases, unpack into `~/.ai`, manage PATH shims, and skip reinstalls when versions already match. [`install.sh`](install.sh) [`README.md`](README.md)

## Configuration & Extensibility
- Defaults cover model selection, system prompts, and bash/context limits while still honoring environment overrides such as `OPENAI_API_KEY`, `AI_MODEL*`, `AI_BASH_MAX_*`, and `AI_CONTEXT_*`. [`config_loader.py`](config_loader.py) [`README.md`](README.md)
- Config files live at the XDG-compliant path `~/.config/ai/config.json`, created on demand when ensuring directories exist. [`config_loader.py`](config_loader.py) [`config_paths.py`](config_paths.py)
- ANSI color and custom system instructions enable per-user personalization without editing source. [`config_loader.py`](config_loader.py) [`main.py`](main.py)

## Security & Guardrails
- Reject file mutations outside the repository root, normalize newline termination, and require approval before writes unless the instruction implies automation. [`main.py`](main.py)
- Log every tool invocation, including command transcripts, so operators can audit the session end-to-end. [`main.py`](main.py)
- Deny dangerous shell commands (e.g., `rm`, `sudo`, absolute paths), enforce timeouts, and cap captured output to prevent runaway processes. [`bash_executor.py`](bash_executor.py)
- Clean up temporary Vim/chat history files and trap interrupts for graceful exits. [`main.py`](main.py)

## Distribution & Release Management
- PyInstaller bundles ship as `ai-linux-x64.tar.gz`; the installer fetches tagged assets or reuses local binaries and installs shims under `~/.ai/bin`. [`install.sh`](install.sh)
- `_version.py` provides the runtime version string, overwritten during tagged GitHub Actions builds, ensuring `ai -v` reflects released artifacts. [`_version.py`](_version.py) [`README.md`](README.md)
- Dependencies are minimal, relying primarily on `openai>=1.0.0` for Responses/chat APIs. [`requirements.txt`](requirements.txt)

## Quality & Testing
- Pytest coverage currently targets context-window behavior, validating offsets, truncation flags, and prompt formatting. [`tests/test_contextualizer.py`](tests/test_contextualizer.py)
- The repository includes a standalone plotting helper unrelated to CLI behavior, highlighting the need to separate experimental scripts from production code. [`test_funcs.py`](test_funcs.py)

## Known Gaps & Future Opportunities
- Expand automated testing across CLI argument parsing, diff rendering, shell rejection paths, and tool-call orchestration for higher confidence. [`main.py`](main.py) [`bash_executor.py`](bash_executor.py)
- Broaden context heuristics to account for repo-specific hotspots (CI configs, lockfiles, docs) and allow manual pinning of critical files. [`contextualizer.py`](contextualizer.py)
- Harden release automation by validating installer checksums and extending support beyond Linux x86_64. [`install.sh`](install.sh)
- Rehome or document auxiliary plotting scripts to avoid confusion with supported workflows. [`test_funcs.py`](test_funcs.py)
