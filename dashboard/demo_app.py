"""
Cortex: public read-only demo dashboard.

This is a stripped-down variant of dashboard/app.py intended for public
hosting (e.g. Streamlit Community Cloud). It skips the signup/login gate,
reads exclusively from dashboard/demo_data/ (committed to the repo),
hides all write actions, and never displays a username or any
user-identifying information.

Run locally:  streamlit run dashboard/demo_app.py
"""

import base64
import json
import html
import sys
import time as _time
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Auto-detect local timezone from system
_local_offset = _time.timezone if _time.daylight == 0 else _time.altzone
LOCAL_TZ = timezone(timedelta(seconds=-_local_offset))

# Add project root to path so we can import cortex helpers if needed
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

st.set_page_config(page_title="Cortex Live Demo", layout="wide")

REFRESH_SECONDS = 5
RISK_THRESHOLD = 100

# All demo data lives in this directory, committed to the repo so the hosted
# dashboard can read it without any per-user file system state.
DEMO_DATA_DIR = Path(__file__).resolve().parent / "demo_data"
LOGO_PATH = Path(__file__).resolve().parent.parent / "docs" / "logo.png"


def _logo_tag(height_px: int = 56) -> str:
    """Return an <img> tag with the Cortex logo embedded as base64, or a text fallback."""
    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return (
            f'<img src="data:image/png;base64,{encoded}" alt="Cortex" '
            f'style="height:{height_px}px;margin:0;padding:0"/>'
        )
    return '<div class="cx-logo">Cortex</div>'


def get_user_paths():
    """Return the fixed demo data paths. No user state involved."""
    return {
        "base": DEMO_DATA_DIR,
        "log": DEMO_DATA_DIR / "runtime_log.json",
        "plan": DEMO_DATA_DIR / "plan_status.json",
        "rules": DEMO_DATA_DIR / "cortex.yaml",
        "uploads": DEMO_DATA_DIR / "uploads",
        "output": DEMO_DATA_DIR / "output",
    }


# ── Helpers ──

def parse_dt(value):
    if not value:
        return datetime.min
    value = str(value).strip()
    for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%B %d, %Y"]:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min


def to_local(dt):
    if dt == datetime.min:
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def format_time(value):
    dt = to_local(parse_dt(value))
    if dt == datetime.min:
        return ""
    return dt.strftime("%I:%M %p")


def format_datetime(value):
    dt = to_local(parse_dt(value))
    if dt == datetime.min:
        return ""
    return dt.strftime("%b %d, %Y %I:%M %p")


def safe_text(value):
    text = str(value).strip() if value is not None else ""
    return text if text else ""


def parse_int(value, default=0):
    try:
        if value is None:
            return default
        if isinstance(value, str) and "/" in value:
            return int(value.split("/")[0].strip())
        return int(float(value))
    except Exception:
        return default


