# PROJECT SCOPE: `ai`

## Mission & Value Proposition
- Deliver a Codex-inspired, terminal-first assistant that can summarize repositories, answer follow-up questions, and author file rewrites without leaving the command line. [`main.py`](main.py) [`README.md`](README.md)
- Emphasize transparent execution: every command, diff, and write is surfaced for human approval, keeping repository explorations auditable and low-risk. [`main.py`](main.py)

## Target Users & Primary Scenarios
1. **Hands-on developers** who want quick repository reconnaissance and iterative Q&A directly from the shell. [`README.md`](README.md)
2. **Security-conscious operators** who require sandboxed shell execution, scoped file access, and explicit confirmation before edits land. [`bash_executor.py`](bash_executor.py) [`main.py`](main.py)
3. **Release and platform teams** responsible for packaging, distributing, and upgrading the standalone binary across fleets. [`install.sh`](install.sh) [`_version.py`](_version.py)

## Product Pillars
- **Repository-aware conversations** – Collect directory listings plus up to eight contextually relevant files to seed model prompts, stream responses, and loop on follow-up instructions. [`contextualizer.py`](contextualizer.py) [`main.py`](main.py)
- **Guided file rewrites** – Switch to edit mode when a file path is scoped, request full replacements from the configured model, show numbered diffs, and only write after user approval. [`main.py`](main.py)
- **Sandboxed command execution** – Validate commands against disallowed substrings and path escapes before running them in a constrained bash session with output truncation and timeout controls. [`bash_executor.py`](bash_executor.py) [`main.py`](main.py)
- **Installation & upgrades** – Provide a curl-able installer, manage PATH shims, expose semantic versioning, and support upgrade checks directly from the CLI. [`install.sh`](install.sh) [`README.md`](README.md) [`_version.py`](_version.py)

## System Components
- **CLI Orchestrator (`main.py`)** – Parses arguments, enforces tool usage (read, write, shell, update_plan), manages OpenAI sessions, renders diffs, and persists chat history scratch files. [`main.py`](main.py)
- **Context Engine (`contextualizer.py`)** – Prioritizes interesting project files, applies byte limits, and formats the prompt/display context blocks. [`contextualizer.py`](contextualizer.py)
- **Sandboxed Bash Runtime (`bash_executor.py`)** – Houses command validation rules, executes bash with deterministic locale settings, and standardizes command transcripts. [`bash_executor.py`](bash_executor.py)
- **Configuration Subsystem (`config_loader.py`, `config_paths.py`)** – Resolves the XDG-compliant config path, loads JSON defaults, and merges environment overrides for models, prompts, and bash limits. [`config_loader.py`](config_loader.py) [`config_paths.py`](config_paths.py)
- **Distribution Scripts (`install.sh`, `_version.py`)** – Package and install the PyInstaller bundle, manage local upgrades, and surface the runtime version flag. [`install.sh`](install.sh) [`_version.py`](_version.py)

## Operational Workflows
1. **Repository conversation**
   - Parse CLI args, resolve scope, and gather context files. [`main.py`](main.py) [`contextualizer.py`](contextualizer.py)
   - Start an OpenAI Responses session with structured tool definitions and stream assistant output. [`main.py`](main.py)
   - Execute requested tools (read/write/shell/update_plan) and echo results back to the terminal for inspection. [`main.py`](main.py)
2. **File edit session**
   - Load the targeted file contents, request a full rewrite from the edit model, strip code fences, and render a unified diff with line numbers. [`main.py`](main.py)
   - Confirm before writing and normalize file permissions/newline termination on success. [`main.py`](main.py)
3. **Sandboxed bash command**
   - Reject empty, path-escaping, or disallowed operations up front. [`bash_executor.py`](bash_executor.py)
   - Run approved commands with time and output ceilings, then return formatted transcripts including exit codes. [`bash_executor.py`](bash_executor.py) [`main.py`](main.py)
4. **Upgrade flow**
   - Invoke the hosted installer (via `ai -u` or manual script), rehydrate the bundle under `~/.ai`, and optionally adjust PATH entries. [`main.py`](main.py) [`install.sh`](install.sh)

## Safeguards & Guardrails
- Reject writes outside the repository root and require confirmation for new content unless auto-applied by explicit instructions. [`main.py`](main.py)
- Trap Ctrl+C to clean up temporary chat history files, maintaining a tidy `/tmp`. [`main.py`](main.py)
- Enforce deterministic command environments (locale, working directory) and redact dangerous shell operations before execution. [`bash_executor.py`](bash_executor.py)

## Configuration & Extensibility
- Defaults include model selection, system prompts, and bash limits; users can override via `~/.config/ai/config.json` or environment variables such as `OPENAI_API_KEY`, `AI_MODEL*`, and `AI_BASH_MAX_*`. [`config_loader.py`](config_loader.py)
- Color customization (`AI_COLOR`) and system instruction overrides (`AI_SYSTEM_PROMPT`) tailor the terminal experience without source changes. [`config_loader.py`](config_loader.py) [`main.py`](main.py)

## External Dependencies & Interfaces
- Relies on the official `openai>=1.0.0` SDK for Responses and Chat Completions APIs. [`requirements.txt`](requirements.txt) [`main.py`](main.py)
- Assumes `curl`, `bash`, and `tar` availability for installation and upgrade paths. [`install.sh`](install.sh) [`README.md`](README.md)

## Future Opportunities
- Expand automated testing around diff rendering, sandbox enforcement, and CLI argument parsing. [`main.py`](main.py) [`bash_executor.py`](bash_executor.py)
- Refine context heuristics to incorporate CI definitions, lockfiles, or prioritized directories. [`contextualizer.py`](contextualizer.py)
- Clarify or relocate the plotting utilities in `test_funcs.py` to reduce confusion with production code. [`test_funcs.py`](test_funcs.py)

## Out of Scope
- GUI experiences, continuous background agents, or automated merge flows remain outside the current roadmap; `ai` focuses on explicit, user-driven CLI sessions per invocation. [`README.md`](README.md)
