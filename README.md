# ai

`ai` is a Vim-first rewrite of OpenAI Codex running on the latest Responses API
superset of Completions. Launch it to analyze a repository snapshot, iterate on
follow-up questions, or hand it a file to rewrite while keeping eyes on the
diff. Everything runs from a single binary with explicit controls for upgrades
and versioning.

- CLI inline mode and CLI interactive chat mode wrap the Responses API so you can
  audit diffs, chat, or edit without leaving the keyboard. A TUI may arrive
  later.
- Minimal, opinionated workflow trims noise and keeps every run focused on
  shipping the next concrete change.
- Git safety by default: sandbox rules block dangerous operations (including
  `git add`/`git commit`/`git push`) and the assistant never auto-commits for
  you.

---

## How is this better than OpenAI Codex / OpenCode?

- Default mode avoids agentic detours: one model, one request, one response.
- Optional orchestrator mode (`-o`) can spawn up to five tmux-backed musician sub-agents when you explicitly want parallel decomposition/synthesis.
- Dog whistle control for mutating model tool calls in interactive chat: no whistle, no file mutation.
- CLI-first on purpose. No TUI, no shortcut maze—inline mode and chat mode play nicely with tmux.
- Low cognitive load. Minimal UI, fast startup, no persistent chat history beyond the session, so it stays as snappy as vanilla Vim.

## Installation

### Prebuilt binary (Linux x86_64)

