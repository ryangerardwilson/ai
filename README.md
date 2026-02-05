# ai

`ai` is a blunt, Vim-friendly terminal companion built on the OpenAI API. Launch it to chat in a dedicated TUI loop, fire off one-shot prompts, or hand it a file to rewrite while keeping eyes on the diff. Everything runs from a single binary with explicit controls for upgrades and versioning.

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

- `ai` — launch the interactive chat loop (Vim opens your scratch buffer for prompts).
- `ai "how do I write a release workflow?"` — send a one-off prompt; the reply prints to stdout.
- `ai -e path/to/file.py "replace legacy API usage"` — rewrite a file, inspect the diff, and apply if you confirm.
- `ai -v` — print the installed version.
- `ai -u` — rerun the installer script if a newer release exists.
- `ai -h` — show the CLI help summary.

Interactive mode keeps a temporary transcript under `/tmp`, streams assistant output live, and cleans itself up when you exit. Editing mode streams a proposed diff, asks for confirmation, and preserves permissions on write.

---

## Configuration & Environment

- `~/.config/ai/config.json` (respecting `XDG_CONFIG_HOME`) controls runtime defaults. Example:

```json
{
  "openai_api_key": "sk-your-key",
  "models": {
    "chat": "gpt-5.2",
    "prompt": "gpt-5-mini",
    "edit": "gpt-5-codex"
  },
  "system_instruction": "Channel a blunt, no-nonsense, technically brutal critique style"
}
```

- `OPENAI_API_KEY` overrides the `openai_api_key` entry at runtime (handy for CI or shells).
- `AI_MODEL` overrides every mode's model; `AI_MODEL_CHAT`, `AI_MODEL_PROMPT`, and `AI_MODEL_EDIT` target individual modes.
- `AI_COLOR` adjusts the ANSI color prefix for assistant output; `AI_SYSTEM_PROMPT` overrides the system instruction.
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
