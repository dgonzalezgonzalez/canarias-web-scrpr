from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from ..io import ensure_parent
from .pipeline import run_jobs_pipeline_with_outcome, run_jobs_scale_with_outcome


@dataclass(frozen=True, slots=True)
class NightWindow:
    start: dt_time
    end: dt_time

    def is_active(self, now: datetime) -> bool:
        now_time = now.timetz().replace(tzinfo=None)
        if self.start < self.end:
            return self.start <= now_time < self.end
        return now_time >= self.start or now_time < self.end

    def seconds_until_start(self, now: datetime) -> int:
        if self.is_active(now):
            return 0
        candidate = now.replace(
            hour=self.start.hour,
            minute=self.start.minute,
            second=0,
            microsecond=0,
        )
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return max(1, int((candidate - now).total_seconds()))


def parse_hhmm(value: str) -> dt_time:
    try:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("invalid")
        hour, minute = int(parts[0]), int(parts[1])
        return dt_time(hour=hour, minute=minute)
    except ValueError as exc:
        raise ValueError(f"Invalid HH:MM value: {value}") from exc


class DaemonLock:
    def __init__(self, lock_path: str | Path) -> None:
        self.path = Path(lock_path)
        self._locked = False

    def acquire(self) -> None:
        ensure_parent(self.path)
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(str(os.getpid()))
                self._locked = True
                return
            except FileExistsError:
                pid = self._read_pid()
                if pid and _pid_alive(pid):
                    raise RuntimeError(f"Daemon already running with PID {pid}")
                self.path.unlink(missing_ok=True)

    def release(self) -> None:
        if self._locked:
            self.path.unlink(missing_ok=True)
            self._locked = False

    def _read_pid(self) -> int | None:
        try:
            text = self.path.read_text(encoding="utf-8").strip()
            if not text:
                return None
            return int(text)
        except (FileNotFoundError, ValueError):
            return None

    def __enter__(self) -> "DaemonLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _sleep_interruptible(seconds: int, should_stop: Callable[[], bool]) -> None:
    remaining = seconds
    while remaining > 0 and not should_stop():
        time.sleep(min(1, remaining))
        remaining -= 1


def run_jobs_daemon(
    *,
    limit_per_source: int,
    output_path: str,
    db_path: str,
    max_total: int | None = None,
    window_start: str = "22:00",
    window_end: str = "07:30",
    timezone_name: str = "Europe/Madrid",
    cooldown_minutes: int = 10,
    idle_poll_seconds: int = 30,
    run_once: bool = False,
    lock_path: str | None = None,
    strategy: str = "scrape",
    time_limit_minutes: int = 45,
    stagnation_cycles: int = 0,
    fail_on_stagnation: bool = False,
    region: str = "canarias",
    sources: list[str] | tuple[str, ...] | None = None,
) -> int:
    tz = ZoneInfo(timezone_name)
    window = NightWindow(start=parse_hhmm(window_start), end=parse_hhmm(window_end))
    lock = DaemonLock(lock_path or f"{db_path}.lock")
    stop_requested = False

    def request_stop(signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True
        print(f"[stop] signal {signum} received, shutting down after current step")

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        with lock:
            print(
                "[start] jobs daemon window={start}-{end} tz={tz} cooldown={cooldown}m strategy={strategy}".format(
                    start=window_start,
                    end=window_end,
                    tz=timezone_name,
                    cooldown=cooldown_minutes,
                    strategy=strategy,
                )
            )
            stagnant_cycles = 0
            while not stop_requested:
                now = datetime.now(tz)
                if not run_once and not window.is_active(now):
                    wait_seconds = min(idle_poll_seconds, window.seconds_until_start(now))
                    print(f"[sleep] outside window; waiting {wait_seconds}s")
                    _sleep_interruptible(wait_seconds, lambda: stop_requested)
                    continue

                print("[cycle] starting scrape cycle")
                if strategy == "scale":
                    outcome = run_jobs_scale_with_outcome(
                        output_path=output_path,
                        db_path=db_path,
                        time_limit_minutes=time_limit_minutes,
                        max_total=max_total or 40_000,
                    )
                else:
                    outcome = run_jobs_pipeline_with_outcome(
                        limit_per_source=limit_per_source,
                        output_path=output_path,
                        max_total=max_total,
                        db_path=db_path,
                        region=region,
                        sources=sources,
                    )
                exit_code = outcome.exit_code
                print(
                    "[cycle] strategy={strategy} scraped={scraped} inserted={inserted} updated={updated} unchanged={unchanged} failures={failures} elapsed={elapsed:.1f}s".format(
                        strategy=outcome.strategy,
                        scraped=outcome.scraped,
                        inserted=outcome.inserted,
                        updated=outcome.updated,
                        unchanged=outcome.unchanged,
                        failures=len(outcome.failures),
                        elapsed=outcome.elapsed_seconds,
                    )
                )
                healthy_cycle = outcome.exit_code == 0 and (
                    outcome.successful_sources > 0
                    or (outcome.attempted_sources == 0 and outcome.scraped > 0)
                )
                if not healthy_cycle:
                    stagnant_cycles += 1
                    print(f"[warn] unhealthy source cycle count={stagnant_cycles}")
                    if stagnation_cycles > 0 and stagnant_cycles >= stagnation_cycles:
                        print(f"[warn] failure threshold reached ({stagnation_cycles})")
                        if fail_on_stagnation:
                            print("[error] exiting non-zero to allow supervisor restart")
                            return 3
                else:
                    stagnant_cycles = 0
                if run_once:
                    return exit_code
                if stop_requested:
                    break
                _sleep_interruptible(max(1, cooldown_minutes * 60), lambda: stop_requested)
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)

    print("[done] daemon stopped")
    return 0
