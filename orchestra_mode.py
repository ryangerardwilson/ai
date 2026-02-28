from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_engine import AIEngine, NEW_CONVERSATION_TOKEN
from orchestra_runtime import OrchestraRuntime
from orchestra_scheduler import OrchestraScheduler
from tmux_manager import TmuxError, TmuxManager


def _is_agent_planning_discussion(text: str) -> bool:
    lowered = (text or "").lower()
    planning_phrases = (
        "which agent",
        "which agents",
        "which musician",
        "which musicians",
        "what agents",
        "what musicians",
        "choose agents",
        "choose musicians",
        "discuss agents",
        "discuss musicians",
        "agent mandates",
        "musician mandates",
        "plan agents",
        "plan musicians",
        "who should we spawn",
        "who to spawn",
        "which should be spawned",
    )
    if any(phrase in lowered for phrase in planning_phrases):
        return True
    if ("agent" in lowered or "musician" in lowered or "ensemble" in lowered) and (
        "which" in lowered or "what" in lowered
    ):
        return True
    return False


def run_orchestra_cleanup(*, renderer: Any, repo_root: Path) -> int:
    tmux = TmuxManager(session_name="ai-orch-cleanup", repo_root=repo_root)
    try:
        tmux.ensure_session()
    except TmuxError as exc:
        renderer.display_error(f"orchestrator cleanup requires tmux: {exc}")
        return 1

    if not tmux.uses_current_session():
        renderer.display_error("orchestrator cleanup must be run from inside tmux")
        return 1

    closed = tmux.close_excess_panes()
    renderer.display_info(f"Closed {closed} excess pane(s); kept current pane.")
    return 0


def run_orchestra_mode(
    *,
    renderer: Any,
    config: dict[str, Any],
    default_model: str,
    repo_root: Path,
) -> int:
    runtime = OrchestraRuntime(repo_root=repo_root)
    session_name = f"ai-orch-{runtime.run_id}"
    tmux = TmuxManager(session_name=session_name, repo_root=repo_root)

    try:
        tmux.ensure_session()
        tmux.focus_orchestrator_pane()
        if not tmux.uses_current_session():
            renderer.display_info(
                f"tmux session '{session_name}' created in background. Attach with: tmux attach -t {session_name}"
            )
    except TmuxError as exc:
        renderer.display_error(f"orchestrator mode requires tmux: {exc}")
        return 1

    scheduler = OrchestraScheduler(runtime=runtime, tmux=tmux)
    engine = AIEngine(
        renderer=renderer,
        config=config,
        default_model=default_model,
        mode="orchestrator",
        orchestra_runtime=runtime,
        orchestra_scheduler=scheduler,
    )

    renderer.display_info(
        "Orchestrator mode started. Define mandates, dispatch musicians, and synthesize results."
    )

    while True:
        instruction = renderer.prompt_follow_up()
        if instruction is None:
            return 0
        instruction = instruction.strip()
        if not instruction:
            renderer.display_info("Provide an orchestration instruction or press Ctrl+D.")
            continue
        if instruction == NEW_CONVERSATION_TOKEN:
            renderer.display_info("Starting a fresh orchestration turn.")
            continue
        user_instruction = instruction
        if _is_agent_planning_discussion(user_instruction):
            instruction = (
                "The user is discussing which musicians/agents should be spawned. "
                "For this turn, discuss recommendations only and do not dispatch musicians unless explicitly asked to execute.\n\n"
                + user_instruction
            )
        else:
            reset = scheduler.reset_for_new_task()
            if reset.get("closed_panes") or reset.get("cancelled_assignments"):
                renderer.display_info(
                    "Reset previous musicians: "
                    f"closed {reset.get('closed_panes', 0)} panes, "
                    f"cancelled {reset.get('cancelled_assignments', 0)} assignments."
                )
            instruction = (
                "For this task, you must spawn a fresh musician ensemble. "
                "Compose mandates, dispatch musicians, collect outputs, then synthesize.\n\n"
                + user_instruction
            )
        renderer.display_user_prompt(user_instruction)
        rc = engine.run_conversation(instruction, None, display_prompt=False)
        if rc != 0:
            return rc
