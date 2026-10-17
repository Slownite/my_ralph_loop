"""Local-first telemetry tests: content-free records, bounds, and retention."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from ralf.telemetry import Telemetry, TelemetryError, repository_state_directory


def test_records_and_reads_complete_lines(tmp_path: Path) -> None:
    telemetry = Telemetry(tmp_path)

    telemetry.record("run_start", run="abc", target="main")
    telemetry.record("run_end", run="abc", processed=1)

    records = list(telemetry.read_records())
    assert [record["event"] for record in records] == ["run_start", "run_end"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt", "do the thing"),
        ("diff", "--- a\n+++ b"),
        ("environment", {"TOKEN": "x"}),
        ("arguments", ["agent", "--flag"]),
        ("path", "/home/user/secret"),
        ("token", "abcd"),
    ],
)
def test_structured_records_reject_sensitive_content(
    tmp_path: Path, field: str, value: object
) -> None:
    telemetry = Telemetry(tmp_path)

    with pytest.raises(TelemetryError):
        telemetry.record("attempt", **{field: value})


def test_absolute_path_values_are_rejected(tmp_path: Path) -> None:
    telemetry = Telemetry(tmp_path)

    with pytest.raises(TelemetryError):
        telemetry.record("op", branch="/home/user/work")


def test_partial_trailing_record_is_retained_but_ignored(tmp_path: Path) -> None:
    telemetry = Telemetry(tmp_path)
    telemetry.record("run_start", run="abc")
    with telemetry.records_path.open("a", encoding="utf-8") as handle:
        handle.write('{"event": "run_end", "run": "abc"')

    records = list(telemetry.read_records())

    assert [record["event"] for record in records] == ["run_start"]
    assert telemetry.incomplete_tail() is True
    assert '{"event": "run_end"' in telemetry.records_path.read_text()


def test_transcripts_are_separate_bounded_and_restricted(tmp_path: Path) -> None:
    telemetry = Telemetry(tmp_path, max_transcript_bytes=16)

    path = telemetry.write_transcript("run1", 1, "stdout", "x" * 100)

    assert os.stat(path).st_mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR
    assert len(path.read_bytes()) == 16
    assert telemetry.records_path.exists() is False


def test_cleanup_retains_optionally_and_records_cleanup(tmp_path: Path) -> None:
    telemetry = Telemetry(tmp_path, max_runs=1, max_age_days=30)
    for run in ("old", "recent"):
        telemetry.write_transcript(run, 1, "stdout", "content")

    summary = telemetry.cleanup()

    assert summary["removed_runs"] == 1
    assert [record["event"] for record in telemetry.read_records()] == ["telemetry_cleanup"]


def test_cleanup_removes_records_for_excess_runs(tmp_path: Path) -> None:
    telemetry = Telemetry(tmp_path, max_runs=1, max_age_days=30)
    now = 1_000_000_000.0
    telemetry.record("run_start", run="old", time=now - 10)
    telemetry.record("run_end", run="old", time=now - 9)
    telemetry.record("run_start", run="recent", time=now - 1)
    telemetry.record("run_end", run="recent", time=now)

    summary = telemetry.cleanup(now=now)

    assert summary["removed_records"] == 2
    runs = [record.get("run") for record in telemetry.read_records() if "run" in record]
    assert runs == ["recent", "recent"]


def test_cleanup_removes_records_older_than_the_age_limit(tmp_path: Path) -> None:
    telemetry = Telemetry(tmp_path, max_runs=100, max_age_days=30)
    now = 2_000_000_000.0
    telemetry.record("run_start", run="stale", time=now - 40 * 24 * 60 * 60)
    telemetry.record("run_start", run="fresh", time=now)

    summary = telemetry.cleanup(now=now)

    assert summary["removed_records"] == 1
    runs = [record.get("run") for record in telemetry.read_records() if "run" in record]
    assert runs == ["fresh"]


def test_cleanup_retains_an_interrupted_record_tail(tmp_path: Path) -> None:
    telemetry = Telemetry(tmp_path, max_runs=1, max_age_days=30)
    telemetry.record("run_start", run="old", time=1.0)
    telemetry.record("run_start", run="new", time=2.0)
    with telemetry.records_path.open("a", encoding="utf-8") as handle:
        handle.write('{"event": "run_end", "run": "new"')

    summary = telemetry.cleanup(now=2.0)

    assert summary["removed_records"] == 1
    assert '{"event": "run_end", "run": "new"' in telemetry.records_path.read_text()
    runs = [record.get("run") for record in telemetry.read_records() if "run" in record]
    assert runs == ["new"]


def test_repository_state_directory_is_keyed_by_identity(tmp_path: Path) -> None:
    monkeypatch_state = tmp_path / "state"
    os.environ["XDG_STATE_HOME"] = str(monkeypatch_state)
    try:
        first = repository_state_directory(tmp_path / "one")
        second = repository_state_directory(tmp_path / "two")
        assert first != second
        assert first.parent == monkeypatch_state / "ralf" / "repositories"
    finally:
        del os.environ["XDG_STATE_HOME"]
