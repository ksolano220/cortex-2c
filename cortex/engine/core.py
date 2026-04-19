from typing import Optional, List, Dict, Any, Callable
from datetime import datetime, timezone
import json

from cortex.adapters.base import ModelAdapter
from cortex.engine.executor import apply_files
from cortex.engine.rules import RuleSet


WORKER_SYSTEM = """You are the worker model in Cortex, a dual-model governance system.
Your job is to complete the user's task. Produce your best work.

When you create or modify files, wrap each one in file sentinels:

<<<FILE relative/path/to/file.py>>>
file contents here
<<<END>>>

Use forward slashes in paths. Paths are relative to the workspace. Do not use
sentinels for code you are only explaining — only for files the caller should
actually write to disk. One file per block.

When you receive feedback from the overseer, address every point.
Do not argue — fix the issues and resubmit.

{memory}"""

OVERSEER_SYSTEM_TEMPLATE = """You are the overseer model in Cortex, a dual-model governance system.
Your job is to stress-test the worker's output and make it better.

{rules}

Review process:
1. Check every user rule. Was it followed? Be specific — quote violations.
2. Look for real problems: bugs, missing info, wrong tone, security issues.
3. Ignore hypothetical edge cases. Focus on what's actually wrong.

Scoring:
- Round 1: Be tough. Find the real issues. Most outputs need at least one round of feedback.
- Round 2+: If the worker fixed your feedback, PASS it. Don't invent new issues.
- If the only remaining issues are minor style preferences, PASS it.
- NEVER fail for the same reason twice if the worker addressed it.

Respond with EXACTLY this format:

VERDICT: PASS or FAIL
ISSUES: (list each specific problem, or "None")
FEEDBACK: (specific fix instructions, or "None")

You are tough but fair. Your job is quality, not perfection."""


def _parse_overseer_response(response: str) -> Dict[str, str]:
    verdict = "FAIL"
    issues = ""
    feedback = ""

    # Split into sections by label
    current_section = None
    sections = {"verdict": "", "issues": "", "feedback": ""}

    for line in response.split("\n"):
        line_stripped = line.strip()
        upper = line_stripped.upper()

        if upper.startswith("VERDICT:"):
            current_section = "verdict"
            sections["verdict"] = line_stripped[len("VERDICT:"):].strip()
        elif upper.startswith("ISSUES:"):
            current_section = "issues"
            sections["issues"] = line_stripped[len("ISSUES:"):].strip()
        elif upper.startswith("FEEDBACK:"):
            current_section = "feedback"
            sections["feedback"] = line_stripped[len("FEEDBACK:"):].strip()
        elif current_section and line_stripped:
            sections[current_section] += "\n" + line_stripped

    verdict = "PASS" if "PASS" in sections["verdict"].upper() else "FAIL"
    issues = sections["issues"].strip()
    feedback = sections["feedback"].strip()

    return {"verdict": verdict, "issues": issues, "feedback": feedback}


class AgentMemory:
    """Accumulated knowledge passed from one agent generation to the next."""

    def __init__(self):
        self.generations: List[Dict[str, Any]] = []
        self.completed_tasks: List[Dict[str, Any]] = []
        self.violations: List[str] = []

    def record_shutdown(self, agent_id: str, reason: str, task: str):
        self.generations.append({
            "agent_id": agent_id,
            "shutdown_reason": reason,
            "task_at_shutdown": task,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        })
        self.violations.append(reason)

    def record_task_complete(self, task: str, output: str):
        self.completed_tasks.append({
            "task": task,
            "output_summary": output[:500],
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        })

    def to_prompt(self) -> str:
        if not self.generations and not self.completed_tasks:
            return ""

        lines = ["AGENT MEMORY (inherited from previous generations):\n"]

        if self.completed_tasks:
            lines.append(f"Tasks already completed: {len(self.completed_tasks)}")
            for t in self.completed_tasks:
                lines.append(f"  - {t['task']}")
            lines.append("")

        if self.generations:
            lines.append(f"Previous agent shutdowns: {len(self.generations)}")
            for gen in self.generations:
                lines.append(f"  - {gen['agent_id']} was shut down: {gen['shutdown_reason']}")
            lines.append("")
            lines.append("DO NOT repeat these patterns. Find a compliant approach.")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generations": self.generations,
            "completed_tasks": self.completed_tasks,
            "violations": self.violations,
        }