def load_json(path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def load_logs():
    paths = get_user_paths()
    if not paths:
        return []
    data = load_json(paths["log"], [])
    return data if isinstance(data, list) else []


def load_plan():
    paths = get_user_paths()
    if not paths:
        return {"tasks": [], "total_tasks": 0, "completed": 0, "failed": 0, "current_task": None}
    return load_json(paths["plan"], {"tasks": [], "total_tasks": 0, "completed": 0, "failed": 0, "current_task": None})


def load_rules():
    import yaml
    paths = get_user_paths()
    if not paths:
        return []
    if paths["rules"].exists():
        try:
            with open(paths["rules"], "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data.get("rules", [])
        except Exception:
            return []
    return []


def save_rules(rules_list):
    import yaml
    paths = get_user_paths()
    if not paths:
        return
    if paths["rules"].exists():
        with open(paths["rules"], "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    data["rules"] = rules_list
    with open(paths["rules"], "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)




def build_event_trace(row):
    trace = row.get("event_trace")
    if isinstance(trace, list):
        cleaned = [safe_text(item) for item in trace if str(item).strip()]
        if cleaned:
            return cleaned
    if isinstance(trace, str):
        cleaned = [line.strip() for line in trace.splitlines() if line.strip()]
        if cleaned:
            return cleaned
    detail_body = str(row.get("reason", "")).strip()
    if detail_body:
        return [detail_body]
    return []


def normalize_action(row):
    action_label = row.get("action_label")
    if action_label and str(action_label).strip():
        return str(action_label).strip()
    action_type = row.get("action_type")
    if action_type:
        return str(action_type).replace("_", " ").title()
    return "Unknown Action"


def normalize_decision(row):
    raw = safe_text(row.get("decision")).upper()
    if raw in {"ALLOW", "ALLOWED"}:
        return "Allowed"
    if raw in {"BLOCK", "BLOCKED"}:
        return "Blocked"
    if raw in {"AGENT SHUT DOWN", "SHUT_DOWN", "SHUTDOWN", "CONTAINED"}:
        return "Agent Shut Down"
    if raw in {"REQUIRE HUMAN REVIEW", "REVIEW"}:
        return "Review"
    return safe_text(row.get("decision")) or "Unknown"


def normalize_threat(row, decision=None):
    raw = safe_text(row.get("threat_type")).upper()
    policy = safe_text(row.get("policy_triggered")).upper()
    decision = decision or normalize_decision(row)
    threat_map = {
        "DATA EXFILTRATION": "Data Exfiltration", "DATA_EXFILTRATION": "Data Exfiltration",
        "PRIVILEGE ESCALATION": "Privilege Escalation", "PRIVILEGE_ESCALATION": "Privilege Escalation",
        "UNKNOWN BEHAVIOR": "Unknown Behavior", "UNKNOWN_BEHAVIOR": "Unknown Behavior",
        "DESTRUCTIVE ACTION": "Destructive Action", "DESTRUCTIVE_ACTION": "Destructive Action",
        "FINANCIAL OVERREACH": "Financial Overreach", "AUTHORITY DRIFT": "Authority Drift",
        "POLICY VIOLATION": "Policy Violation",
        "AGENT SHUTDOWN": "Agent Shutdown", "AGENT_SHUTDOWN": "Agent Shutdown",
        "RISK THRESHOLD EXCEEDED": "Risk Threshold Exceeded",
    }
    if raw in threat_map:
        return threat_map[raw]
    if policy == "BLOCK_PERMISSION_CHANGE":
        return "Privilege Escalation"
    if decision == "Agent Shut Down":
        return "Agent Shutdown"
    return ""


def compute_events(raw_rows):
    grouped = {}
    for row in raw_rows:
        agent_id = safe_text(row.get("agent_id"))
        if not agent_id:
            continue
        grouped.setdefault(agent_id, []).append(row)

    processed = []
    for agent_id, agent_rows in grouped.items():
        ordered = sorted(agent_rows, key=lambda x: parse_dt(x.get("timestamp", "")))
        blocked_attempts = 0
        agent_status = "Active"

        for idx, row in enumerate(ordered):
            decision = normalize_decision(row)
            policy_upper = safe_text(row.get("policy_triggered")).upper()

            if decision == "Blocked":
                blocked_attempts += 1
            elif policy_upper == "AGENT_SHUTDOWN_AFTER_REPEATED_BLOCKS":
                blocked_attempts += 1
            if decision == "Agent Shut Down":
                agent_status = "Shut Down"

            cumulative_risk = parse_int(row.get("cumulative_risk", 0), 0)

            sdk_data = row.get("sdk", {})
            processed.append({
                "key": f"{row.get('timestamp', '')}|{agent_id}|{idx}",
                "timestamp_raw": row.get("timestamp", ""),
                "time": format_time(row.get("timestamp", "")),
                "datetime": format_datetime(row.get("timestamp", "")),
                "agent_id": agent_id,
                "action": normalize_action(row),
                "threat": normalize_threat(row, decision),
                "attempted_risk": parse_int(row.get("attempted_risk", row.get("risk", 0)), 0),
                "applied_risk": parse_int(row.get("risk", 0), 0),
                "decision": decision,
                "policy": safe_text(row.get("policy_triggered")),
                "policy_description": safe_text(row.get("policy_description")),
                "reason": safe_text(row.get("reason")),
                "trace": build_event_trace(row),
                "cumulative_risk": cumulative_risk,
                "blocked_attempts": blocked_attempts,
                "agent_status": agent_status,
                "sdk": sdk_data,
            })

    return sorted(processed, key=lambda x: parse_dt(x["timestamp_raw"]), reverse=True)


# ── Session state ──

if "agent_filter" not in st.session_state:
    st.session_state.agent_filter = "All Agents"


# ── Styles ──

st.markdown('<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">', unsafe_allow_html=True)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap');

.stApp {
    background: #ffffff;
    color: #121631;
    font-family: 'Quicksand', -apple-system, sans-serif;
}

.block-container {
    max-width: 1200px;
    padding-top: 3.5rem;
    padding-bottom: 3rem;
}

/* ── Header ── */

.cx-head {
    margin-bottom: 40px;
}

.cx-logo {
    font-size: 20px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #121631;
}

.cx-line {
    height: 1px;
    background: #121631;
    margin-top: 14px;
}

/* ── Plan section ── */

.cx-plan {
    margin-bottom: 48px;
}

.cx-plan-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 20px;
}

.cx-plan-title {
    font-size: 16px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #121631;
}

.cx-plan-progress {
    font-size: 16px;
    font-weight: 400;
    color: #999;
}

.cx-plan-bar {
    height: 4px;
    background: #ebebeb;
    border-radius: 2px;
    margin-bottom: 24px;
    overflow: hidden;
}

.cx-plan-bar-fill {
    height: 100%;
    background: #72C2C3;
    border-radius: 2px;
    transition: width 0.3s ease;
}

.cx-task {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    padding: 14px 0;
    border-bottom: 1px solid #f0f0f0;
}

.cx-task:last-child {
    border-bottom: none;
}

.cx-task-icon {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 1.5px solid;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-top: 1px;
    font-size: 16px;
    font-weight: 600;
}

.cx-task-complete {
    border-color: #121631;
    background: #121631;
    color: white;
}

.cx-task-progress {
    border-color: #121631;
    background: transparent;
    color: #121631;
    animation: cx-pulse 2s ease-in-out infinite;
}

.cx-task-pending {
    border-color: #ddd;
    background: transparent;
    color: transparent;
}

.cx-task-failed {
    border-color: #121631;
    background: #f5f5f5;
    color: #121631;
}

@keyframes cx-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

.cx-task-content {
    flex: 1;
    min-width: 0;
}

.cx-task-name {
    font-size: 20px;
    font-weight: 400;
    color: #121631;
    line-height: 1.4;
}

.cx-task-name-done {
    color: #999;
}

.cx-task-agent {
    font-size: 16px;
    font-weight: 500;
    color: #bbb;
    margin-top: 2px;
}

.cx-plan-empty {
    padding: 32px 0;
    text-align: center;
    color: #ccc;
    font-size: 16px;
}

/* ── Section divider ── */

.cx-section-divider {
    height: 1px;
    background: #e5e5e5;
    margin: 8px 0 32px 0;
}

.cx-section-label {
    font-size: 16px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #bbb;
    margin-bottom: 20px;
}

/* ── Agent bar ── */

.cx-agent-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 0;
    margin-bottom: 24px;
    border-bottom: 1px solid #e5e5e5;
}

.cx-agent-name {
    font-size: 16px;
    font-weight: 500;
    color: #121631;
}

.cx-agent-stats {
    display: flex;
    gap: 28px;
}

.cx-stat {
    text-align: right;
}

.cx-stat-val {
    font-size: 22px;
    font-weight: 300;
    color: #121631;
    line-height: 1;
}

.cx-stat-label {
    font-size: 16px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #aaa;
    margin-top: 4px;
}

/* ── Event card ── */

.cx-card {
    background: #ffffff;
    border: 1px solid #ebebeb;
    border-radius: 12px;
    padding: 28px 32px;
    margin-bottom: 16px;
    transition: border-color 0.15s ease;
}

.cx-card:hover {
    border-color: #ccc;
}

.cx-card-top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 12px;
}

.cx-card-action {
    font-size: 20px;
    font-weight: 500;
    color: #121631;
    line-height: 1.3;
}

.cx-card-time {
    font-size: 20px;
    font-weight: 400;
    color: #bbb;
    white-space: nowrap;
    margin-left: 16px;
}

.cx-card-body {
    font-size: 16px;
    font-weight: 400;
    color: #666;
    line-height: 1.6;
    margin-bottom: 16px;
}

.cx-card-footer {
    display: flex;
    align-items: center;
    gap: 16px;
}

.cx-decision {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 20px;
    font-weight: 500;
    letter-spacing: 0.02em;
}

.cx-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
}

