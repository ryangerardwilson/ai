# ai

`ai` is a blunt, Codex-inspired terminal companion built on the OpenAI API. Launch it to analyze a repository snapshot, iterate on follow-up questions, or hand it a file to rewrite while keeping eyes on the diff. Everything runs from a single binary with explicit controls for upgrades and versioning.

---

## Installation

### Prebuilt binary (Linux x86_64)

Grab the latest tagged release via the helper script:

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/ai/main/install.sh | bash
```

The script drops the unpacked bundle into `~/.ai/app` and a shim in `~/.ai/bin`. It will attempt to append that directory to your `PATH` (unless you opt out). Once installed, run `ai -h` to confirm everything works.

Installer flags of note:

- `-v <x.y.z>`: install a specific tagged release (`v0.2.0`, etc.).
- `-v` (no argument): print the latest GitHub release version.
- `-u`: reinstall only if GitHub has something newer than your current local copy.
- `-b /path/to/ai-linux-x64.tar.gz`: install from an already-downloaded archive.
- `-h`: show installer usage.
- `--no-modify-path`: skip editing shell rc files; the script prints the `PATH` entry you need.

You can also download the `ai-linux-x64.tar.gz` artifact manually from the releases page and run `install.sh --binary` if you prefer to manage the bundle yourself.

### From source

```bash
git clone https://github.com/ryangerardwilson/ai.git
cd ai
python main.py
```

---

## Usage

- `ai` — analyze the current repository and start an interactive Q&A conversation (use the `follow_up >>>` prompt to continue, or press Enter to finish).
- `ai "how do I write a release workflow?"` — run a one-off prompt; the assistant answers once and exits.
- `ai path/to/file.py "replace legacy API usage"` — review the proposed diff for that file and confirm (or supply more context to retry).
- `ai "what is the objective of this repo"` — summarize the repository snapshot and cite relevant files.
- `ai docs/architecture "summarize these docs"` — limit the analysis to the `docs/architecture` directory before answering.
- When the assistant provides file contents, the CLI shows a unified diff for each file and asks for confirmation before writing; approved files are created or updated immediately.
- Behind the scenes the assistant uses Codex-like tools (`read_file`, `write_file`, `update_plan`, `shell`). You’ll see plan updates, command output, and diff prompts as those tools run.
- `ai -v` — print the installed version.
- `ai -u` — rerun the installer script if a newer release exists.
- `ai -h` — show the CLI help summary.

Each response streams live to your terminal, followed by the `follow_up >>>` prompt so you can iterate. Editing mode (triggered by a file scope or a conversation-generated file) shows a unified diff and preserves permissions when you approve the change.

---

## Configuration & Environment

- `~/.config/ai/config.json` (respecting `XDG_CONFIG_HOME`) controls runtime defaults. Example:

```json
{
  "openai_api_key": "sk-your-key",
  "models": {
    "chat": "gpt-5.2",
    "prompt": "gpt-5-mini",
    "edit": "gpt-5-codex",
    "bash": "gpt-5-codex"
  },
  "system_instruction": "Channel a blunt, no-nonsense, technically brutal critique style",
  "bash_settings": {
    "max_seconds": 20,
    "max_output_bytes": 32768,
    "max_iterations": 6
  }
}
```

- `OPENAI_API_KEY` overrides the `openai_api_key` entry at runtime (handy for CI or shells).
- `AI_MODEL` overrides every mode's model; `AI_MODEL_CHAT`, `AI_MODEL_PROMPT`, and `AI_MODEL_EDIT` target individual modes.
- `AI_COLOR` adjusts the ANSI color prefix for assistant output; `AI_SYSTEM_PROMPT` overrides the system instruction.
- `AI_MODEL_BASH` selects the model used in bash mode (defaults to a Responses-capable Codex model).
- `AI_BASH_MAX_SECONDS`, `AI_BASH_MAX_OUTPUT`, and `AI_BASH_MAX_ITERATIONS` tune command timeout, captured bytes, and maximum command/response loops.
- `bash_settings` in the config file mirrors those environment variables if you prefer static defaults.
- Models with the `-codex` suffix (for example `gpt-5-codex`) are Responses-only per [OpenAI's docs](https://platform.openai.com/docs/models/gpt-5-codex); `ai` automatically switches the edit workflow to the Responses API when you configure one.

The application stores temporary chat buffers in `/tmp/chat_history_*.txt`. Killing the process with `Ctrl+C` cleans up any remaining scratch files.

---

## Upgrading

Reinstall in place with:

```bash
ai -u
```

The binary checks GitHub for the latest release and only downloads when a newer version exists. You can also fetch a specific tag by running:

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

GitHub Actions builds a PyInstaller bundle (`ai-linux-x64.tar.gz`), updates `_version.py`, and publishes the asset alongside the tagged release.

---

## Development

- Requirements live in `requirements.txt`.
- `_version.py` carries the runtime version string; the release workflow overwrites it during tagged builds.
- Run `python main.py -h` to view the CLI summary from source.
