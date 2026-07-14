from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_uses_frozen_lockfile_and_non_root_runtime() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY --chown=app:app pyproject.toml uv.lock README.md ./" in dockerfile
    assert "uv sync --frozen --no-dev --no-install-project" in dockerfile
    assert 'CMD ["python", "-m", "app.main"]' in dockerfile
    assert "USER app" in dockerfile


def test_ci_runs_locked_quality_checks_and_docker_build() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "uv sync --frozen --all-groups" in workflow
    assert "uv run --frozen ruff check ." in workflow
    assert "uv run --frozen pytest" in workflow
    assert "scripts/check_release_safety.py" in workflow
    assert "docker build" in workflow


def test_line_endings_are_declared_for_source_and_powershell_files() -> None:
    attributes = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "*.py text eol=lf" in attributes
    assert "*.yml text eol=lf" in attributes
    assert "*.ps1 text eol=crlf" in attributes
