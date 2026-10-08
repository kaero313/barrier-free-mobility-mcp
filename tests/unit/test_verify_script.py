from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import verify


def use_fake_steps(
    monkeypatch: pytest.MonkeyPatch,
    runs_dir: Path,
    exit_codes: dict[str, int] | None = None,
    tree_hashes: tuple[str | None, ...] = ("tree", "tree"),
    outputs: dict[str, str] | None = None,
) -> list[str]:
    exit_codes = exit_codes or {}
    outputs = {"pytest": "438 passed, 1 warning in 30.00s\n", **(outputs or {})}
    calls: list[str] = []

    def fake_build_steps(fast: bool) -> list[tuple[str, list[str]]]:
        names = ["ruff", "release_safety", "lock"] + ([] if fast else ["pytest"])
        return [(name, [name]) for name in names]

    def fake_run(command: list[str]) -> dict:
        calls.append(command[0])
        return {
            "command": command,
            "exit_code": exit_codes.get(command[0], 0),
            "seconds": 0.0,
            "stdout": outputs.get(command[0], ""),
            "stderr": "",
        }

    hashes = iter(tree_hashes)
    monkeypatch.setattr(verify, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(verify, "build_steps", fake_build_steps)
    monkeypatch.setattr(verify, "run", fake_run)
    monkeypatch.setattr(verify, "workspace_sha256", lambda: next(hashes))
    monkeypatch.setattr(verify, "git", lambda *args, root=None: "abc123\n")
    return calls


def read_report(runs_dir: Path) -> dict:
    (report_path,) = runs_dir.glob("*/result.json")
    return json.loads(report_path.read_text(encoding="utf-8"))


def test_build_steps_runs_cheap_checks_before_pytest() -> None:
    assert [name for name, _ in verify.build_steps(fast=False)] == [
        "ruff",
        "release_safety",
        "lock",
        "pytest",
    ]
    assert [name for name, _ in verify.build_steps(fast=True)] == ["ruff", "release_safety", "lock"]


def test_pytest_summary_reads_last_summary_line() -> None:
    output = "....F\nFAILED tests/x.py::test_y\n1 failed, 437 passed, 2 warnings in 31.20s\n"

    assert verify.pytest_summary(output) == {"failed": 1, "passed": 437, "warning": 2}
    assert verify.pytest_summary("3 errors in 1.00s") == {"error": 3}
    assert verify.pytest_summary("no summary here") == {}


def test_main_records_passing_run_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = use_fake_steps(monkeypatch, tmp_path)

    assert verify.main([]) == 0

    report = read_report(tmp_path)
    assert calls == ["ruff", "release_safety", "lock", "pytest"]
    assert report["status"] == "passed"
    assert report["reason"] == "passed"
    assert report["base_commit"] == "abc123"
    assert report["steps"][-1]["summary"] == {"passed": 438, "warning": 1}
    output = capsys.readouterr().out
    assert "verify: passed" in output
    assert "pytest 438 passed, 1 warning" in output


def test_main_stops_at_first_failed_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = use_fake_steps(monkeypatch, tmp_path, exit_codes={"release_safety": 1})

    assert verify.main([]) == 1

    report = read_report(tmp_path)
    assert calls == ["ruff", "release_safety"]
    assert report["status"] == "failed"
    assert report["reason"] == "release_safety"
    assert report["failed_step"] == "release_safety"


def test_failed_step_prints_full_output_and_keeps_tail_in_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = "first traceback line\n" + "x" * 3000
    use_fake_steps(monkeypatch, tmp_path, exit_codes={"ruff": 1}, outputs={"ruff": output})

    assert verify.main([]) == 1

    step = read_report(tmp_path)["steps"][0]
    assert "first traceback line" in capsys.readouterr().err
    assert len(step["stdout_tail"]) == verify.OUTPUT_TAIL_CHARS
    assert "stdout" not in step


def test_main_fails_without_git_file_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = use_fake_steps(monkeypatch, tmp_path, tree_hashes=(None,))

    assert verify.main([]) == 1

    assert calls == []
    assert not list(tmp_path.glob("*/result.json"))


def test_main_fails_when_files_change_during_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake_steps(monkeypatch, tmp_path, tree_hashes=("before", "after"))

    assert verify.main([]) == 1

    report = read_report(tmp_path)
    assert report["status"] == "failed"
    assert report["reason"] == "workspace_mutated"
    assert report["failed_step"] is None


def test_fast_run_skips_pytest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = use_fake_steps(monkeypatch, tmp_path)

    assert verify.main(["--fast"]) == 0

    assert calls == ["ruff", "release_safety", "lock"]
    assert read_report(tmp_path)["fast"] is True


def test_workspace_sha256_tracks_content_and_skips_local_files(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    original = verify.workspace_sha256(tmp_path)

    tmp_path.joinpath(".env").write_text("LOCAL=1\n", encoding="utf-8")
    evidence_dir = tmp_path / ".harness" / "runs" / "run-1"
    evidence_dir.mkdir(parents=True)
    evidence_dir.joinpath("result.json").write_text("{}\n", encoding="utf-8")
    assert verify.workspace_sha256(tmp_path) == original

    source.write_text("value = 2\n", encoding="utf-8")
    assert verify.workspace_sha256(tmp_path) != original
