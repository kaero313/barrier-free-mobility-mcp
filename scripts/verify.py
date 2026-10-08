"""Run the project verification gate and record evidence.

Steps run in order and stop at the first failure:

  1. ruff check .
  2. scripts/check_release_safety.py
  3. uv lock --check
  4. pytest -q                          (skipped with --fast)

    uv run --frozen python scripts/verify.py
    uv run --frozen python scripts/verify.py --fast

Each run writes .harness/runs/<id>/result.json. A run fails with reason
`workspace_mutated` when repository files change while it runs, because the
evidence would not describe a single working tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = PROJECT_ROOT / ".harness" / "runs"
OUTPUT_TAIL_CHARS = 2000
STEP_TIMEOUT_SECONDS = 1800
PYTEST_SUMMARY = re.compile(
    r"(\d+) (passed|failed|skipped|deselected|errors?|xfailed|xpassed|warnings?)"
)
SUMMARY_KEY_ALIASES = {"errors": "error", "warnings": "warning"}
CHILD_ENV = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTEST_ADDOPTS": ""}


def build_steps(fast: bool) -> list[tuple[str, list[str]]]:
    python = sys.executable
    steps = [
        ("ruff", [python, "-m", "ruff", "check", "."]),
        ("release_safety", [python, "scripts/check_release_safety.py"]),
        ("lock", [shutil.which("uv") or "uv", "lock", "--check"]),
    ]
    if not fast:
        steps.append(("pytest", [python, "-m", "pytest", "-q"]))
    return steps


def run(command: list[str]) -> dict:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=STEP_TIMEOUT_SECONDS,
            env={**os.environ, **CHILD_ENV},
        )
        exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        exit_code, stdout, stderr = 124, "", f"timeout after {STEP_TIMEOUT_SECONDS}s"
    except FileNotFoundError as exc:
        exit_code, stdout, stderr = 127, "", str(exc)
    return {
        "command": command,
        "exit_code": exit_code,
        "seconds": round(time.monotonic() - started, 1),
        "stdout": stdout,
        "stderr": stderr,
    }


def git(*args: str, root: Path = PROJECT_ROOT) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def is_local_env_file(relative: str) -> bool:
    name = Path(relative).name
    return name != ".env.example" and (name == ".env" or name.startswith(".env."))


def workspace_sha256(root: Path = PROJECT_ROOT) -> str | None:
    """Hash tracked and untracked, non-ignored files; None when git cannot list them."""
    listing = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", root=root)
    if not listing:
        return None
    lines = []
    for relative in sorted({item for item in listing.split("\0") if item}):
        if relative.startswith(".harness/") or is_local_env_file(relative):
            continue
        path = root / relative
        if path.is_symlink():
            data = os.readlink(path).encode("utf-8")
        elif path.is_file():
            data = path.read_bytes()
        else:
            continue
        lines.append(f"{relative} {hashlib.sha256(data).hexdigest()}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def pytest_summary(output: str) -> dict[str, int]:
    for line in reversed(output.strip().splitlines()):
        found = PYTEST_SUMMARY.findall(line)
        if found and " in " in line:
            return {SUMMARY_KEY_ALIASES.get(key, key): int(count) for count, key in found}
    return {}


def describe(step: dict) -> str:
    name = step["step"]
    if step["exit_code"] != 0:
        return f"{name} FAIL(exit {step['exit_code']})"
    if name == "pytest":
        counts = [f"{count} {key}" for key, count in step.get("summary", {}).items()]
        return "pytest " + (", ".join(counts) or "no summary")
    return f"{name} OK"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run the verification gate and record evidence.")
    parser.add_argument("--fast", action="store_true", help="skip pytest")
    args = parser.parse_args(argv)

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    before = workspace_sha256()
    if before is None:
        print("verify: failed | git cannot list repository files", file=sys.stderr)
        return 1
    results: list[dict] = []
    failed_step: str | None = None
    for name, command in build_steps(args.fast):
        result = {"step": name, **run(command)}
        if name == "pytest":
            result["summary"] = pytest_summary(result["stdout"])
        results.append(result)
        if result["exit_code"] != 0:
            failed_step = name
            break
    after = workspace_sha256()

    if failed_step is not None:
        failed = results[-1]
        sys.stderr.write((failed["stdout"] + failed["stderr"]).rstrip() + "\n")
    for result in results:
        result["stdout_tail"] = result.pop("stdout")[-OUTPUT_TAIL_CHARS:]
        result["stderr_tail"] = result.pop("stderr")[-OUTPUT_TAIL_CHARS:]

    reason = failed_step or ("workspace_mutated" if before != after else "passed")
    report = {
        "run_id": run_id,
        "status": "passed" if reason == "passed" else "failed",
        "reason": reason,
        "failed_step": failed_step,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_commit": git("rev-parse", "HEAD").strip(),
        "workspace_sha256": before,
        "workspace_sha256_after": after,
        "python": sys.version.split()[0],
        "fast": args.fast,
        "steps": results,
    }
    report_dir = RUNS_DIR / run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "result.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    summary = " | ".join(describe(step) for step in results)
    if reason == "workspace_mutated":
        summary += " | files changed during the run"
    try:
        shown_path = report_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        shown_path = report_path.as_posix()
    print(f"verify: {report['status']} | {summary} | report {shown_path}")
    return 0 if reason == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
