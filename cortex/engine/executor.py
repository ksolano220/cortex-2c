"""Apply worker output to disk.

Parses worker output for fenced file blocks of the form:

    <<<FILE relative/path/to/file.py>>>
    file contents
    <<<END>>>

and writes them to a workspace directory under explicit opt-in. Safety rails:
  - Paths must resolve inside the workspace root (no ../../etc/passwd)
  - Denylist of always-off paths (.git/, .env*, *.key, *.pem, .ssh/)
  - Absolute paths rejected
  - Creates parent directories as needed
  - Emits an event per attempted write (allowed or blocked)
"""

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


FILE_BLOCK_PATTERN = re.compile(
    r"<<<FILE\s+([^\n>]+?)>>>\n(.*?)\n<<<END>>>",
    re.DOTALL,
)

DENY_PATTERNS = [
    re.compile(r"^\.git(/|$)"),
    re.compile(r"^\.env"),
    re.compile(r"\.(key|pem|p12|pfx)$"),
    re.compile(r"^\.ssh(/|$)"),
    re.compile(r"^id_(rsa|ed25519|ecdsa)"),
]


def extract_files(output: str) -> List[Tuple[str, str]]:
    """Parse worker output for file blocks.

    Returns a list of (path, content) tuples in the order they appear.
    """
    return [
        (path.strip(), content)
        for path, content in FILE_BLOCK_PATTERN.findall(output)
    ]


def is_safe_path(path_str: str, workspace: Path) -> Tuple[bool, str]:
    """Check whether a path is safe to write inside `workspace`.

    Returns (is_safe, reason_if_not_safe).
    """
    if not path_str:
        return False, "empty path"

    if path_str.startswith("/") or (len(path_str) > 1 and path_str[1] == ":"):
        return False, "absolute paths are not allowed"

    for pattern in DENY_PATTERNS:
        if pattern.search(path_str):
            return False, f"path matches denylist pattern ({pattern.pattern})"

    try:
        workspace_resolved = workspace.resolve()
        target = (workspace_resolved / path_str).resolve()
    except (OSError, ValueError) as e:
        return False, f"path resolution failed: {e}"

    if target == workspace_resolved:
        return False, "path is the workspace root"

    if workspace_resolved not in target.parents:
        return False, "path escapes the workspace"

    return True, ""


def apply_files(
    output: str,
    workspace: str = ".",
    on_event: Optional[Callable[[Dict], None]] = None,
) -> List[Dict]:
    """Extract file blocks from worker output and write them to the workspace.

    Returns a list of write results, one per block encountered. Each entry:
      {"path": str, "written": bool, "reason": str (if blocked), "size": int (if written)}

    Blocked entries are reported but do not stop the rest of the writes from
    running. Callers can inspect the result list to see what happened.
    """
    workspace_path = Path(workspace).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)

    results: List[Dict] = []

    for path_str, content in extract_files(output):
        safe, reason = is_safe_path(path_str, workspace_path)
        if not safe:
            entry = {"path": path_str, "written": False, "reason": reason}
            results.append(entry)
            if on_event:
                on_event({"type": "file_write_blocked", "path": path_str, "reason": reason})
            continue

        target = workspace_path / path_str
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        size = len(content.encode("utf-8"))
        entry = {"path": path_str, "written": True, "size": size}
        results.append(entry)
        if on_event:
            on_event({"type": "file_write", "path": path_str, "size": size})

    return results
