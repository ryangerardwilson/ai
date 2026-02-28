from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MUSICIAN_POOL = ["cello", "harp", "piano", "violin", "flute"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AssignmentRecord:
    assignment_id: str
    task_id: str
    musician: str
    goal: str
    scope: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    timeout_ms: int = 600000
    status: str = "pending"
    created_at: str = field(default_factory=_utc_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    pane_id: Optional[str] = None
    log_path: Optional[str] = None
    result_ref: Optional[str] = None
    error: Optional[str] = None


class OrchestraRuntime:
    def __init__(self, repo_root: Path, state_root: Optional[Path] = None) -> None:
        self.repo_root = repo_root.resolve()
        base = state_root.resolve() if state_root else (self.repo_root / ".ai_orchestra")
        self.state_root = base
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + secrets.token_hex(3)
        self.run_dir = self.state_root / self.run_id
        self.logs_dir = self.run_dir / "logs"
        self.musician_logs_dir = self.logs_dir / "musicians"
        self.tasks_dir = self.run_dir / "tasks"

        self.active_task_id: Optional[str] = None
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.assignments: Dict[str, AssignmentRecord] = {}
        self.musician_to_pane: Dict[str, str] = {}

        self._ensure_dirs()
        self._persist_run_state()

    def _ensure_dirs(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.musician_logs_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _persist_run_state(self) -> None:
        self._write_json(
            self.run_dir / "run.json",
            {
                "run_id": self.run_id,
                "repo_root": str(self.repo_root),
                "created_at": _utc_now(),
                "active_task_id": self.active_task_id,
                "tasks": sorted(self.tasks.keys()),
                "active_musicians": sorted(self.musician_to_pane.keys()),
            },
        )

    def start_task(self, user_goal: str, depth_profile: str, task_type: str) -> Dict[str, Any]:
        task_id = "task_" + secrets.token_hex(4)
        payload = {
            "task_id": task_id,
            "user_goal": user_goal,
            "depth_profile": depth_profile,
            "task_type": task_type,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "mandates": [],
            "assignment_ids": [],
        }
        self.tasks[task_id] = payload
        self.active_task_id = task_id
        self._persist_task(task_id)
        self._persist_run_state()
        return payload

    def _persist_task(self, task_id: str) -> None:
        task = self.tasks[task_id]
        self._write_json(self.tasks_dir / task_id / "session.json", task)

    def set_mandates(self, task_id: str, mandates: List[Dict[str, Any]]) -> Dict[str, Any]:
        if task_id not in self.tasks:
            raise ValueError(f"Unknown task_id: {task_id}")
        if not mandates:
            raise ValueError("At least one mandate is required")
        if len(mandates) > 5:
            raise ValueError("A maximum of 5 mandates is allowed")
        names = [str(item.get("musician", "")).strip() for item in mandates]
        if any(name not in MUSICIAN_POOL for name in names):
            raise ValueError("One or more musicians are invalid")
        if len(set(names)) != len(names):
            raise ValueError("Duplicate musicians in mandates are not allowed")
        task = self.tasks[task_id]
        task["mandates"] = mandates
        task["updated_at"] = _utc_now()
        self._persist_task(task_id)
        self._persist_run_state()
        return task

    def clear_mandates(self, task_id: str) -> Dict[str, Any]:
        if task_id not in self.tasks:
            raise ValueError(f"Unknown task_id: {task_id}")
        task = self.tasks[task_id]
        task["mandates"] = []
        task["updated_at"] = _utc_now()
        self._persist_task(task_id)
        self._persist_run_state()
        return task

    def create_assignment(
        self,
        *,
        task_id: str,
        musician: str,
        goal: str,
        scope: List[str],
        constraints: List[str],
        timeout_ms: int,
    ) -> AssignmentRecord:
        if task_id not in self.tasks:
            raise ValueError(f"Unknown task_id: {task_id}")
        assignment_id = "asg_" + secrets.token_hex(4)
        record = AssignmentRecord(
            assignment_id=assignment_id,
            task_id=task_id,
            musician=musician,
            goal=goal,
            scope=scope,
            constraints=constraints,
            timeout_ms=timeout_ms,
        )
        self.assignments[assignment_id] = record
        task = self.tasks[task_id]
        task["assignment_ids"].append(assignment_id)
        task["updated_at"] = _utc_now()
        self._persist_assignment(record)
        self._persist_task(task_id)
        return record

    def _persist_assignment(self, record: AssignmentRecord) -> None:
        path = self.tasks_dir / record.task_id / "assignments" / f"{record.assignment_id}.json"
        self._write_json(path, asdict(record))

    def update_assignment(self, assignment_id: str, **updates: Any) -> AssignmentRecord:
        if assignment_id not in self.assignments:
            raise ValueError(f"Unknown assignment_id: {assignment_id}")
        record = self.assignments[assignment_id]
        for key, value in updates.items():
            if hasattr(record, key):
                setattr(record, key, value)
        self._persist_assignment(record)
        if record.task_id in self.tasks:
            self.tasks[record.task_id]["updated_at"] = _utc_now()
            self._persist_task(record.task_id)
        return record

    def get_assignment(self, assignment_id: str) -> AssignmentRecord:
        if assignment_id not in self.assignments:
            raise ValueError(f"Unknown assignment_id: {assignment_id}")
        return self.assignments[assignment_id]

    def list_assignments(self, task_id: str, statuses: Optional[List[str]] = None) -> List[AssignmentRecord]:
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Unknown task_id: {task_id}")
        wanted = set(statuses or [])
        out: List[AssignmentRecord] = []
        for assignment_id in task.get("assignment_ids", []):
            rec = self.assignments.get(assignment_id)
            if not rec:
                continue
            if wanted and rec.status not in wanted:
                continue
            out.append(rec)
        return out

    def list_musicians(self) -> Dict[str, Any]:
        active = sorted(self.musician_to_pane.keys())
        available = [name for name in MUSICIAN_POOL if name not in self.musician_to_pane]
        return {
            "available": available,
            "active": active,
            "max_musicians": len(MUSICIAN_POOL),
        }
