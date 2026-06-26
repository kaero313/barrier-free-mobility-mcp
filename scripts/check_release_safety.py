from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_GITIGNORE_PATTERNS = {
    ".env",
    ".env.*",
    "!.env.example",
    ".venv/",
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    ".tmp-*",
    "*.log",
    "dist/",
    "build/",
    "*.egg-info/",
}

REQUIRED_DOCKERIGNORE_PATTERNS = {
    ".env",
    ".env.*",
    "!.env.example",
    ".venv/",
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    ".tmp-*",
    "*.log",
    ".git/",
    "dist/",
    "build/",
    "*.egg-info/",
}

EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
    "htmlcov",
}

EXCLUDED_FILE_PATTERNS = {
    ".env",
    ".env.*",
    ".tmp-*",
    "*.pyc",
    "*.pyo",
    "*.log",
    ".coverage",
    "coverage.xml",
    "uv.lock",
}

SENSITIVE_MARKERS = (
    "PUBLIC_DATA_SERVICE_KEY",
    "SEOUL_OPEN_API_KEY",
    "ELEVATOR_STATUS_API_KEY",
    "ELEVATOR_INFO_API_KEY",
    "RESTROOM_API_KEY",
    "MCP_API_KEY",
)

SECRET_ASSIGNMENT_RE = re.compile(
    rf"(?P<marker>{'|'.join(re.escape(marker) for marker in SENSITIVE_MARKERS)})"
    r"\s*[:=]\s*"
    r"(?P<value>.+)"
)

SERVICE_KEY_QUERY_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<marker>serviceKey|ServiceKey|SERVICE_KEY)"
    r"\s*=\s*"
    r"(?P<value>[^&\s]+)"
)

PLACEHOLDER_VALUES = {
    "",
    "...",
    "change-me",
    "changeme",
    "secret",
    "secret-value",
    "secret-token",
    "test-secret",
    "dummy",
    "placeholder",
    "[redacted]",
    "<redacted>",
    "긴-랜덤-문자열",
}


@dataclass(frozen=True)
class ReleaseSafetyIssue:
    path: str
    line: int | None
    marker: str
    reason: str

    def format(self) -> str:
        location = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{location}: {self.marker} ({self.reason})"


def collect_release_safety_issues(root: Path = PROJECT_ROOT) -> list[ReleaseSafetyIssue]:
    root = root.resolve()
    issues: list[ReleaseSafetyIssue] = []
    issues.extend(check_ignore_file(root / ".gitignore", REQUIRED_GITIGNORE_PATTERNS))
    issues.extend(check_ignore_file(root / ".dockerignore", REQUIRED_DOCKERIGNORE_PATTERNS))

    for path in iter_release_candidate_files(root):
        issues.extend(scan_file_for_secrets(root, path))

    return issues


def check_ignore_file(path: Path, required_patterns: set[str]) -> list[ReleaseSafetyIssue]:
    if not path.exists():
        return [
            ReleaseSafetyIssue(
                path=path.name,
                line=None,
                marker=path.name,
                reason="ignore file is missing",
            )
        ]

    patterns = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = sorted(required_patterns - patterns)
    return [
        ReleaseSafetyIssue(
            path=path.name,
            line=None,
            marker=pattern,
            reason="required ignore pattern is missing",
        )
        for pattern in missing
    ]


def iter_release_candidate_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if path.is_dir() or not is_release_candidate(root, path):
            continue
        candidates.append(path)
    return sorted(candidates)


def is_release_candidate(root: Path, path: Path) -> bool:
    relative = path.resolve().relative_to(root)
    parts = relative.parts
    if any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]):
        return False

    name = path.name
    if name == ".env.example":
        return True
    return not any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED_FILE_PATTERNS)


def scan_file_for_secrets(root: Path, path: Path) -> list[ReleaseSafetyIssue]:
    relative = path.resolve().relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    issues: list[ReleaseSafetyIssue] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        issues.extend(scan_line_for_secret_assignments(relative, line_number, line))
        issues.extend(scan_line_for_service_key_query(relative, line_number, line))
    return issues


def scan_line_for_secret_assignments(
    relative_path: str,
    line_number: int,
    line: str,
) -> list[ReleaseSafetyIssue]:
    issues: list[ReleaseSafetyIssue] = []
    for match in SECRET_ASSIGNMENT_RE.finditer(line):
        marker = match.group("marker")
        value = normalize_candidate_secret_value(match.group("value"))
        if is_allowed_secret_value(relative_path, value):
            continue
        issues.append(
            ReleaseSafetyIssue(
                path=relative_path,
                line=line_number,
                marker=marker,
                reason="secret-like assignment must stay out of release files",
            )
        )
    return issues


def scan_line_for_service_key_query(
    relative_path: str,
    line_number: int,
    line: str,
) -> list[ReleaseSafetyIssue]:
    issues: list[ReleaseSafetyIssue] = []
    for match in SERVICE_KEY_QUERY_RE.finditer(line):
        marker = match.group("marker")
        value = normalize_candidate_secret_value(match.group("value"))
        if is_allowed_secret_value(relative_path, value):
            continue
        issues.append(
            ReleaseSafetyIssue(
                path=relative_path,
                line=line_number,
                marker=marker,
                reason="service key query value must not be committed",
            )
        )
    return issues


def normalize_candidate_secret_value(raw_value: str) -> str:
    value = raw_value.strip()
    value = value.split("#", 1)[0].strip()
    value = value.rstrip(",;")
    return value.strip("\"'")


def is_allowed_secret_value(relative_path: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in PLACEHOLDER_VALUES:
        return True
    if normalized.startswith("<") and normalized.endswith(">"):
        return True
    if normalized.startswith("${") and normalized.endswith("}"):
        return True
    return relative_path.startswith("tests/") and "secret" in normalized


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check release files for local artifacts and secrets."
    )
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()

    issues = collect_release_safety_issues(args.root)
    if not issues:
        print("Release safety check passed.")
        return 0

    print("Release safety check failed:")
    for issue in issues:
        print(f"- {issue.format()}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