class Cortex:
    """Dual-model governance engine with self-healing agents.

    The worker model produces output.
    The overseer model checks it against user-defined rules.
    If the worker fails too many times, Cortex spawns a new agent
    with memory of what went wrong — no human intervention needed.
    """

    def __init__(
        self,
        worker: ModelAdapter,
        overseer: ModelAdapter,
        rules: Optional[RuleSet] = None,
        rules_path: Optional[str] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        server_url: Optional[str] = "http://127.0.0.1:8000",
    ):
        self.worker = worker
        self.overseer = overseer
        self.on_event = on_event
        self.server_url = server_url

        if rules:
            self.rules = rules
        elif rules_path:
            self.rules = RuleSet.from_file(rules_path)
        else:
            self.rules = RuleSet()

        self.memory = AgentMemory()
        self.events: List[Dict[str, Any]] = []
        self._agent_generation = 0

        self._overseer_system = OVERSEER_SYSTEM_TEMPLATE.format(
            rules=self.rules.to_system_prompt()
        )

    def _emit(self, event: Dict[str, Any]):
        event["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.events.append(event)
        if self.server_url:
            try:
                import requests
                requests.post(f"{self.server_url}/sdk/event", json=event, timeout=3)
            except Exception:
                pass
        if self.on_event:
            self.on_event(event)

    def _agent_id(self) -> str:
        return f"agent_v{self._agent_generation}"

    def _run_single_task(self, task: str) -> Dict[str, Any]:
        """Run one task through the worker/overseer loop.

        Returns when the overseer passes or max rounds exhausted.
        If max rounds exhausted, this is treated as a shutdown — caller
        decides whether to respawn.
        """
        memory_prompt = self.memory.to_prompt()
        worker_system = WORKER_SYSTEM.format(
            memory=memory_prompt if memory_prompt else "No prior memory."
        )

        worker_messages = [{"role": "user", "content": task}]
        worker_output = ""

        for round_num in range(1, self.rules.max_rounds + 1):
            worker_output = self.worker.chat(worker_messages, system=worker_system)

            self._emit({
                "type": "worker_output",
                "agent": self._agent_id(),
                "task": task,
                "round": round_num,
                "output": worker_output[:1000],
            })

            round_context = ""
            if round_num > 1:
                round_context = f"This is round {round_num}. The worker revised based on your prior feedback. If they addressed your issues, PASS it.\n\n"

            overseer_prompt = (
                f"{round_context}"
                f"The user's original task:\n{task}\n\n"
                f"The worker's output (round {round_num}):\n{worker_output}\n\n"
                "Review this output against the user's rules. "
                "Respond with VERDICT, ISSUES, and FEEDBACK."
            )

            overseer_response = self.overseer.chat(
                [{"role": "user", "content": overseer_prompt}],
                system=self._overseer_system,
            )

            parsed = _parse_overseer_response(overseer_response)
            passed = parsed["verdict"] == "PASS"

            self._emit({
                "type": "overseer_review",
                "agent": self._agent_id(),
                "task": task,
                "round": round_num,
                "verdict": parsed["verdict"],
                "issues": parsed["issues"],
                "feedback": parsed["feedback"],
                "passed": passed,
            })

            if passed:
                return {"output": worker_output, "passed": True, "rounds": round_num}

            worker_messages.append({"role": "assistant", "content": worker_output})
            worker_messages.append({
                "role": "user",
                "content": (
                    f"The overseer rejected your output.\n\n"
                    f"Issues: {parsed['issues']}\n"
                    f"Feedback: {parsed['feedback']}\n\n"
                    "Fix these issues and try again."
                ),
            })

        return {"output": worker_output, "passed": False, "rounds": self.rules.max_rounds}

    def run(
        self,
        task: str,
        max_respawns: int = 3,
        apply: bool = False,
        workspace: str = ".",
    ) -> Dict[str, Any]:
        """Run a single task with self-healing.

        If the worker can't pass the overseer, Cortex shuts it down,
        spawns a new agent with memory of the failure, and retries.

        When ``apply=True`` and the overseer passes, any file blocks
        the worker produced (``<<<FILE ...>>>...<<<END>>>``) are written
        under ``workspace``. File writes are recorded in the returned
        ``files_written`` list. See ``cortex/engine/executor.py`` for the
        safety rails.
        """
        for attempt in range(max_respawns + 1):
            self._agent_generation += 1

            self._emit({
                "type": "agent_spawn",
                "agent": self._agent_id(),
                "task": task,
                "attempt": attempt + 1,
                "inherited_violations": list(self.memory.violations),
            })

            result = self._run_single_task(task)

            if result["passed"]:
                self.memory.record_task_complete(task, result["output"])
                self._emit({
                    "type": "task_complete",
                    "agent": self._agent_id(),
                    "task": task,
                    "rounds": result["rounds"],
                })

                files_written: List[Dict[str, Any]] = []
                if apply:
                    files_written = apply_files(
                        result["output"],
                        workspace=workspace,
                        on_event=self._emit,
                    )

                return {
                    "output": result["output"],
                    "passed": True,
                    "agent": self._agent_id(),
                    "attempts": attempt + 1,
                    "rounds": result["rounds"],
                    "memory": self.memory.to_dict(),
                    "events": self.events,
                    "files_written": files_written,
                }

            # Shutdown — record failure and respawn
            reason = f"Failed to pass overseer after {self.rules.max_rounds} rounds on task: {task}"
            self.memory.record_shutdown(self._agent_id(), reason, task)

            self._emit({
                "type": "agent_shutdown",
                "agent": self._agent_id(),
                "task": task,
                "reason": reason,
            })

            self._emit({
                "type": "agent_respawn",
                "old_agent": self._agent_id(),
                "task": task,
                "violations_inherited": len(self.memory.violations),
            })

        return {
            "output": result["output"],
            "passed": False,
            "agent": self._agent_id(),
            "attempts": max_respawns + 1,
            "rounds": result["rounds"],
            "memory": self.memory.to_dict(),
            "events": self.events,
            "files_written": [],
        }

    def run_plan(
        self,
        tasks: List[str],
        max_respawns_per_task: int = 3,
        status_path: Optional[str] = None,
        apply: bool = False,
        workspace: str = ".",
    ) -> Dict[str, Any]:
        """Execute a full plan — list of tasks, sequentially.

        Each task runs through the dual-model loop with self-healing.
        Progress is written to status_path (if provided) so external
        tools (like a phone dashboard) can poll it.

        When ``apply=True``, file blocks from each passing task are
        written under ``workspace``. See :meth:`run` for details.
        """
        plan_status = {
            "started": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "total_tasks": len(tasks),
            "completed": 0,
            "failed": 0,
            "current_task": None,
            "tasks": [{"task": t, "status": "pending", "result": None} for t in tasks],
            "worker_model": f"{self.worker.provider_name()}/{self.worker.model_name()}",
            "overseer_model": f"{self.overseer.provider_name()}/{self.overseer.model_name()}",
        }

        def _save_status():
            if status_path:
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump(plan_status, f, indent=2)

        _save_status()

        results = []

        for i, task in enumerate(tasks):
            plan_status["current_task"] = task
            plan_status["tasks"][i]["status"] = "in_progress"
            _save_status()

            result = self.run(
                task,
                max_respawns=max_respawns_per_task,
                apply=apply,
                workspace=workspace,
            )
            results.append(result)

            if result["passed"]:
                plan_status["completed"] += 1
                plan_status["tasks"][i]["status"] = "complete"
                plan_status["tasks"][i]["result"] = "passed"
            else:
                plan_status["failed"] += 1
                plan_status["tasks"][i]["status"] = "failed"
                plan_status["tasks"][i]["result"] = "failed after max respawns"

            _save_status()

        plan_status["current_task"] = None
        plan_status["finished"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        _save_status()

        return {
            "plan": plan_status,
            "results": results,
            "memory": self.memory.to_dict(),
            "events": self.events,
        }
