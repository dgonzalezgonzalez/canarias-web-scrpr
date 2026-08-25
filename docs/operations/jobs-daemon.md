# Jobs Daemon Operations

## Purpose

Run the jobs scraper as a long-lived process that only executes inside a nightly window.

## Command

```bash
.venv/bin/python -m src.canarias_uni_ml.cli jobs daemon \
  --window-start 22:00 \
  --window-end 07:30 \
  --timezone Europe/Madrid \
  --strategy scale \
  --time-limit-minutes 45 \
  --cooldown-minutes 5 \
  --stagnation-cycles 6 \
  --fail-on-stagnation
```

## Runtime Signals

- `SIGTERM` / `SIGINT`: daemon stops gracefully after current step.

## Locking

- Lock file prevents concurrent daemon instances.
- Default lock path: `data/processed/canarias_jobs.lock`

## Outputs

- Canonical DB: `data/processed/canarias_jobs.db`
- Snapshot CSV: `data/processed/canarias_jobs.csv`

## Preflight

```bash
.venv/bin/python -m src.canarias_uni_ml.cli jobs daemon --run-once
```

Use run-once preflight before enabling unattended service mode.

## Deduplicate Existing Database

Stop daemon first, then compact DB in place:

```bash
.venv/bin/python -m src.canarias_uni_ml.cli jobs compact --db-path data/processed/canarias_jobs.db
```

This keeps one latest logical row per job and removes stale duplicates.

## Source health

- A healthy cycle means at least one selected source returned records and the pipeline completed successfully.
- Unchanged rows are expected and do not count as failure.
- `--stagnation-cycles N` counts consecutive unhealthy source cycles.
- With `--fail-on-stagnation`, daemon exits non-zero at threshold so `systemd` restarts it.

## Throughput Tuning

- Increase per-night ingestion:
  - use `--strategy scale`
  - increase `--time-limit-minutes`
  - decrease `--cooldown-minutes`
- Reduce churn when sources are unstable:
  - raise `--stagnation-cycles`
  - disable `--fail-on-stagnation` temporarily (warning-only mode)