Grab the latest tagged release via the helper script:

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/ai/main/install.sh | bash
```

The script drops the unpacked bundle into `~/.ai/app` and a shim in
`~/.ai/bin`. It will attempt to append that directory to your `PATH` (unless
you opt out). Once installed, run `ai -h` to confirm everything works.

Installer flags of note:

- `-v <x.y.z>`: install a specific tagged release (`v0.2.0`, etc.).
- `-v` (no argument): print the latest GitHub release version.
- `-u`: reinstall only if GitHub has something newer than your current local copy.
- `-b /path/to/ai`: install from an already-downloaded executable binary.
- `-h`: show installer usage.

You can also download the `ai-linux-x64.tar.gz` artifact manually from the
releases page, extract it, and pass the extracted `ai` executable to
`install.sh --binary`.

### From source

```bash
git clone https://github.com/ryangerardwilson/ai.git
cd ai
python main.py
```

---

## Usage

### Interactive chat

- `ai` — start a live chat session.
- `💬 >` prompt accepts follow-ups until you press Enter on an empty line or hit `Ctrl+D`.
- `v` — open Vim (or configured editor) to draft the next prompt.
- `help` / `new` — show cheat sheet or reset context.
- `q` / `r` — stop or retry while a response streams.
- `jfdi` — unlock mutating model tool calls (like `write`, `write_file`, `apply_patch`, tool-driven `shell`) for the current interactive session.
- `!command` in chat runs immediately through the sandboxed shell executor.

### Inline mode

- `ai "how do i add 2 and 2 in python"` — one-shot answer.
- `ai path/to/file.py path/to/other.py "what are these files about"` — scoped one-shot.
- Inline prompts can read, write, and run sandboxed commands immediately.

### Utilities

- `ai '!pytest -q'` — run a sandboxed shell command.
- `ai path/to/dir '!pytest -q'` — run a sandboxed shell command with a scoped working directory.
- `ai --read path/to/file.py --offset 400 --limit 200` — preview a file slice.
- `ai -d` — enable debug logs.
- `ai -o` — start orchestrator mode (tmux required) with musician sub-agents.
- `ai -oc` — close all tmux panes in the current window except the current pane.
- `ai -v` / `ai --version` / `ai -V` — show version.
- `ai -u` / `ai --upgrade` — upgrade.
- `ai -h` / `ai --help` — help.

### Orchestrator mode (`-o`)

- Requires tmux. If launched inside tmux, panes are created in the current session; otherwise `ai` creates a background session and prints how to attach.
- User interacts only with the orchestrator pane; musician panes are treated as execution/log panes.
- For execution-oriented tasks, the orchestrator clears excess panes, composes a fresh musician ensemble, dispatches assignments, then synthesizes output.
- For "which agents should we spawn" discussions, the orchestrator treats the turn as planning-only and does not force spawning unless explicitly asked.
- On `Ctrl+C`, orchestrator mode closes excess panes and exits with interrupt status.

### What you’ll see

- A rotating glyph loader appears while the model is preparing a response.
- Reasoning may stream as a dim `🤖` line (toggle with `AI_SHOW_REASONING=0`).
- File edits show a unified diff before writing.

## Tool Suite

- `read_file` / `write` / `write_file` / `apply_patch` — precise file IO primitives; prefer `write`/`write_file` with full file contents for edits.
- `glob` — repo-scoped file discovery powered by pattern matching (`src/**/*.py`, `tests/**/*_spec.py`, etc.).
- `search_content` — ripgrep-backed content search that returns `path:line:text` snippets right in the transcript.
- `shell` — sandboxed command runner (`!pytest`, `!ls src`) constrained to the repo root with output automatically attached to the conversation.
- `unit_test_coverage` — one-shot `pytest --cov` runner for quick coverage spot checks.
- `plan_update` (with legacy `update_plan`) — structured todo management so the assistant can publish, merge, and summarize task lists as work progresses.

In orchestrator mode, additional tools are available for multi-agent flow:

- `compose_ensemble`, `set_musician_mandates`, `dispatch_by_mandate`
- `poll_assignments`, `wait_assignment`, `collect_assignment_result`
- `cancel_assignment`, `synthesize_ensemble`, `list_musicians`, `reset_task_ensemble`

As the assistant works you’ll see tool output in-line—diff previews, coverage
summaries, plan updates—so every action stays transparent.

### Why a Single-Agent + Dog-Whistle Flow?

- **Default one-brain workflow.** In standard mode, a single assistant carries full context from plan to execution.
- **Orchestrator when needed.** `-o` is opt-in for tasks where multi-agent decomposition is helpful; otherwise you stay in the simpler single-agent flow.
- **User-controlled execution.** Your dog whistle phrase (default `jfdi`, but feel free to use `ship it`, `make it so`, `hakuna matata`) is the explicit “go” signal for interactive, model-initiated mutations.
- **Transparent guardrails.** When a mutating tool is blocked, the assistant tells you exactly why and reminds you of the phrase—no rummaging through agent logs.
- **Easy to customize.** Teams can pick a phrase that fits their culture; set it once in config or via `DOG_WHISTLE` and keep the workflow playful *and* safe.

---

## Configuration & Environment

- `~/.config/ai/config.json` (respecting `XDG_CONFIG_HOME`) stores your OpenAI API key, dog whistle phrase, and default model.
- On first launch `ai` asks for your OpenAI API key, then prompts for the default model, then asks for your dog whistle phrase (press Enter to keep `jfdi`) before writing the config file.

- `OPENAI_API_KEY` is used when `openai_api_key` is not set in config (handy for CI or shells).
- `AI_MODEL` overrides the single `model` value.
- `DOG_WHISTLE` overrides the approval phrase used to authorize interactive model-driven file edits and tool shell commands.
- `AI_COLOR` adjusts the ANSI color prefix for assistant output.
- `AI_PROMPT_EDITOR` overrides which editor `v` uses for prompt drafting.
- `AI_SHOW_REASONING=0` (or `AI_SHOW_THINKING=0`) disables the live reasoning stream.
- `AI_REASONING_EFFORT` tweaks how hard reasoning models think (`minimal`, `low`, `medium`, `high`, etc.); defaults to `medium` when reasoning is enabled.
- `AI_DEBUG_API` (alias `AI_DEBUG_REASONING`) enables verbose OpenAI interaction logs; combine with the `-d` flag to capture them automatically.
- `AI_BASH_MAX_SECONDS` and `AI_BASH_MAX_OUTPUT` tune timeout and output caps for tool-driven `shell` calls.
- Context collection defaults are code-level constants (`read_limit` 2000, `max_bytes` 51200, listings disabled for full-repo snapshots, max 8 files per collection pass).
- Models with the `-codex` suffix (for example `gpt-5-codex`) are Responses-only per [OpenAI's docs](https://platform.openai.com/docs/models/gpt-5-codex); `ai` automatically switches the edit workflow to the Responses API when you configure one.

Prompt drafting in editor mode uses temporary files in `/tmp` and removes them
on completion.

Orchestrator runtime artifacts are ephemeral by default and stored under system
temp (`/tmp/ai_orchestra/...`), then cleaned up when the orchestrator session
ends.

---

## Upgrading

Reinstall in place with:

```bash
ai -u
```

The binary checks GitHub for the latest release and only downloads when a newer
version exists. You can also fetch a specific tag by running:

```bash
install.sh -v 0.4.0
```

---

## Releases

Tag the repository with the desired semantic version and push:

```bash
git tag v0.4.0
git push origin v0.4.0
```

GitHub Actions builds a PyInstaller bundle (`ai-linux-x64.tar.gz`), stamps the
placeholder `_version.py` in the shipped artifact, and publishes the asset
alongside the tagged release.

---

## Development

- Requirements live in `requirements.txt`.
- `_version.py` carries the runtime version string; the checked-in value stays a placeholder and the release workflow overwrites it during tagged builds.
- Run `python main.py -h` to view the CLI summary from source.
- `ai_engine.py` hosts the core orchestration (context gathering, tool dispatch, Responses loop) and can be reused by future UIs.
- `cli_renderer.py` implements the current terminal UX; alternative renderers (TUI, GUI) can plug into the same engine.
- `orchestrator.py` wires configuration, renderer, and engine together so `main.py` remains a thin entrypoint.
