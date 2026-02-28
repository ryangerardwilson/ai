from __future__ import annotations

import shlex
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestra_runtime import AssignmentRecord, OrchestraRuntime
from tmux_manager import TmuxManager


class OrchestraScheduler:
    def __init__(self, runtime: OrchestraRuntime, tmux: TmuxManager) -> None:
        self.runtime = runtime
        self.tmux = tmux

    def dispatch(self, *, task_id: str, dispatch_plan: List[Dict[str, Any]], mode: str) -> List[str]:
        assignment_ids: List[str] = []
        for item in dispatch_plan:
            musician = str(item.get("musician") or "").strip()
            if not musician:
                continue
            goal = str(item.get("goal_override") or item.get("goal") or "").strip()
            scope = [str(v) for v in item.get("scope") or []]
            constraints = [str(v) for v in item.get("constraints") or []]
            timeout_ms = int(item.get("timeout_ms") or 600000)

            rec = self.runtime.create_assignment(
                task_id=task_id,
                musician=musician,
                goal=goal,
                scope=scope,
                constraints=constraints,
                timeout_ms=timeout_ms,
            )
            log_path = self.runtime.musician_logs_dir / f"{musician}.log"
            pane_id = self.tmux.ensure_musician_pane(musician, log_path)
            command = self._build_worker_command(
                goal=goal,
                scope=scope,
                log_path=log_path,
                repo_root=self.runtime.repo_root,
            )
            self.tmux.run_in_pane(pane_id, command)
            self.runtime.musician_to_pane[musician] = pane_id
            self.runtime.update_assignment(
                rec.assignment_id,
                status="in_progress",
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                pane_id=pane_id,
                log_path=str(log_path),
            )
            assignment_ids.append(rec.assignment_id)
            self.tmux.focus_orchestrator_pane()

            if mode == "sequential":
                self.wait(assignment_id=rec.assignment_id, timeout_ms=timeout_ms)

        return assignment_ids

    def reset_for_new_task(self) -> Dict[str, int]:
        closed = self.tmux.close_excess_panes()
        cancelled = 0
        for rec in list(self.runtime.assignments.values()):
            if rec.status in {"pending", "in_progress"}:
                self.runtime.update_assignment(
                    rec.assignment_id,
                    status="cancelled",
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    error="cancelled: new task started",
                )
                cancelled += 1
        self.runtime.musician_to_pane.clear()
        return {"closed_panes": closed, "cancelled_assignments": cancelled}

    def poll(self, *, task_id: str, statuses: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for rec in self.runtime.list_assignments(task_id, statuses=statuses):
            self._refresh_status(rec)
            out.append(asdict(self.runtime.get_assignment(rec.assignment_id)))
        return out

    def wait(self, *, assignment_id: str, timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        rec = self.runtime.get_assignment(assignment_id)
        deadline = time.monotonic() + (timeout_ms or rec.timeout_ms) / 1000.0
        while time.monotonic() < deadline:
            self._refresh_status(rec)
            rec = self.runtime.get_assignment(assignment_id)
            if rec.status in {"completed", "failed", "cancelled", "timed_out"}:
                return asdict(rec)
            time.sleep(0.2)

        self.runtime.update_assignment(
            assignment_id,
            status="timed_out",
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error="wait timeout",
        )
        return asdict(self.runtime.get_assignment(assignment_id))

    def cancel(self, *, assignment_id: str) -> bool:
        rec = self.runtime.get_assignment(assignment_id)
        if rec.status in {"completed", "failed", "cancelled", "timed_out"}:
            return False
        self.runtime.update_assignment(
            assignment_id,
            status="cancelled",
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        return True

    def _refresh_status(self, rec: AssignmentRecord) -> None:
        if rec.status != "in_progress" or not rec.pane_id:
            return
        busy = self.tmux.pane_is_busy(rec.pane_id)
        if busy is False:
            self.runtime.update_assignment(
                rec.assignment_id,
                status="completed",
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                result_ref=rec.log_path,
            )

    def _build_worker_command(
        self,
        *,
        goal: str,
        scope: List[str],
        log_path: Path,
        repo_root: Path,
    ) -> str:
        parts: List[str] = [
            "python",
            "-u",
            "musician_worker.py",
            "--repo-root",
            str(repo_root),
            "--prompt",
            goal or "Review the repository and provide findings.",
        ]
        for path_item in scope:
            cleaned = path_item.strip()
            if not cleaned:
                continue
            candidate = Path(cleaned).expanduser()
            if not candidate.is_absolute():
                candidate = (repo_root / candidate).resolve()
            else:
                candidate = candidate.resolve()
            if not candidate.exists():
                continue
            parts.extend(["--scope", str(candidate)])
        inner = " ".join(shlex.quote(part) for part in parts)
        shell = f"{inner} 2>&1 | tee -a {shlex.quote(str(log_path))}; exec bash"
        return f"bash -lc {shlex.quote(shell)}"
