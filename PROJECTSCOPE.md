# Project Scope: `ai` CLI Companion

## 1. Mission Statement
- Deliver a local-first terminal assistant that combines OpenAI Responses with repo-aware tooling so developers can inspect code, run commands, and apply edits without leaving the shell. ([README.md](README.md), [orchestrator.py](orchestrator.py), [ai_engine_main.py](ai_engine_main.py))
- Preserve user control by surfacing plans, tool calls, shell output, and unified diffs directly in-session. ([ai_engine_main.py](ai_engine_main.py), [ai_engine_tools.py](ai_engine_tools.py), [cli_renderer.py](cli_renderer.py))
- Keep distribution simple: one install script, one binary bundle target, and an upgrade path. ([install.sh](install.sh), [README.md](README.md), [orchestrator.py](orchestrator.py))

## 2. Product Principles
- **Observable operations** – Stream assistant output/reasoning, show tool results inline, and render numbered unified diffs before write application. ([ai_engine_main.py](ai_engine_main.py), [cli_renderer.py](cli_renderer.py), [ai_engine_tools.py](ai_engine_tools.py))
- **Controlled mutation** – In interactive chat, mutating tool calls are blocked until the dog whistle is provided; read-only tools remain available. ([ai_engine_main.py](ai_engine_main.py), [ai_engine_tools.py](ai_engine_tools.py), [README.md](README.md))
- **Minimal runtime surface** – Runtime dependency is the OpenAI Python SDK plus stdlib modules. ([requirements.txt](requirements.txt), [orchestrator.py](orchestrator.py), [ai_engine_main.py](ai_engine_main.py))

## 3. Primary Workflows
| Flow | Invocation Example | Description | Key Sources | | --- | --- | --- |
--- | | Interactive conversation | `ai` | Starts prompt loop (`💬 >`), runs
Responses streaming, supports `help`, `new`, `v`, and in-chat `!command`. |
[orchestrator.py](orchestrator.py), [ai_engine_main.py](ai_engine_main.py),
[cli_renderer.py](cli_renderer.py) | | Inline one-shot | `ai "explain this
repo"` | Single-request mode with no follow-up loop. |
[inline_prompt_mode.py](inline_prompt_mode.py),
[inline_mode_renderer.py](inline_mode_renderer.py) | | Scoped inline prompt |
`ai path/to/dir "summarize architecture"` | Collects context from provided path
arguments before one-shot model call. |
[inline_prompt_mode.py](inline_prompt_mode.py),
[inline_mode_renderer.py](inline_mode_renderer.py),
[contextualizer.py](contextualizer.py) | | Read-only preview | `ai --read
path/to/file.py --offset 400 --limit 200` | Prints bounded file slice and
continuation hint if truncated. | [orchestrator.py](orchestrator.py),
[contextualizer.py](contextualizer.py) | | Immediate sandboxed shell | `ai
'!pytest -q'` | Executes guarded shell command without starting model
conversation loop. | [orchestrator.py](orchestrator.py),
[bash_executor.py](bash_executor.py) | | Self-upgrade | `ai -u` | Calls
installer script to reinstall only when newer release is available. |
[orchestrator.py](orchestrator.py), [install.sh](install.sh),
[README.md](README.md) |

## 4. Architectural Components
- **CLI entrypoint** – Thin wrapper that instantiates orchestrator and forwards argv. ([main.py](main.py))
- **Orchestrator** – Handles config bootstrap, top-level flags, immediate shell invocations, inline mode delegation, and interactive session startup. ([orchestrator.py](orchestrator.py))
- **AI engine** – Maintains conversation state, streaming Responses loop, tool-call handling, hotkey cancel/retry, and dog-whistle gating for mutating tools. ([ai_engine_main.py](ai_engine_main.py), [ai_engine.py](ai_engine.py))
- **Tool runtime** – Implements `read_file`, `write`, `write_file`, `apply_patch`, `shell`, `glob`, `search_content`, `unit_test_coverage`, `update_plan`, and `plan_update`. ([ai_engine_tools.py](ai_engine_tools.py))
- **Context collection** – Selects candidate files, slices text windows, and formats prompt-ready snapshots. ([contextualizer.py](contextualizer.py))
- **Renderer** – Terminal UX for prompts, loader, reasoning stream, assistant stream, diff rendering, and editor integration. ([cli_renderer.py](cli_renderer.py))
- **Configuration pathing/loading** – XDG-aware config location with env overrides. ([config_paths.py](config_paths.py), [config_loader.py](config_loader.py))

## 5. Configuration & Environment
- Config file: `~/.config/ai/config.json` (or `XDG_CONFIG_HOME`) with persisted keys: `openai_api_key`, `model`, `dog_whistle`. ([config_paths.py](config_paths.py), [config_loader.py](config_loader.py), [README.md](README.md))
- Env overrides implemented in loader: `OPENAI_API_KEY`, `AI_MODEL`, `DOG_WHISTLE`. ([config_loader.py](config_loader.py))
- Runtime behavior toggles consumed by engine/renderer/tooling include: `AI_SHOW_REASONING` / `AI_SHOW_THINKING`, `AI_REASONING_EFFORT`, `AI_DEBUG_API` / `AI_DEBUG_REASONING`, `AI_COLOR`, `AI_PROMPT_EDITOR`, `AI_BASH_MAX_SECONDS`, `AI_BASH_MAX_OUTPUT`. ([ai_engine_config.py](ai_engine_config.py), [cli_renderer.py](cli_renderer.py), [orchestrator.py](orchestrator.py), [ai_engine_tools.py](ai_engine_tools.py), [README.md](README.md))
- Context limits are currently code-level defaults in `contextualizer.py`; persisted `context_settings` are dropped by config loader. ([contextualizer.py](contextualizer.py), [config_loader.py](config_loader.py))

