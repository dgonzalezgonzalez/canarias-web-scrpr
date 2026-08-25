import os

import pytest

from src.canarias_uni_ml.jobs.daemon import DaemonLock, run_jobs_daemon
from src.canarias_uni_ml.jobs.pipeline import PipelineOutcome


def test_daemon_lock_blocks_when_process_alive(tmp_path):
    lock_path = tmp_path / "daemon.lock"
    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    lock = DaemonLock(lock_path)
    with pytest.raises(RuntimeError):
        lock.acquire()


def test_daemon_lock_reclaims_stale_pid(tmp_path):
    lock_path = tmp_path / "daemon.lock"
    lock_path.write_text("999999", encoding="utf-8")
    lock = DaemonLock(lock_path)
    lock.acquire()
    assert lock_path.exists()
    lock.release()
    assert not lock_path.exists()


def test_run_jobs_daemon_run_once_executes_single_cycle(tmp_path, monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_run_jobs_pipeline(**kwargs):
        calls.append(kwargs)
        return PipelineOutcome(
            exit_code=0,
            scraped=1,
            inserted=1,
            updated=0,
            unchanged=0,
            failures=[],
            elapsed_seconds=0.1,
            strategy="scrape",
        )

    monkeypatch.setattr("src.canarias_uni_ml.jobs.daemon.run_jobs_pipeline_with_outcome", fake_run_jobs_pipeline)

    code = run_jobs_daemon(
        limit_per_source=5,
        output_path=str(tmp_path / "jobs.csv"),
        db_path=str(tmp_path / "jobs.db"),
        window_start="00:00",
        window_end="23:59",
        timezone_name="Europe/Madrid",
        run_once=True,
        lock_path=str(tmp_path / "daemon.lock"),
    )
    assert code == 0
    assert len(calls) == 1


def test_run_jobs_daemon_forwards_region(tmp_path, monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_run_jobs_pipeline(**kwargs):
        calls.append(kwargs)
        return PipelineOutcome(
            exit_code=0,
            scraped=1,
            inserted=1,
            updated=0,
            unchanged=0,
            failures=[],
            elapsed_seconds=0.1,
            strategy="scrape",
        )

    monkeypatch.setattr("src.canarias_uni_ml.jobs.daemon.run_jobs_pipeline_with_outcome", fake_run_jobs_pipeline)
    code = run_jobs_daemon(
        limit_per_source=5,
        output_path=str(tmp_path / "jobs.csv"),
        db_path=str(tmp_path / "jobs.db"),
        window_start="00:00",
        window_end="23:59",
        timezone_name="Europe/Madrid",
        run_once=True,
        lock_path=str(tmp_path / "daemon.lock"),
        region="cantabria",
    )
    assert code == 0
    assert calls[0]["region"] == "cantabria"


def test_run_jobs_daemon_keeps_unchanged_successful_cycle_healthy(tmp_path, monkeypatch):
    def fake_run_jobs_pipeline(**kwargs):
        return PipelineOutcome(
            exit_code=0,
            scraped=10,
            inserted=0,
            updated=0,
            unchanged=10,
            failures=[],
            elapsed_seconds=0.1,
            strategy="scrape",
            attempted_sources=1,
            successful_sources=1,
        )

    monkeypatch.setattr("src.canarias_uni_ml.jobs.daemon.run_jobs_pipeline_with_outcome", fake_run_jobs_pipeline)

    code = run_jobs_daemon(
        limit_per_source=5,
        output_path=str(tmp_path / "jobs.csv"),
        db_path=str(tmp_path / "jobs.db"),
        window_start="00:00",
        window_end="23:59",
        timezone_name="Europe/Madrid",
        cooldown_minutes=0,
        lock_path=str(tmp_path / "daemon.lock"),
        stagnation_cycles=1,
        fail_on_stagnation=True,
        run_once=True,
    )
    assert code == 0


def test_run_jobs_daemon_exits_after_repeated_source_failure(tmp_path, monkeypatch):
    def fake_run_jobs_pipeline(**kwargs):
        return PipelineOutcome(
            exit_code=1,
            scraped=0,
            inserted=0,
            updated=0,
            unchanged=0,
            failures=["emcan: timeout"],
            elapsed_seconds=0.1,
            strategy="scrape",
            attempted_sources=1,
            successful_sources=0,
        )

    monkeypatch.setattr("src.canarias_uni_ml.jobs.daemon.run_jobs_pipeline_with_outcome", fake_run_jobs_pipeline)
    code = run_jobs_daemon(
        limit_per_source=5,
        output_path=str(tmp_path / "jobs.csv"),
        db_path=str(tmp_path / "jobs.db"),
        window_start="00:00",
        window_end="23:59",
        timezone_name="Europe/Madrid",
        lock_path=str(tmp_path / "daemon.lock"),
        stagnation_cycles=1,
        fail_on_stagnation=True,
        run_once=True,
    )
    assert code == 3


def test_run_jobs_daemon_scale_strategy_uses_scale_runner(tmp_path, monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_run_jobs_scale(**kwargs):
        calls.append(kwargs)
        return PipelineOutcome(
            exit_code=0,
            scraped=50,
            inserted=10,
            updated=1,
            unchanged=39,
            failures=[],
            elapsed_seconds=0.5,
            strategy="scale",
        )

    monkeypatch.setattr("src.canarias_uni_ml.jobs.daemon.run_jobs_scale_with_outcome", fake_run_jobs_scale)

    code = run_jobs_daemon(
        limit_per_source=5,
        output_path=str(tmp_path / "jobs.csv"),
        db_path=str(tmp_path / "jobs.db"),
        window_start="00:00",
        window_end="23:59",
        timezone_name="Europe/Madrid",
        run_once=True,
        lock_path=str(tmp_path / "daemon.lock"),
        strategy="scale",
        time_limit_minutes=12,
    )
    assert code == 0
    assert len(calls) == 1
    assert calls[0]["time_limit_minutes"] == 12
