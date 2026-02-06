from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _resolve_base_dir() -> Optional[Path]:
    candidates: list[Path] = []

    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        candidates.append(Path(xdg_state) / "ai" / "conversations")

    candidates.append(Path.home() / ".local" / "state" / "ai" / "conversations")
    candidates.append(Path.home() / ".ai" / "conversations")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return None


class ConversationStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.base_dir = _resolve_base_dir()
        disable = os.environ.get("AI_DISABLE_PERSISTENCE", "").lower() in {
            "1",
            "true",
            "yes",
        }
        self.enabled = self.base_dir is not None and not disable
        if not self.enabled:
            self.base_dir = None
            self.file_path = None
            return
        digest = hashlib.sha1(str(self.workspace).encode("utf-8")).hexdigest()
        assert self.base_dir is not None  # for type checkers
        self.file_path = self.base_dir / f"{digest}.json"

    def load(self) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if not self.enabled or not self.file_path or not self.file_path.exists():
            return [], None
        try:
            with self.file_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return [], None

        if not isinstance(data, dict):
            return [], None
        if data.get("path") and Path(data["path"]).resolve() != self.workspace:
            return [], None
        items = data.get("items", [])
        if not isinstance(items, list):
            return [], None
        plan = data.get("plan")
        if plan is not None and not isinstance(plan, str):
            plan = None
        return items, plan

    def save(self, items: List[Dict[str, Any]], plan: Optional[str]) -> None:
        if not self.enabled or not self.file_path:
            return
        payload = {"path": str(self.workspace), "items": items, "plan": plan}
        tmp_path = self.file_path.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            tmp_path.replace(self.file_path)
        except OSError:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

    def clear(self) -> None:
        if not self.enabled or not self.file_path:
            return
        try:
            self.file_path.unlink()
        except FileNotFoundError:
            pass
