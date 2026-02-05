# PROJECT SCOPE: `ai`

## Mission & Positioning
- `ai` delivers a Codex-inspired command-line assistant that interrogates repository snapshots, streams model output, and mediates every file mutation through explicit human approval. [`main.py`](main.py) [`README.md`](README.md)
- The tool emphasizes deterministic diffs, auditable tool usage, and minimal setup so engineers can explore and edit projects without leaving the terminal. [`main.py`](main.py) [`README.md`](README.md)

## Primary Audiences
- **Terminal-first engineers** who want rapid repository reconnaissance and interactive Q&A from within their shell sessions. [`README.md`](README.md)
- **Security-conscious maintainers** that require sandboxed shell execution, scoped file access, and reviewable diffs before writes occur. [`main.py`](main.py) [`bash_executor.py`](bash_executor.py)
- **Release and platform teams** responsible for distributing, versioning, and upgrading the standalone bundle across fleets. [`install.sh`](install.sh) [`README.md`](README.md)

## Core Capabilities
### Repository-aware conversations
- Launching `ai` against a directory collects a curated listing plus up to eight high-signal files (README, entry points, manifests, etc.) to seed the model prompt. [`contextualizer.py`](contextualizer.py)
- Conversations stream through the OpenAI Responses API, exposing a toolbox (`read_file`, `write`, `shell`, `update_plan`) that the assistant must call explicitly; results and diffs are echoed to the terminal for auditability. [`main.py`](main.py)

### Guided file rewrites
- Pointing `ai` at a specific file switches to edit mode, where the model returns complete file replacements, code fences are stripped, and numbered color diffs are rendered before applying changes. [`main.py`](main.py)
- Writes normalize permissions, enforce newline termination, and refuse paths outside the repository root to keep edits predictable. [`main.py`](main.py)

### Sandboxed command assistance
- Commands issued via the `shell` tool are validated against disallowed substrings, absolute/parent paths, and scope boundaries before execution; stdout/stderr are truncated to byte ceilings and annotated with exit codes. [`bash_executor.py`](bash_executor.py) [`main.py`](main.py)

### Configuration & personalization
- JSON config is loaded from an XDG-compliant path, merged with environment overrides (`OPENAI_API_KEY`, `AI_MODEL*`, `AI_SYSTEM_PROMPT`, bash limits), and supplied to each run. [`config_loader.py`](config_loader.py) [`config_paths.py`](config_paths.py)
- Model, color, and system-prompt selection fall back to sensible defaults to keep the CLI usable with minimal setup. [`config_loader.py`](config_loader.py) [`main.py`](main.py)

### Installation & upgrades
- `install.sh` bootstraps the PyInstaller bundle, manages PATH shims under `~/.ai`, enforces platform requirements (Linux x86_64), and supports version pinning or local artifact installs. [`install.sh`](install.sh)
- Runtime upgrade commands (`ai -u`) fetch and execute the hosted installer, while `_version.py` exposes the semantic version reported via `ai -v`. [`main.py`](main.py) [`_version.py`](_version.py)

## Architecture Overview
- **CLI Entrypoint (`main.py`)** – Parses arguments, orchestrates conversation/edit loops, renders diffs, enforces plan updates, and mediates tool calls to OpenAI and local helpers. [`main.py`](main.py)
- **Context Provider (`contextualizer.py`)** – Discovers interesting files, applies byte limits, and formats listings for prompt inclusion and on-screen summaries. [`contextualizer.py`](contextualizer.py)
- **Sandboxed Bash Executor (`bash_executor.py`)** – Validates commands, runs them under constrained environments, and returns structured results for the assistant loop. [`bash_executor.py`](bash_executor.py)
- **Configuration subsystem (`config_loader.py`, `config_paths.py`)** – Determines configuration file locations, loads defaults, and merges environment overrides. [`config_loader.py`](config_loader.py) [`config_paths.py`](config_paths.py)
- **Installer & Versioning (`install.sh`, `_version.py`)** – Packages releases and reports runtime versions for distribution flows. [`install.sh`](install.sh) [`_version.py`](_version.py)
- **Ancillary scripts** – `test_funcs.py` contains plotting scaffolding unrelated to the CLI experience and could be relocated or removed. [`test_funcs.py`](test_funcs.py)

## Operational Workflows
1. **Repository conversation**
   - Parse CLI args, resolve scope, and collect context.
   - Initialize an OpenAI Responses session with tool definitions and the system prompt.
   - Stream assistant output, execute requested tools, print results, and loop on `follow_up >>>` prompts. [`main.py`](main.py) [`contextualizer.py`](contextualizer.py)
2. **File edit session**
   - Read existing file contents (or treat as empty), request a full replacement from the configured model, strip code fences, and present a numbered diff before applying with confirmation. [`main.py`](main.py)
3. **Sandboxed bash command**
   - Validate command tokens, enforce scope/time/output ceilings, run in a controlled environment, then emit formatted transcripts back to the assistant. [`bash_executor.py`](bash_executor.py) [`main.py`](main.py)
4. **Upgrade flow**
   - Invoke `install.sh` via `ai -u` or direct script execution, download the desired bundle, install under `~/.ai`, and optionally patch shell PATH entries. [`main.py`](main.py) [`install.sh`](install.sh)

## Safeguards & Guardrails
- Rejects absolute/parent-path writes and refuses to run outside the repository scope, preventing accidental filesystem damage. [`main.py`](main.py) [`bash_executor.py`](bash_executor.py)
- Requires user confirmation (unless auto-applied by explicit write instructions) before writing files or applying patches, ensuring human-in-the-loop changes. [`main.py`](main.py)
- Maintains chat transcripts in `/tmp`, intercepts `Ctrl+C` for cleanup, and normalizes terminal color usage based on TTY detection. [`main.py`](main.py)

## External Dependencies & Interfaces
- Depends on the official `openai>=1.0.0` SDK and assumes availability of `curl`, `bash`, and `tar` for installation/upgrade paths. [`requirements.txt`](requirements.txt) [`main.py`](main.py) [`install.sh`](install.sh)
- Respects environment variables for credentials, model selection, color preferences, and bash limits to integrate with CI and developer workflows. [`config_loader.py`](config_loader.py) [`main.py`](main.py)

## Out of Scope & Future Opportunities
- Automated tests are minimal; expanding coverage for diff rendering, sandbox enforcement, and CLI parsing would increase confidence. [`main.py`](main.py) [`bash_executor.py`](bash_executor.py)
- Context heuristics could consider CI workflows, lockfiles, or larger file sets to improve prompt fidelity. [`contextualizer.py`](contextualizer.py)
- Clarify the role of `test_funcs.py` or migrate it to dedicated examples/tests to avoid confusion with production code. [`test_funcs.py`](test_funcs.py)
