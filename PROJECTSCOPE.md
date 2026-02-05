# Project Scope: `ai`

## Overview
`ai` is a Codex-inspired command-line assistant that runs locally and interacts with the OpenAI API to analyze repositories, answer questions, and draft file edits. It mirrors the multi-tool behavior of GitHub Copilot-style agents: gathering repository context, updating plans, invoking sandboxed shell commands, and writing files when explicitly approved. The CLI can operate over the whole repository or a scoped path, and it enforces explicit user confirmation before mutating files.\
— Source: [`README.md`](README.md)

## Core Capabilities
- **Interactive repository analysis** – Collects directory listings and prioritized files, then streams them to the language model before answering user prompts.\
  — [`main.py`](main.py), [`contextualizer.py`](contextualizer.py)
- **File editing workflow** – When pointed at a file, the CLI requests a Codex-style rewrite, shows a diff with numbered lines, and asks for confirmation before writing.\
  — `run_codex_edit` in [`main.py`](main.py)
- **Conversation loop with tool calls** – Maintains a plan, routes model-issued tool calls (read/write/shell/update_plan), and enforces sandbox rules so edits stay inside the repo.\
  — `run_codex_conversation` and helpers in [`main.py`](main.py)
- **Sandboxed bash execution** – Validates commands, blocks destructive operations, and truncates long output during AI-driven shell sessions.\
  — [`bash_executor.py`](bash_executor.py)
- **Configurable defaults** – Loads settings from XDG config paths, merges in environment overrides, and exposes knobs for model selection, system prompt, and bash limits.\
  — [`config_loader.py`](config_loader.py), [`config_paths.py`](config_paths.py)
- **Installer and release support** – Provides a bash installer for downloading tagged PyInstaller bundles, with version detection and upgrade checks.\
  — [`install.sh`](install.sh), [`_version.py`](_version.py)

## Architectural Outline
1. **Argument Parsing & Primary Flags** – `main()` recognizes `-h`, `-v`, and `-u` as early-exit commands for help, version, and self-upgrade respectively before loading config.\
   — `_handle_primary_flags` in [`main.py`](main.py)
2. **Mode Selection**
   - *Conversation Mode*: Default when no specific file path exists; composes repository context and drives an OpenAI Responses session with tool orchestration.\
     — `run_codex_conversation` in [`main.py`](main.py)
   - *Edit Mode*: Triggered when the first CLI argument is a file. Fetches baseline text, prompts the edit model, strips code fences, and writes the full file replacement after user approval.\
     — `run_codex_edit` in [`main.py`](main.py)
3. **Tool Handling** – `_handle_tool_call` dispatches model-issued requests. It logs invocations, validates paths against the repo root, confirms diffs interactively, and respects “auto-apply” rules when instructions clearly request writes.\
   — [`main.py`](main.py)
4. **Context Management** – `collect_context` prioritizes README, main entry points, and config files (up to eight files), returning both display and prompt-friendly formats.\
   — [`contextualizer.py`](contextualizer.py)
5. **OpenAI API Clients** – Both chat and edit flows construct an `openai.OpenAI` client with the resolved API key, and choose models per mode, swapping between Chat Completions and Responses depending on model capabilities.\
   — `AIChat`, `run_codex_conversation`, `run_codex_edit` in [`main.py`](main.py)
6. **User Confirmation UX** – Diffs are colorized and line-numbered when stdout is a TTY, and follow-up prompts allow iterative instructions after each response.\
   — `add_line_numbers_to_diff`, `follow_up` loop in [`main.py`](main.py)

## Configuration Surface
- **Config File** – Located at `${XDG_CONFIG_HOME:-~/.config}/ai/config.json`; ships with defaults for models, system prompt, OpenAI key placeholder, and bash resource limits. Environment variables override individual fields (e.g., `AI_MODEL_EDIT`, `AI_BASH_MAX_SECONDS`).\
  — [`config_loader.py`](config_loader.py), [`config_paths.py`](config_paths.py)
- **Runtime Environment Variables** – `OPENAI_API_KEY` is required unless supplied via config. Model overrides (`AI_MODEL`, `AI_MODEL_CHAT`, etc.) support per-mode customization.\
  — `load_config()` in [`config_loader.py`](config_loader.py)

## Safety & Guardrails
- **File Scope Enforcement** – Paths resolved from tool calls must remain inside the repository root; attempts outside are rejected.\
  — `_handle_tool_call` in [`main.py`](main.py)
- **Sandboxed Shell Commands** – Disallows dangerous substrings (`rm`, `sudo`, etc.) and absolute or parent paths, ensuring commands stay within the scoped directory.\
  — `_validate_command` in [`bash_executor.py`](bash_executor.py)
- **Explicit Writes** – The OpenAI agent is reminded to call `write`/`write_file` with full content; whenever it only describes a change without writing, the CLI prompts for correction.\
  — `_detect_generated_files` and conversation loop in [`main.py`](main.py)

## Distribution & Dependencies
- **Installer Workflow** – `install.sh` downloads the latest or requested release, installs into `~/.ai`, manages PATH updates (optional), and supports local bundles.\
  — [`install.sh`](install.sh)
- **Versioning** – `_version.py` holds the runtime version string; release automation overwrites it during tagged builds.\
  — [`_version.py`](_version.py)
- **Python Dependencies** – Minimal `requirements.txt` pinning `openai>=1.0.0`; the PyInstaller bundle encapsulates the rest.\
  — [`requirements.txt`](requirements.txt)

## Ancillary Content
- **Plotting Example Script** – `test_funcs.py` generates several sample plots using NumPy and Matplotlib, functioning as a demo or smoke test for CLI-assisted file editing.\
  — [`test_funcs.py`](test_funcs.py)
- **Repository Metadata** – Project summary, installation instructions, configuration hints, and usage examples live in `README.md`, serving as the end-user companion to this scope document.\
  — [`README.md`](README.md)

## Out-of-Scope / Open Questions
- Automated testing is absent; behaviors are exercised manually via the CLI.\
  — Lack of test harness beyond sample script (`test_funcs.py`)
- Release automation (referenced in README) resides outside this snapshot; GitHub Actions workflows are implied but not included here.

---
This document captures the functional boundaries, major components, and operational conventions of the `ai` CLI so contributors can quickly orient themselves and plan enhancements without digging through every module.