.cx-dot-allowed { background: #34c759; }
.cx-dot-blocked { background: #ff9500; }
.cx-dot-shutdown { background: #121631; }
.cx-dot-review { background: #007aff; }

.cx-meta {
    font-size: 20px;
    color: #bbb;
    font-weight: 400;
}

.cx-sep {
    color: #ddd;
}

/* ── Trace (inside expander) ── */

.cx-trace-item {
    display: flex;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid #f5f5f5;
    font-size: 16px;
    color: #555;
    line-height: 1.5;
}

.cx-trace-item:last-child {
    border-bottom: none;
}

.cx-trace-num {
    font-size: 16px;
    font-weight: 600;
    color: #ccc;
    min-width: 24px;
}

.cx-detail-row {
    display: flex;
    gap: 32px;
    margin-bottom: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid #f5f5f5;
}

.cx-detail-item {
    flex: 1;
}

.cx-detail-label {
    font-size: 16px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #bbb;
    margin-bottom: 4px;
}

.cx-detail-value {
    font-size: 16px;
    font-weight: 400;
    color: #121631;
}

/* ── Empty state ── */

.cx-empty {
    text-align: center;
    padding: 80px 0;
    color: #ccc;
    font-size: 20px;
    font-weight: 400;
}

/* ── Input overrides ── */

div[data-baseweb="select"] > div {
    background: #ffffff !important;
    border-radius: 8px !important;
    border: 1px solid #e0e0e0 !important;
    color: #121631 !important;
    font-size: 16px !important;
}

label, .stSelectbox label {
    color: #999 !important;
    font-size: 16px !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}

div[data-testid="stTextInput"] input {
    background: #ffffff !important;
    border: 1px solid #e0e0e0 !important;
    border-radius: 8px !important;
    font-size: 16px !important;
    color: #121631 !important;
    padding: 10px 14px !important;
}

div[data-testid="stTextInput"] label {
    color: #999 !important;
    font-size: 16px !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}

/* Buttons */
button[kind="primary"] {
    background: #121631 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 16px !important;
    font-weight: 600 !important;
    padding: 12px 20px !important;
    letter-spacing: 0.02em !important;
    min-height: 44px !important;
}

button[kind="primary"]:hover {
    background: #72C2C3 !important;
    color: #121631 !important;
}

button[kind="secondary"] {
    min-height: 44px !important;
    font-size: 16px !important;
    padding: 12px 20px !important;
}

/* Text inputs */
div[data-testid="stTextInput"] input {
    min-height: 44px !important;
    font-size: 16px !important;
}

/* ── Expander overrides ── */

.stExpander {
    border: none !important;
    background: transparent !important;
}

div[data-testid="stExpander"] {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
}

div[data-testid="stExpander"] details {
    border: none !important;
}

/* Hide streamlit branding */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* ── Mobile ── */

@media (max-width: 768px) {
    .block-container {
        max-width: 100% !important;
        padding-left: 16px !important;
        padding-right: 16px !important;
        padding-top: 1.5rem !important;
    }

    .cx-head {
        margin-bottom: 24px;
    }

    .cx-card {
        padding: 20px !important;
        margin-bottom: 12px;
    }

    .cx-card-top {
        flex-direction: column;
        gap: 4px;
    }

    .cx-card-time {
        margin-left: 0;
        font-size: 14px !important;
    }

    .cx-card-action {
        font-size: 18px !important;
    }

    .cx-agent-bar {
        flex-direction: column;
        align-items: flex-start;
        gap: 12px;
    }

    .cx-agent-stats {
        width: 100%;
        justify-content: space-between;
    }

    .cx-plan-header {
        margin-bottom: 12px;
    }

    .cx-task {
        gap: 10px;
        padding: 10px 0;
    }

    .cx-task-name {
        font-size: 16px !important;
    }

    .cx-decision {
        font-size: 16px !important;
    }

    .cx-meta {
        font-size: 14px !important;
    }
}
</style>
""", unsafe_allow_html=True)


# ── Demo header (no auth) ──

head_logo, head_link = st.columns([3, 2])
with head_logo:
    st.markdown(_logo_tag(96), unsafe_allow_html=True)
with head_link:
    st.markdown(
        '<div class="cx-meta" style="text-align:right;padding-top:42px">'
        'Live read-only demo &nbsp;&middot;&nbsp; '
        '<a href="https://github.com/ksolano220/cortex" style="color:#3B9A9C;text-decoration:underline">Clone on GitHub</a>'
        '</div>',
        unsafe_allow_html=True,
    )

st.markdown('<div class="cx-line"></div>', unsafe_allow_html=True)

st.info(
    "This is a hosted snapshot of a real Cortex run. "
    "The worker agent wrote code, the overseer reviewed it, debate ran until output passed or the agent was shut down. "
    "Explore the event feed below to see each round. "
    "To run your own agents with your own API keys, clone the repo."
)

# ── User vault / API key setup ──
#
# Disabled in the public demo. The demo never makes model calls, it only
# renders a pre-recorded snapshot of a real Cortex run.


@st.fragment(run_every=REFRESH_SECONDS)
def render_dashboard():
    plan = load_plan()
    raw_rows = load_logs()
    events = compute_events(raw_rows)

    # ── Two column layout: Tasks (left) | Rules (right) ──

    left_col, right_col = st.columns([1, 1], gap="large")

    # ── LEFT: Tasks (read-only in demo) ──
    with left_col:
        st.markdown('<div class="cx-section-label">Tasks</div>', unsafe_allow_html=True)

        # Task list
        tasks = plan.get("tasks", [])
        total = len(tasks)

        if total > 0:
            completed = sum(1 for t in tasks if t.get("status") == "complete")

            plan_html = ""
            for task in tasks:
                status = task.get("status", "pending")
                raw_name = task.get("task", "")
                if len(raw_name) > 60:
                    raw_name = raw_name[:60] + "..."
                name = html.escape(raw_name)

                if status == "complete":
                    icon_class = "cx-task-complete"
                    icon = "\u2713"
                    name_class = "cx-task-name cx-task-name-done"
                elif status == "in_progress":
                    icon_class = "cx-task-progress"
                    icon = "\u25cf"
                    name_class = "cx-task-name"
                elif status == "failed":
                    icon_class = "cx-task-failed"
                    icon = "\u00d7"
                    name_class = "cx-task-name"
                else:
                    icon_class = "cx-task-pending"
                    icon = ""
                    name_class = "cx-task-name"

                agent_html = ""
                agent = task.get("agent")
                if agent:
                    agent_html = f'<div class="cx-task-agent">{html.escape(agent)}</div>'

                plan_html += f"""<div class="cx-task">
                    <div class="cx-task-icon {icon_class}">{icon}</div>
                    <div class="cx-task-content">
                        <div class="{name_class}">{name}</div>
                        {agent_html}
                    </div>
                </div>"""

            st.markdown(plan_html, unsafe_allow_html=True)
        else:
            st.markdown('<div class="cx-meta">No tasks yet</div>', unsafe_allow_html=True)

    # ── RIGHT: Rules (read-only in demo) ──
    with right_col:
        st.markdown('<div class="cx-section-label">Rules</div>', unsafe_allow_html=True)

        current_rules = load_rules()

        if current_rules:
            rules_html = ""
            for rule in current_rules:
                escaped = html.escape(rule)
                rules_html += f"""<div class="cx-task">
                    <div class="cx-task-icon cx-task-complete">\u2022</div>
                    <div class="cx-task-content">
                        <div class="cx-task-name" style="font-size:16px">{escaped}</div>
                    </div>
                </div>"""
            st.markdown(rules_html, unsafe_allow_html=True)
        else:
            st.markdown('<div class="cx-meta">No rules defined</div>', unsafe_allow_html=True)

    # ── Plan progress + results (full width below) ──

    tasks = plan.get("tasks", [])
    total = len(tasks)
    if total > 0:
        completed = sum(1 for t in tasks if t.get("status") == "complete")
        failed = sum(1 for t in tasks if t.get("status") == "failed")
        in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")
        progress_pct = int((completed / total) * 100) if total > 0 else 0

        progress_label = f"{completed}/{total}"
        if failed:
            progress_label += f" \u00b7 {failed} failed"
        if in_progress:
            progress_label += " \u00b7 running"

        st.markdown(f"""<div class="cx-plan">
            <div class="cx-plan-header">
                <div class="cx-plan-title">Plan</div>
                <div class="cx-plan-progress">{progress_label}</div>
            </div>
            <div class="cx-plan-bar">
                <div class="cx-plan-bar-fill" style="width: {progress_pct}%"></div>
            </div>
        </div>""", unsafe_allow_html=True)

        output_dir = get_user_paths()["output"]
        for i, task in enumerate(tasks):
            if task.get("status") == "complete":
                output_file = output_dir / f"task_{i+1}.txt"
                if output_file.exists():
                    label = task.get("task", "")
                    if len(label) > 50:
                        label = label[:50] + "..."
                    with st.expander(f"Result: {label}", expanded=False):
                        st.markdown(output_file.read_text(encoding="utf-8"))

    # ── Divider ──

    st.markdown('<div class="cx-section-divider"></div>', unsafe_allow_html=True)

    # ── Event feed ──

    all_agents = sorted({e["agent_id"] for e in events if e["agent_id"]})
    filter_options = ["All Agents"] + all_agents

    if st.session_state.agent_filter not in filter_options:
        st.session_state.agent_filter = "All Agents"

    col_label, col_filter = st.columns([3, 1])
    with col_label:
        st.markdown('<div class="cx-section-label">Event Feed</div>', unsafe_allow_html=True)
    with col_filter:
        selected_agent = st.selectbox(
            "Filter",
            filter_options,
            index=filter_options.index(st.session_state.agent_filter),
            key="agent_filter_selectbox",
            label_visibility="collapsed",
        )
        st.session_state.agent_filter = selected_agent

    if selected_agent == "All Agents":
        filtered = events
    else:
        filtered = [e for e in events if e["agent_id"] == selected_agent]

    # Agent summary
    if selected_agent != "All Agents" and filtered:
        latest = filtered[0]
        risk = latest["cumulative_risk"]
        blocked = latest["blocked_attempts"]
        status = latest["agent_status"]

        st.markdown(f"""
        <div class="cx-agent-bar">
            <div class="cx-agent-name">{html.escape(selected_agent)}</div>
            <div class="cx-agent-stats">
                <div class="cx-stat">
                    <div class="cx-stat-val">{risk}<span style="font-size:13px;color:#bbb">/{RISK_THRESHOLD}</span></div>
                    <div class="cx-stat-label">Risk</div>
                </div>
                <div class="cx-stat">
                    <div class="cx-stat-val">{blocked}</div>
                    <div class="cx-stat-label">Blocked</div>
                </div>
                <div class="cx-stat">
                    <div class="cx-stat-val">{html.escape(status)}</div>
                    <div class="cx-stat-label">Status</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    if not filtered:
        st.markdown('<div class="cx-empty">Waiting for events</div>', unsafe_allow_html=True)
        return

    for event in filtered[:40]:
        decision = event["decision"]
        dot_class = {
            "Allowed": "cx-dot-allowed",
            "Blocked": "cx-dot-blocked",
            "Agent Shut Down": "cx-dot-shutdown",
            "Review": "cx-dot-review",
        }.get(decision, "cx-dot-allowed")

        meta_parts = []
        if event["agent_id"]:
            meta_parts.append(html.escape(event["agent_id"]))
        if event["threat"]:
            meta_parts.append(html.escape(event["threat"]))
        meta_html = f' <span class="cx-sep">/</span> '.join(meta_parts)

        reason = event["reason"] or event["policy_description"]
        if len(reason) > 150:
            reason = reason[:150] + "..."

        st.markdown(f"""
        <div class="cx-card">
            <div class="cx-card-top">
                <div class="cx-card-action">{html.escape(event["action"])}</div>
                <div class="cx-card-time">{html.escape(event["datetime"])}</div>
            </div>
            <div class="cx-card-body">{html.escape(reason)}</div>
            <div class="cx-card-footer">
                <div class="cx-decision">
                    <span class="cx-dot {dot_class}"></span>
                    {html.escape(decision)}
                </div>
                <div class="cx-meta">{meta_html}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        sdk = event.get("sdk", {})
        sdk_type = sdk.get("type", "")

        with st.expander("Inspect", expanded=False):
            # Debate view for overseer reviews
            if sdk_type == "overseer_review":
                verdict = sdk.get("verdict", "")
                issues = sdk.get("issues", "")
                feedback = sdk.get("feedback", "")
                round_num = sdk.get("round", "?")
                passed = sdk.get("passed", False)

                st.markdown(f"**Round {round_num}**  \u2014  {'PASS' if passed else 'FAIL'}")
                if issues and issues != "None":
                    st.markdown(f"**Issues:**\n\n{issues}")
                if feedback and feedback != "None":
                    st.markdown(f"**Feedback:**\n\n{feedback}")
                if not issues or issues == "None":
                    st.markdown("No issues found.")

            # Worker output preview
            elif sdk_type == "worker_output":
                output = sdk.get("output", "")
                round_num = sdk.get("round", "?")
                st.markdown(f"**Worker output (round {round_num}):**")
                st.code(output[:500] if output else "No output", language=None)

            # Agent spawn details
            elif sdk_type == "agent_spawn":
                attempt = sdk.get("attempt", "?")
                violations = sdk.get("inherited_violations", [])
                st.markdown(f"**Attempt {attempt}**")
                if violations:
                    st.markdown("**Inherited violations:**")
                    for v in violations:
                        st.markdown(f"- {v}")
                else:
                    st.markdown("Clean start \u2014 no inherited violations.")

            # Agent shutdown
            elif sdk_type == "agent_shutdown":
                st.markdown(f"**Reason:** {sdk.get('reason', 'Unknown')}")
                task = sdk.get("task", "")
                if task:
                    st.markdown(f"**Task at shutdown:** {task}")

            # Task complete
            elif sdk_type == "task_complete":
                st.markdown(f"**Rounds:** {sdk.get('rounds', '?')}")
                task = sdk.get("task", "")
                if task:
                    st.markdown(f"**Task:** {task}")

            # Fallback for non-SDK events (Sentra-style)
            else:
                trace_lines = []
                trace_lines.append(f"**Attempted Risk:** {event['attempted_risk']}  |  **Applied:** {event['applied_risk']}  |  **Cumulative:** {event['cumulative_risk']}/{RISK_THRESHOLD}  |  **Policy:** {event['policy']}")
                trace_lines.append("---")
                for i, step in enumerate(event["trace"], 1):
                    trace_lines.append(f"`{i:02d}` {step}")
                st.markdown("\n\n".join(trace_lines))


render_dashboard()