## 6. Tooling & Safeguards
- Mutating tool calls (`write`, `write_file`, `apply_patch`, tool-driven `shell`) are blocked in interactive mode until dog whistle approval is detected. ([ai_engine_main.py](ai_engine_main.py), [ai_engine_tools.py](ai_engine_tools.py))
- Inline mode runs with mutation enabled for the one-shot call path. ([inline_mode_renderer.py](inline_mode_renderer.py))
- File writes are applied through renderer diff review (`review_file_update`) and written to disk when accepted by workflow logic. ([ai_engine_tools.py](ai_engine_tools.py), [cli_renderer.py](cli_renderer.py))
- Bash sandbox rejects commands containing disallowed substrings and rejects absolute/parent-path tokens and `.git` path references. ([bash_executor.py](bash_executor.py))
- Read-only search/discovery helpers (`glob`, `search_content`, `read_file`) stay available regardless of mutation approval state. ([ai_engine_tools.py](ai_engine_tools.py))

## 7. Dependencies & Packaging
- Runtime dependency: `openai>=1.0.0`. ([requirements.txt](requirements.txt))
- Distribution target documented and implemented as Linux x86_64 PyInstaller bundle (`ai-linux-x64.tar.gz`). ([README.md](README.md), [install.sh](install.sh))
- Installer installs bundle under `~/.ai/app`, places shim in `~/.ai/bin`, and supports latest/versioned/upgrade/local-binary paths. ([install.sh](install.sh), [README.md](README.md))

## 8. Testing & Quality
- Current tests cover contextualizer slicing, streaming/cancel/retry engine behavior, CLI prompt behavior, tool handlers, and orchestrator shell/inline routing. ([tests/test_contextualizer.py](tests/test_contextualizer.py), [tests/test_ai_engine_streaming.py](tests/test_ai_engine_streaming.py), [tests/test_cli_renderer_prompt.py](tests/test_cli_renderer_prompt.py), [tests/test_ai_engine_tools.py](tests/test_ai_engine_tools.py), [tests/test_orchestrator_shell.py](tests/test_orchestrator_shell.py))
- There is still limited direct coverage for installer script behavior and full end-to-end OpenAI integration paths. ([install.sh](install.sh), [orchestrator.py](orchestrator.py), [ai_engine_main.py](ai_engine_main.py))

## 9. Release & Distribution Flow
1. Tag semantic version and push tag. ([README.md](README.md))
2. CI builds/publishes release artifact and updates runtime version metadata. ([README.md](README.md), [_version.py](_version.py))
3. Users install/upgrade via `install.sh` (remote fetch) or provide a local executable via `--binary`. ([install.sh](install.sh), [README.md](README.md))

## 10. Operational Considerations & Limitations
- Requires valid OpenAI API key from config/env; no offline model runtime. ([config_loader.py](config_loader.py), [ai_engine_config.py](ai_engine_config.py), [README.md](README.md))
- Prebuilt binary support is Linux x86_64 only. ([README.md](README.md), [install.sh](install.sh))
- Shell sandbox reduces risk but does not eliminate side effects of allowed commands; operator review is still required. ([bash_executor.py](bash_executor.py), [README.md](README.md))
- Repo context collection intentionally samples a bounded subset of files each pass (`MAX_FILES=8`, byte/line caps). ([contextualizer.py](contextualizer.py))

## 11. Future Opportunities
- Add broader tests for orchestrator flag matrix, installer edge cases, and additional tool-call branches. ([orchestrator.py](orchestrator.py), [install.sh](install.sh), [ai_engine_tools.py](ai_engine_tools.py))
- Expose configurable context limits through persisted config instead of code-only defaults. ([config_loader.py](config_loader.py), [contextualizer.py](contextualizer.py))
- Document platform strategy beyond Linux x86_64 and/or publish additional artifacts. ([README.md](README.md), [install.sh](install.sh))
- Consider modular tool registration hooks for project-specific tool extensions. ([ai_engine_tools.py](ai_engine_tools.py), [ai_engine_main.py](ai_engine_main.py))

## 12. Out of Scope / Assumptions
- Native non-Linux installer support is not provided in current release flow. ([install.sh](install.sh), [README.md](README.md))
- Credential storage is limited to local config/env usage; the app does not implement secret vaulting. ([config_loader.py](config_loader.py))
- Interactive mutation gating applies to model-driven mutating tools; direct CLI shell invocation remains an explicit user command path. ([orchestrator.py](orchestrator.py), [ai_engine_main.py](ai_engine_main.py), [ai_engine_tools.py](ai_engine_tools.py))
