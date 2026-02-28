from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from orchestra_runtime import MUSICIAN_POOL, OrchestraRuntime
from orchestra_scheduler import OrchestraScheduler


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "data": data}


def _err(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details or {},
        },
    }


def _parse_args(arguments: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if isinstance(arguments, dict):
        return arguments, None
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}, None
        try:
            value = json.loads(text)
        except Exception as exc:
            return None, _err("invalid_args", f"Arguments must be valid JSON: {exc}")
        if not isinstance(value, dict):
            return None, _err("invalid_args", "Arguments must decode to an object")
        return value, None
    if arguments is None:
        return {}, None
    return None, _err("invalid_args", "Unsupported argument format")


def handle_orchestra_tool_call(
    tool_name: str,
    arguments: Any,
    *,
    runtime: OrchestraRuntime,
    scheduler: Any,
) -> tuple[str, bool]:
    args, parse_error = _parse_args(arguments)
    if parse_error is not None:
        return json.dumps(parse_error), False
    assert args is not None

    try:
        if tool_name == "compose_ensemble":
            payload, mutated = run_compose_ensemble(args, runtime=runtime)
            return json.dumps(payload), mutated
        if tool_name == "set_musician_mandates":
            payload, mutated = run_set_musician_mandates(args, runtime=runtime)
            return json.dumps(payload), mutated
        if tool_name == "dispatch_by_mandate":
            payload, mutated = run_dispatch_by_mandate(
                args, runtime=runtime, scheduler=scheduler
            )
            return json.dumps(payload), mutated
        if tool_name == "poll_assignments":
            payload, mutated = run_poll_assignments(
                args, runtime=runtime, scheduler=scheduler
            )
            return json.dumps(payload), mutated
        if tool_name == "wait_assignment":
            payload, mutated = run_wait_assignment(
                args, runtime=runtime, scheduler=scheduler
            )
            return json.dumps(payload), mutated
        if tool_name == "collect_assignment_result":
            payload, mutated = run_collect_assignment_result(args, runtime=runtime)
            return json.dumps(payload), mutated
        if tool_name == "cancel_assignment":
            payload, mutated = run_cancel_assignment(
                args, runtime=runtime, scheduler=scheduler
            )
            return json.dumps(payload), mutated
        if tool_name == "synthesize_ensemble":
            payload, mutated = run_synthesize_ensemble(args, runtime=runtime)
            return json.dumps(payload), mutated
        if tool_name == "list_musicians":
            payload, mutated = run_list_musicians(args, runtime=runtime)
            return json.dumps(payload), mutated
        if tool_name == "reset_task_ensemble":
            payload, mutated = run_reset_task_ensemble(args, runtime=runtime)
            return json.dumps(payload), mutated
    except ValueError as exc:
        return json.dumps(_err("invalid_args", str(exc))), False
    except Exception as exc:  # pragma: no cover - defensive
        return json.dumps(_err("internal_error", str(exc))), False

    return (
        json.dumps(_err("invalid_args", f"Unknown orchestrator tool: {tool_name}")),
        False,
    )


def run_compose_ensemble(
    args: Dict[str, Any], *, runtime: OrchestraRuntime
) -> tuple[Dict[str, Any], bool]:
    user_goal = str(args.get("user_goal") or "").strip()
    if not user_goal:
        raise ValueError("user_goal is required")
    depth = str(args.get("depth_profile") or "standard")
    task_type = str(args.get("task_type") or "mixed")
    max_musicians = int(args.get("max_musicians") or 3)
    max_musicians = max(1, min(5, max_musicians))
    if depth == "quick":
        preferred = 2
    elif depth == "deep":
        preferred = 5
    else:
        preferred = 3
    count = min(max_musicians, preferred)
    selected = MUSICIAN_POOL[:count]
    proposed = [
        {
            "musician": name,
            "title": f"{name.title()} mandate",
            "objective": f"Contribute first-principles analysis for: {user_goal}",
            "method": ["decompose assumptions", "produce concrete findings"],
            "deliverable_format": "bulleted_memo",
            "non_goals": ["Do not ask the user direct questions"],
        }
        for name in selected
    ]
    task = runtime.start_task(user_goal=user_goal, depth_profile=depth, task_type=task_type)
    return (
        _ok(
            {
                "task_id": task["task_id"],
                "proposed_mandates": proposed,
                "rationale": "Selected ensemble size from depth profile and max_musicians.",
            }
        ),
        True,
    )


def run_set_musician_mandates(
    args: Dict[str, Any], *, runtime: OrchestraRuntime
) -> tuple[Dict[str, Any], bool]:
    task_id = str(args.get("task_id") or "").strip()
    mandates = args.get("mandates")
    if not task_id:
        raise ValueError("task_id is required")
    if not isinstance(mandates, list):
        raise ValueError("mandates must be a list")
    task = runtime.set_mandates(task_id, mandates)
    active = [str(item.get("musician")) for item in task.get("mandates", [])]
    return (
        _ok(
            {
                "task_id": task_id,
                "active_musicians": active,
                "mandate_count": len(active),
            }
        ),
        True,
    )


