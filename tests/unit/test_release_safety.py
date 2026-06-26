from __future__ import annotations

from pathlib import Path

from scripts.check_release_safety import (
    collect_release_safety_issues,
    is_release_candidate,
)


def write_required_ignore_files(root: Path) -> None:
    root.joinpath(".gitignore").write_text(
        "\n".join(
            [
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
            ]
        ),
        encoding="utf-8",
    )
    root.joinpath(".dockerignore").write_text(
        "\n".join(
            [
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
            ]
        ),
        encoding="utf-8",
    )


def test_release_scanner_excludes_local_artifacts(tmp_path: Path) -> None:
    write_required_ignore_files(tmp_path)
    public_key_marker = "PUBLIC_DATA" + "_SERVICE_KEY"
    mcp_key_marker = "MCP" + "_API_KEY"
    tmp_path.joinpath(".env").write_text(f"{public_key_marker}=real-local-value\n")
    tmp_path.joinpath(".tmp-auth-smoke-out.txt").write_text("local output\n")
    tmp_path.joinpath(".venv").mkdir()
    tmp_path.joinpath(".venv", "secret.txt").write_text(
        f"{mcp_key_marker}=real-local-value\n"
    )
    tmp_path.joinpath(".pytest_cache").mkdir()
    tmp_path.joinpath(".pytest_cache", "x").write_text("cache\n")

    issues = collect_release_safety_issues(tmp_path)

    assert issues == []
    assert not is_release_candidate(tmp_path, tmp_path / ".env")
    assert not is_release_candidate(tmp_path, tmp_path / ".tmp-auth-smoke-out.txt")
    assert not is_release_candidate(tmp_path, tmp_path / ".venv" / "secret.txt")


def test_release_scanner_detects_secret_assignment_without_value_leak(tmp_path: Path) -> None:
    write_required_ignore_files(tmp_path)
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    public_key_marker = "PUBLIC_DATA" + "_SERVICE_KEY"
    app_dir.joinpath("config.py").write_text(
        f'{public_key_marker} = "real-secret-value"\n',
        encoding="utf-8",
    )

    issues = collect_release_safety_issues(tmp_path)

    assert len(issues) == 1
    assert issues[0].marker == "PUBLIC_DATA_SERVICE_KEY"
    assert "real-secret-value" not in issues[0].format()


def test_release_scanner_allows_test_secret_strings(tmp_path: Path) -> None:
    write_required_ignore_files(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    mcp_key_marker = "MCP" + "_API_KEY"
    tests_dir.joinpath("test_auth.py").write_text(
        f'{mcp_key_marker} = "SECRET"\n',
        encoding="utf-8",
    )

    issues = collect_release_safety_issues(tmp_path)

    assert issues == []


def test_release_scanner_requires_ignore_patterns(tmp_path: Path) -> None:
    tmp_path.joinpath(".gitignore").write_text(".env\n", encoding="utf-8")
    tmp_path.joinpath(".dockerignore").write_text(".env\n", encoding="utf-8")

    issues = collect_release_safety_issues(tmp_path)

    markers = {issue.marker for issue in issues}
    assert ".venv/" in markers
    assert ".tmp-*" in markers
    assert ".git/" in markers
