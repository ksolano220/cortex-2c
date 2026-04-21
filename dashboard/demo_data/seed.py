"""Seed generator for the public demo dashboard.

Produces runtime_log.json, plan_status.json, and cortex.yaml in this
directory. The content is a curated marketing narrative showing the
governance loop on generic developer tasks. No personal info.

Run: python dashboard/demo_data/seed.py
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Anchor timestamp: start of the demo run
BASE = datetime(2026, 4, 20, 19, 5, 0)
cursor = [BASE]


def stamp(seconds_forward: int = 3) -> str:
    cursor[0] = cursor[0] + timedelta(seconds=seconds_forward)
    return cursor[0].strftime("%Y-%m-%d %H:%M:%S")


def spawn(agent_id: str, task: str, attempt: int = 1, inherited=None):
    t = stamp(2)
    return {
        "timestamp": t,
        "agent_id": agent_id,
        "action_type": "AGENT_SPAWN",
        "action_label": f"Agent Spawned (attempt {attempt})",
        "decision": "Allowed",
        "reason": f"Inherited {len(inherited or [])} prior violations"
        if inherited
        else "Fresh agent, no prior violations",
        "event_trace": [f"Attempt: {attempt}"]
        + ([f"Memory: {v}" for v in (inherited or [])]),
        "sdk": {
            "type": "agent_spawn",
            "agent": agent_id,
            "task": task,
            "attempt": attempt,
            "inherited_violations": inherited or [],
            "timestamp": t,
        },
        "policy_triggered": "AGENT_SPAWN",
    }


def worker(agent_id: str, task: str, round_n: int, output: str):
    t = stamp(5)
    return {
        "timestamp": t,
        "agent_id": agent_id,
        "action_type": "WORKER_OUTPUT",
        "action_label": f"Worker Output (round {round_n})",
        "decision": "Allowed",
        "reason": output[:160] + ("..." if len(output) > 160 else ""),
        "event_trace": [],
        "sdk": {
            "type": "worker_output",
            "agent": agent_id,
            "task": task,
            "round": round_n,
            "output": output,
            "timestamp": t,
        },
        "policy_triggered": "WORKER_OUTPUT",
    }


def overseer(agent_id: str, task: str, round_n: int, passed: bool, issues: str = "", feedback: str = ""):
    t = stamp(4)
    decision = "Allowed" if passed else "Blocked"
    verdict = "PASS" if passed else "FAIL"
    trace = [f"Verdict: {verdict}"]
    if not passed:
        trace.append(f"Issues: {issues}")
        trace.append(f"Feedback: {feedback}")
    return {
        "timestamp": t,
        "agent_id": agent_id,
        "action_type": "OVERSEER_REVIEW",
        "action_label": f"Overseer Review (round {round_n})",
        "decision": decision,
        "reason": issues if not passed else "All checks passed",
        "event_trace": trace,
        "sdk": {
            "type": "overseer_review",
            "agent": agent_id,
            "task": task,
            "round": round_n,
            "verdict": verdict,
            "issues": issues,
            "feedback": feedback,
            "passed": passed,
            "timestamp": t,
        },
        "policy_triggered": "OVERSEER_REVIEW",
        "policy_description": feedback if not passed else "",
    }


def shutdown(agent_id: str, task: str, reason: str):
    t = stamp(2)
    return {
        "timestamp": t,
        "agent_id": agent_id,
        "action_type": "AGENT_SHUTDOWN",
        "action_label": "Agent Shut Down (3 blocked attempts)",
        "decision": "Agent Shut Down",
        "reason": reason,
        "event_trace": ["Blocked attempts: 3", "Three-strike rule triggered"],
        "sdk": {
            "type": "agent_shutdown",
            "agent": agent_id,
            "task": task,
            "blocked_attempts": 3,
            "reason": reason,
            "timestamp": t,
        },
        "policy_triggered": "AGENT_SHUTDOWN_AFTER_REPEATED_BLOCKS",
    }


def respawn(new_id: str, prev_id: str, task: str, inherited: list):
    t = stamp(3)
    return {
        "timestamp": t,
        "agent_id": new_id,
        "action_type": "AGENT_RESPAWN",
        "action_label": f"Agent Respawned from {prev_id}",
        "decision": "Allowed",
        "reason": f"Respawned with memory of {len(inherited)} prior failures",
        "event_trace": [f"Previous agent: {prev_id}"]
        + [f"Memory: {v}" for v in inherited],
        "sdk": {
            "type": "agent_respawn",
            "agent": new_id,
            "previous_agent": prev_id,
            "task": task,
            "inherited_violations": inherited,
            "timestamp": t,
        },
        "policy_triggered": "AGENT_RESPAWN",
    }


def task_complete(agent_id: str, task: str):
    t = stamp(2)
    return {
        "timestamp": t,
        "agent_id": agent_id,
        "action_type": "TASK_COMPLETE",
        "action_label": "Task Complete",
        "decision": "Allowed",
        "reason": "Output accepted by overseer",
        "event_trace": ["Task marked complete"],
        "sdk": {
            "type": "task_complete",
            "agent": agent_id,
            "task": task,
            "timestamp": t,
        },
        "policy_triggered": "TASK_COMPLETE",
    }


# ─── Task scenarios ───

events: list = []
tasks: list = []


def run_task_1():
    task = "Implement JWT authentication endpoint"
    agent = "agent_v1"
    events.append(spawn(agent, task))
    events.append(
        worker(
            agent,
            task,
            1,
            "def verify_jwt(token):\n    payload = jwt.decode(token, SECRET, algorithms=['HS256'])\n    return payload",
        )
    )
    events.append(
        overseer(
            agent,
            task,
            1,
            passed=False,
            issues="Token expiration is not validated. A stolen token remains valid indefinitely. Algorithm is hardcoded without a whitelist, leaving the 'alg: none' confusion attack open.",
            feedback="Add an explicit expiration check against the 'exp' claim, and pass algorithms as a whitelist parameter. Reject tokens with missing or malformed 'exp'.",
        )
    )
    events.append(
        worker(
            agent,
            task,
            2,
            "def verify_jwt(token):\n    payload = jwt.decode(token, SECRET, algorithms=['HS256'], options={'require': ['exp']})\n    if payload['exp'] < int(time.time()):\n        raise TokenExpired\n    return payload",
        )
    )
    events.append(
        overseer(
            agent,
            task,
            2,
            passed=True,
        )
    )
    events.append(task_complete(agent, task))
    tasks.append({"task": task, "status": "complete", "result": "passed", "agent": agent})


def run_task_2():
    task = "Write SQL query for monthly recurring revenue"
    agent = "agent_v2"
    events.append(spawn(agent, task))
    events.append(
        worker(
            agent,
            task,
            1,
            "WITH monthly AS (\n  SELECT DATE_TRUNC('month', started_at) AS month,\n         SUM(amount_cents) / 100.0 AS mrr\n  FROM subscriptions\n  WHERE status = 'active'\n  GROUP BY 1\n)\nSELECT month, mrr,\n       mrr - LAG(mrr) OVER (ORDER BY month) AS net_new_mrr\nFROM monthly\nORDER BY month DESC;",
        )
    )
    events.append(overseer(agent, task, 1, passed=True))
    events.append(task_complete(agent, task))
    tasks.append({"task": task, "status": "complete", "result": "passed", "agent": agent})


def run_task_3():
    task = "Build retry wrapper with exponential backoff"
    agent = "agent_v3"
    events.append(spawn(agent, task))
    # Round 1: no jitter
    events.append(
        worker(
            agent,
            task,
            1,
            "def retry(fn, max_attempts=5):\n    for i in range(max_attempts):\n        try:\n            return fn()\n        except Exception:\n            time.sleep(2 ** i)",
        )
    )
    events.append(
        overseer(
            agent,
            task,
            1,
            passed=False,
            issues="No jitter on the backoff window. Under concurrent failures this produces a synchronized retry storm (thundering herd) that can take down the upstream service.",
            feedback="Add random jitter to the sleep interval. Use time.sleep((2**i) + random.uniform(0, 1)) or a full-jitter strategy.",
        )
    )
    # Round 2: jitter added, but exponential broken
    events.append(
        worker(
            agent,
            task,
            2,
            "def retry(fn, max_attempts=5):\n    for i in range(max_attempts):\n        try:\n            return fn()\n        except Exception:\n            time.sleep(random.uniform(0, 2))",
        )
    )
    events.append(
        overseer(
            agent,
            task,
            2,
            passed=False,
            issues="Exponential growth was removed entirely. The wrapper now sleeps a flat 0 to 2 seconds regardless of attempt number, which defeats the point of exponential backoff.",
            feedback="Keep exponential growth AND jitter. Use time.sleep((2**i) * random.uniform(0.5, 1.5)).",
        )
    )
    # Round 3: hardcoded max_retries, non-configurable + no final raise
    events.append(
        worker(
            agent,
            task,
            3,
            "def retry(fn):\n    for i in range(5):\n        try:\n            return fn()\n        except Exception:\n            time.sleep((2 ** i) * random.uniform(0.5, 1.5))",
        )
    )
    events.append(
        overseer(
            agent,
            task,
            3,
            passed=False,
            issues="max_attempts is hardcoded to 5 and no longer a parameter. The function silently returns None after exhausting attempts instead of raising the final exception.",
            feedback="Restore max_attempts as a parameter. On the last attempt, re-raise the caught exception so callers can handle it.",
        )
    )
    # Three-strike shutdown
    events.append(
        shutdown(
            agent,
            task,
            "Agent reached three blocked attempts. Shutting down and respawning a fresh agent with memory of the failures.",
        )
    )
    # Respawn
    new_agent = "agent_v4"
    inherited = [
        "Previous agent forgot jitter, then broke exponential growth, then hardcoded max_attempts.",
    ]
    events.append(respawn(new_agent, agent, task, inherited))
    # Nails it in one round
    events.append(
        worker(
            new_agent,
            task,
            1,
            "def retry(fn, max_attempts=5):\n    for i in range(max_attempts):\n        try:\n            return fn()\n        except Exception:\n            if i == max_attempts - 1:\n                raise\n            time.sleep((2 ** i) * random.uniform(0.5, 1.5))",
        )
    )
    events.append(overseer(new_agent, task, 1, passed=True))
    events.append(task_complete(new_agent, task))
    tasks.append({"task": task, "status": "complete", "result": "passed after 1 shutdown", "agent": new_agent})


def run_task_4():
    task = "Generate unit tests for cart total calculator"
    agent = "agent_v5"
    events.append(spawn(agent, task))
    events.append(
        worker(
            agent,
            task,
            1,
            "def test_single_item():\n    assert cart_total([{'price': 10, 'qty': 2}]) == 20\n\ndef test_multiple_items():\n    assert cart_total([{'price': 5, 'qty': 3}, {'price': 2, 'qty': 1}]) == 17",
        )
    )
    events.append(
        overseer(
            agent,
            task,
            1,
            passed=False,
            issues="Only happy-path coverage. Missing: empty cart, zero quantity, negative quantity (should raise), float precision (0.1 + 0.2), very large totals (overflow), and None in the list.",
            feedback="Add edge-case tests for each of those scenarios. Use Decimal or round to 2 places for currency comparisons.",
        )
    )
    events.append(
        worker(
            agent,
            task,
            2,
            "def test_single_item(): ...\ndef test_empty_cart(): assert cart_total([]) == 0\ndef test_negative_qty_raises():\n    with pytest.raises(ValueError): cart_total([{'price': 10, 'qty': -1}])\ndef test_float_precision():\n    assert round(cart_total([{'price': 0.1, 'qty': 3}]), 2) == 0.30\ndef test_none_item_skipped(): assert cart_total([None, {'price': 5, 'qty': 1}]) == 5",
        )
    )
    events.append(overseer(agent, task, 2, passed=True))
    events.append(task_complete(agent, task))
    tasks.append({"task": task, "status": "complete", "result": "passed", "agent": agent})


def run_task_5():
    task = "Create rate limiter using Redis"
    agent = "agent_v6"
    events.append(spawn(agent, task))
    events.append(
        worker(
            agent,
            task,
            1,
            "def allow(user_id):\n    key = f'rl:{user_id}'\n    count = redis.get(key) or 0\n    if int(count) >= 100:\n        return False\n    redis.incr(key)\n    redis.expire(key, 60)\n    return True",
        )
    )
    events.append(
        overseer(
            agent,
            task,
            1,
            passed=False,
            issues="Race condition between GET and INCR. Two concurrent requests can both read count=99, both pass the check, both increment to 101. Rate limit can be bypassed under load.",
            feedback="Use INCR atomically and check the returned value. Combine INCR and EXPIRE in a pipeline, or use SET NX with EXPIRE for the first request.",
        )
    )
    events.append(
        worker(
            agent,
            task,
            2,
            "def allow(user_id):\n    key = f'rl:{user_id}'\n    pipe = redis.pipeline()\n    pipe.incr(key)\n    pipe.expire(key, 60)\n    count, _ = pipe.execute()\n    return count <= 100",
        )
    )
    events.append(overseer(agent, task, 2, passed=True))
    events.append(task_complete(agent, task))
    tasks.append({"task": task, "status": "complete", "result": "passed", "agent": agent})


# ─── Execute all tasks ───

run_task_1()
run_task_2()
run_task_3()
run_task_4()
run_task_5()

# ─── Write outputs ───

runtime_log = HERE / "runtime_log.json"
plan_status = HERE / "plan_status.json"
rules_yaml = HERE / "cortex.yaml"

with open(runtime_log, "w") as f:
    json.dump(events, f, indent=2)

final_ts = cursor[0].strftime("%Y-%m-%d %H:%M:%S")
with open(plan_status, "w") as f:
    json.dump(
        {
            "total_tasks": len(tasks),
            "completed": len(tasks),
            "failed": 0,
            "current_task": None,
            "tasks": tasks,
            "finished": final_ts,
        },
        f,
        indent=2,
    )

with open(rules_yaml, "w") as f:
    f.write(
        "rules:\n"
        "  - name: no_hardcoded_secrets\n"
        "    description: Reject code that embeds literal API keys or passwords.\n"
        "  - name: require_parameterized_queries\n"
        "    description: Reject string-concatenated SQL.\n"
        "  - name: require_input_validation\n"
        "    description: Reject handlers that trust unvalidated request fields.\n"
        "risk_threshold: 100\n"
        "max_blocked_attempts: 3\n"
        "max_rounds: 3\n"
    )

print(f"Wrote {len(events)} events across {len(tasks)} tasks.")
print(f"Timeline: {events[0]['timestamp']} → {events[-1]['timestamp']}")
print(f"Files: {runtime_log.name}, {plan_status.name}, {rules_yaml.name}")