def run_dispatch_by_mandate(
    args: Dict[str, Any],
    *,
    runtime: OrchestraRuntime,
    scheduler: OrchestraScheduler,
) -> tuple[Dict[str, Any], bool]:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    mode = str(args.get("mode") or "parallel")
    dispatch_plan = args.get("dispatch_plan")
    if not isinstance(dispatch_plan, list) or not dispatch_plan:
        task = runtime.tasks.get(task_id)
        if not task:
            raise ValueError(f"Unknown task_id: {task_id}")
        dispatch_plan = []
        for mandate in task.get("mandates", []):
            dispatch_plan.append(
                {
                    "musician": mandate.get("musician"),
                    "goal_override": mandate.get("objective") or "",
                }
            )
    assignment_ids = scheduler.dispatch(
        task_id=task_id, dispatch_plan=dispatch_plan, mode=mode
    )
    return (
        _ok(
            {
                "task_id": task_id,
                "mode": mode,
                "assignment_ids": assignment_ids,
                "dispatched": len(assignment_ids),
            }
        ),
        True,
    )


def run_poll_assignments(
    args: Dict[str, Any],
    *,
    runtime: OrchestraRuntime,
    scheduler: OrchestraScheduler,
) -> tuple[Dict[str, Any], bool]:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    statuses_raw = args.get("statuses")
    statuses = [str(v) for v in statuses_raw] if isinstance(statuses_raw, list) else None
    assignments = scheduler.poll(task_id=task_id, statuses=statuses)
    return _ok({"task_id": task_id, "assignments": assignments}), False


def run_wait_assignment(
    args: Dict[str, Any],
    *,
    runtime: OrchestraRuntime,
    scheduler: OrchestraScheduler,
) -> tuple[Dict[str, Any], bool]:
    assignment_id = str(args.get("assignment_id") or "").strip()
    if not assignment_id:
        raise ValueError("assignment_id is required")
    timeout_ms = args.get("timeout_ms")
    timeout_value = int(timeout_ms) if timeout_ms is not None else None
    record = scheduler.wait(assignment_id=assignment_id, timeout_ms=timeout_value)
    return _ok(record), True


def run_collect_assignment_result(
    args: Dict[str, Any], *, runtime: OrchestraRuntime
) -> tuple[Dict[str, Any], bool]:
    assignment_id = str(args.get("assignment_id") or "").strip()
    if not assignment_id:
        raise ValueError("assignment_id is required")
    rec = runtime.get_assignment(assignment_id)
    log_path = Path(rec.log_path) if rec.log_path else None
    text = ""
    if log_path and log_path.exists():
        text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    tail = lines[-120:]
    summary = tail[-1] if tail else "No output yet."
    return (
        _ok(
            {
                "assignment_id": assignment_id,
                "summary": summary,
                "findings": tail[-10:],
                "citations": [],
                "artifacts": [str(log_path)] if log_path else [],
            }
        ),
        False,
    )


def run_cancel_assignment(
    args: Dict[str, Any],
    *,
    runtime: OrchestraRuntime,
    scheduler: OrchestraScheduler,
) -> tuple[Dict[str, Any], bool]:
    assignment_id = str(args.get("assignment_id") or "").strip()
    if not assignment_id:
        raise ValueError("assignment_id is required")
    changed = scheduler.cancel(assignment_id=assignment_id)
    rec = runtime.get_assignment(assignment_id)
    return (
        _ok(
            {
                "assignment_id": assignment_id,
                "status": rec.status,
                "changed": changed,
            }
        ),
        changed,
    )


def run_synthesize_ensemble(
    args: Dict[str, Any], *, runtime: OrchestraRuntime
) -> tuple[Dict[str, Any], bool]:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    assignment_ids_raw = args.get("assignment_ids")
    if isinstance(assignment_ids_raw, list) and assignment_ids_raw:
        assignment_ids = [str(v) for v in assignment_ids_raw]
    else:
        assignment_ids = [rec.assignment_id for rec in runtime.list_assignments(task_id)]

    snippets: List[str] = []
    for assignment_id in assignment_ids:
        rec = runtime.get_assignment(assignment_id)
        if rec.log_path and Path(rec.log_path).exists():
            text = Path(rec.log_path).read_text(encoding="utf-8", errors="replace")
            last = "\n".join(text.splitlines()[-5:])
            if last:
                snippets.append(f"[{rec.musician}]\n{last}")

    consensus = "\n\n".join(snippets) if snippets else "No musician output available yet."
    payload = {
        "task_id": task_id,
        "consensus": consensus,
        "disagreements": [],
        "recommended_path": "Review musician outputs and choose the strongest combined plan.",
        "confidence": 0.5 if snippets else 0.1,
        "risks": [],
        "next_actions": ["Refine mandates", "Dispatch another round if needed"],
    }
    path = runtime.tasks_dir / task_id / "synthesis.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return _ok(payload), True


def run_list_musicians(
    args: Dict[str, Any], *, runtime: OrchestraRuntime
) -> tuple[Dict[str, Any], bool]:
    return _ok(runtime.list_musicians()), False


def run_reset_task_ensemble(
    args: Dict[str, Any], *, runtime: OrchestraRuntime
) -> tuple[Dict[str, Any], bool]:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id is required")
    task = runtime.tasks.get(task_id)
    if not task:
        raise ValueError(f"Unknown task_id: {task_id}")
    runtime.clear_mandates(task_id)
    return _ok({"task_id": task_id, "mandates_cleared": True}), True
