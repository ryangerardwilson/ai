from __future__ import annotations

import shlex
import shutil
import subprocess
import os
from pathlib import Path
from typing import Dict, Optional


class TmuxError(RuntimeError):
    pass


class TmuxManager:
    def __init__(self, *, session_name: str, repo_root: Path) -> None:
        self.session_name = session_name
        self.repo_root = repo_root.resolve()
        self._pane_map: Dict[str, str] = {}
        self._orchestrator_pane_id: Optional[str] = None
        self._orchestrator_window_id: Optional[str] = None
        self._using_current_session = False

    def _ensure_tmux(self) -> None:
        if shutil.which("tmux") is None:
            raise TmuxError("tmux is required for orchestrator mode")

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self._ensure_tmux()
        proc = subprocess.run(
            ["tmux", *args],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip() or proc.stdout.strip()
            raise TmuxError(stderr or "tmux command failed")
        return proc

    def ensure_session(self) -> None:
        self._ensure_tmux()
        if "TMUX" in os.environ:
            proc = self._run(["display-message", "-p", "#S"])
            current = proc.stdout.strip()
            if current:
                self.session_name = current
                self._using_current_session = True
                self.ensure_orchestrator_pane()
                return
        has = subprocess.run(
            ["tmux", "has-session", "-t", self.session_name],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
        )
        if has.returncode == 0:
            self.ensure_orchestrator_pane()
            return
        self._run(["new-session", "-d", "-s", self.session_name, "bash"])
        self.ensure_orchestrator_pane()

    def ensure_orchestrator_pane(self) -> str:
        if self._orchestrator_pane_id:
            return self._orchestrator_pane_id
        if self._using_current_session:
            proc = self._run(["display-message", "-p", "#{pane_id}"])
            win_proc = self._run(["display-message", "-p", "#{window_id}"])
        else:
            proc = self._run(
                [
                    "display-message",
                    "-p",
                    "-t",
                    f"{self.session_name}:0.0",
                    "#{pane_id}",
                ]
            )
            win_proc = self._run(
                [
                    "display-message",
                    "-p",
                    "-t",
                    f"{self.session_name}:0.0",
                    "#{window_id}",
                ]
            )
        pane_id = proc.stdout.strip()
        window_id = win_proc.stdout.strip()
        if not pane_id:
            raise TmuxError("Unable to resolve orchestrator pane")
        self._orchestrator_pane_id = pane_id
        self._orchestrator_window_id = window_id or None
        self._run(["select-pane", "-t", pane_id, "-e"])
        return pane_id

    def ensure_musician_pane(self, musician: str, log_path: Path) -> str:
        self.ensure_session()
        if musician in self._pane_map:
            return self._pane_map[musician]
        target = self._orchestrator_pane_id if self._using_current_session else self.session_name
        proc = self._run(
            [
                "split-window",
                "-t",
                str(target),
                "-P",
                "-F",
                "#{pane_id}",
                "bash",
            ]
        )
        pane_id = proc.stdout.strip()
        self._pane_map[musician] = pane_id
        if not self._using_current_session:
            self._run(["select-layout", "-t", self.session_name, "tiled"])
        else:
            self._run(["select-layout", "tiled"])
        self._run(["select-pane", "-t", pane_id, "-d"])
        self._run_pane_command(
            pane_id,
            f"bash -lc {shlex.quote(f'touch {log_path}; tail -f {log_path}')}",
        )
        self.focus_orchestrator_pane()
        return pane_id

    def _run_pane_command(self, pane_id: str, command: str) -> None:
        self._run(["respawn-pane", "-k", "-t", pane_id, command])

    def run_in_pane(self, pane_id: str, command: str) -> None:
        self._run_pane_command(pane_id, command)

    def close_excess_panes(self) -> int:
        orchestrator_pane = self.ensure_orchestrator_pane()
        window_target = self._orchestrator_window_id or orchestrator_pane
        proc = self._run(["list-panes", "-t", window_target, "-F", "#{pane_id}"])
        pane_ids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        closed = 0
        for pane_id in pane_ids:
            if pane_id == orchestrator_pane:
                continue
            try:
                self._run(["kill-pane", "-t", pane_id])
                closed += 1
            except TmuxError:
                pass
        self._pane_map.clear()
        try:
            if self._using_current_session:
                self._run(["select-layout", "tiled"])
            else:
                self._run(["select-layout", "-t", self.session_name, "tiled"])
        except TmuxError:
            pass
        return closed

    def close_musician_panes(self) -> int:
        closed = 0
        for musician, pane_id in list(self._pane_map.items()):
            try:
                self._run(["kill-pane", "-t", pane_id])
                closed += 1
            except TmuxError:
                pass
            finally:
                self._pane_map.pop(musician, None)
        try:
            if self._using_current_session:
                self._run(["select-layout", "tiled"])
            else:
                self._run(["select-layout", "-t", self.session_name, "tiled"])
        except TmuxError:
            pass
        return closed

    def focus_orchestrator_pane(self) -> None:
        pane_id = self.ensure_orchestrator_pane()
        self._run(["select-pane", "-t", pane_id, "-e"])

    def uses_current_session(self) -> bool:
        return self._using_current_session

    def pane_is_busy(self, pane_id: str) -> Optional[bool]:
        try:
            proc = self._run([
                "display-message",
                "-p",
                "-t",
                pane_id,
                "#{pane_current_command}",
            ])
        except TmuxError:
            return None
        current = (proc.stdout or "").strip().lower()
        if not current:
            return None
        if current in {"bash", "zsh", "fish", "sh", "tail"}:
            return False
        return True
