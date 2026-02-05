# PROJECT SCOPE: `ai`

## Product Vision
- Deliver a Codex-inspired, terminal-first companion that analyzes repositories, answers follow-up questions, and proposes file rewrites with transparent diffs and human approval loops. [`main.py`](main.py) [`README.md`](README.md)
- Keep every interaction auditable by surfacing directory listings, context excerpts, tool calls, and write confirmations directly in the CLI session. [`main.py`](main.py)

## Key Personas & Scenarios
1. **Hands-on developers** looking for rapid repository reconnaissance and iterative Q&A without leaving the shell. [`README.md`](README.md)
2. **Security-conscious operators** who demand sandboxed command execution, scoped file access, and explicit confirmation before edits land. [`bash_executor.py`](bash_executor.py) [`main.py`](main.py)
3. **Release and platform engineers** responsible for packaging the standalone binary, distributing upgrades, and tracking semantic versions. [`install.sh`](install.sh) [`_version.py`](_version.py)

## Core Pillars
- **Repository-aware conversations** – Gather directory listings plus up to eight relevant files to seed prompts and keep discussions grounded in source truth. [`contextualizer.py`](contextualizer.py) [`main.py`](main.py)
- **Guided file rewrites** – When scoped to a file, request full replacements from the edit model, display numbered diffs, and persist changes only after user approval. [`main.py`](main.py)
- **Sandboxed automation** – Validate commands against disallowed substrings and path escapes before running them with strict timeout and output ceilings. [`bash_executor.py`](bash_executor.py) [`main.py`](main.py)
- **Distribution & upgrades** – Provide a curl-able installer, manage PATH shims, expose `ai -v`/`ai -u`, and keep `_version.py` in sync during tagged releases. [`install.sh`](install.sh) [`main.py`](main.py) [`_version.py`](_version.py)

## Architecture Overview
- **CLI Orchestrator (`main.py`)** – Parses arguments, resolves scopes, loads configuration, orchestrates OpenAI Responses sessions, streams model output, manages tool calls (`read_file`, `write`, `shell`, `update_plan`), renders diffs, and cleans up temporary chat history files. [`main.py`](main.py)
- **Context Engine (`contextualizer.py`)** – Prioritizes interesting project files, enforces byte/line limits, detects binary assets, and formats prompt/display blocks for repository snapshots. [`contextualizer.py`](contextualizer.py)
- **Sandboxed Bash Runtime (`bash_executor.py`)** – Defines disallowed command substrings, rejects absolute/parent path usage, executes approved commands under deterministic locale settings, truncates oversized output, and normalizes formatted transcripts. [`bash_executor.py`](bash_executor.py)
- **Configuration Subsystem (`config_loader.py`, `config_paths.py`)** – Resolves XDG-compliant config paths, merges JSON defaults with environment overrides, and exposes model/system prompt/bash limit settings. [`config_loader.py`](config_loader.py) [`config_paths.py`](config_paths.py)
- **Distribution Assets (`install.sh`, `_version.py`)** – Package and install the PyInstaller bundle, manage local upgrades, and surface the runtime version string for `ai -v`. [`install.sh`](install.sh) [`_version.py`](_version.py)
- **Quality & Regression Tests (`tests/test_contextualizer.py`)** – Exercise context slicing behaviors to ensure offsets, truncation flags, and prompt formatting remain stable. [`tests/test_contextualizer.py`](tests/test_contextualizer.py)

## Operational Workflows
1. **Repository conversation**
   - Parse CLI args, resolve scope, and gather context files with byte/line safeguards. [`main.py`](main.py) [`contextualizer.py`](contextualizer.py)
   - Start an OpenAI Responses session seeded with tool definitions; process reasoning, tool calls, and assistant messages. [`main.py`](main.py)
   - Execute requested tools and echo their outputs, keeping the user in the approval loop. [`main.py`](main.py)
2. **File edit session**
   - Load the targeted file (or empty content), call the edit model for a full rewrite, strip code fences, and render numbered diffs. [`main.py`](main.py)
   - Confirm before writing, normalize newline termination, and set standard permissions. [`main.py`](main.py)
3. **Sandboxed bash command**
   - Reject dangerous commands up front, then run approved ones with configured timeout/output ceilings and formatted transcripts. [`bash_executor.py`](bash_executor.py) [`main.py`](main.py)
4. **Install & upgrade flow**
   - Fetch the hosted installer (or supplied bundle), hydrate the app under `~/.ai`, manage PATH shims, and update versions during tagged releases. [`install.sh`](install.sh) [`README.md`](README.md) [`_version.py`](_version.py)

## Configuration & Extensibility
- Defaults cover model selection, system prompts, and bash/context limits; users can override via `~/.config/ai/config.json` or environment variables such as `OPENAI_API_KEY`, `AI_MODEL*`, and `AI_BASH_MAX_*`. [`config_loader.py`](config_loader.py) [`README.md`](README.md)
- ANSI color and system instruction tweaks adapt terminal presentation without source changes (`AI_COLOR`, `AI_SYSTEM_PROMPT`). [`config_loader.py`](config_loader.py) [`main.py`](main.py)
- Context window controls (`read_limit`, `max_bytes`) can be tuned per repo or CI environment, ensuring predictable prompt budgets. [`config_loader.py`](config_loader.py) [`contextualizer.py`](contextualizer.py)

## Security & Guardrails
- Reject writes outside the repository root, require explicit confirmation (unless auto-applied by directive), and clean up temporary history files on exit. [`main.py`](main.py)
- Enforce sandboxed command rules, blocking disallowed substrings, path escapes, and invalid working directories before execution. [`bash_executor.py`](bash_executor.py)
- Surface line-numbered diffs and explicit tool-call transcripts so operators can audit every mutation. [`main.py`](main.py)

## Dependencies & Tooling
- Relies on the official `openai>=1.0.0` SDK for Responses and Chat Completions. [`requirements.txt`](requirements.txt) [`main.py`](main.py)
- Assumes local availability of `curl`, `bash`, and `tar` for installation and upgrade automation. [`install.sh`](install.sh) [`README.md`](README.md)

## Testing & Quality
- Pytest coverage currently focuses on context window behavior; expanding tests across diff rendering, CLI parsing, and sandbox enforcement would boost confidence. [`tests/test_contextualizer.py`](tests/test_contextualizer.py) [`main.py`](main.py)

## Known Gaps & Future Opportunities
- Broaden automated testing around tool-call orchestration, diff approval pathways, and bash command rejection to reduce regressions. [`main.py`](main.py) [`bash_executor.py`](bash_executor.py)
- Refine context heuristics to prioritize CI definitions, lockfiles, or repo-specific hot spots. [`contextualizer.py`](contextualizer.py)
- Clarify or relocate plotting utilities currently living in `test_funcs.py` to avoid confusion with production code. [`test_funcs.py`](test_funcs.py)
