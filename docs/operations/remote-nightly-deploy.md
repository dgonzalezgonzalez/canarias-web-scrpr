# Remote Nightly Deploy

## Remote run order (safe)

Run in this exact order on the remote host:

1. Backup current DB
```bash
cp data/processed/canarias_jobs.db data/processed/canarias_jobs.$(date +%F).bak.db
```

2. Stop daemon/service
```bash
sudo systemctl stop canarias-jobs-daemon.service
```

3. Compact DB (drop logical duplicates, keep latest row per job)
```bash
.venv/bin/python -m src.canarias_uni_ml.cli jobs compact --db-path data/processed/canarias_jobs.db
```

4. Preflight one cycle
```bash
.venv/bin/python -m src.canarias_uni_ml.cli jobs daemon --run-once --strategy scale --time-limit-minutes 45
```

5. Start nightly daemon
```bash
sudo systemctl start canarias-jobs-daemon.service
```

6. Monitor health/logs
```bash
sudo systemctl status canarias-jobs-daemon.service
sudo journalctl -u canarias-jobs-daemon.service -f
```

## 1) Bootstrap machine

```bash
git clone <repo-url>
cd canarias-uni-ml
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium  # only if enabling Turijobs
```

Set required env vars in service environment (or `.env`):

- `INFOJOBS_CLIENT_ID`
- `INFOJOBS_CLIENT_SECRET`
- Do not configure proxies to bypass source controls; JobSpy and Turijobs are optional.

## Cantabria VM (recommended path)

Use the renamed repository and region-specific paths:

```bash
git clone https://github.com/dgonzalezgonzalez/canarias-cantabria-unis-ml.git
cd canarias-cantabria-unis-ml
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Official EMCAN-only preflight (the shipped systemd unit uses the same source set)
.venv/bin/python -m src.canarias_uni_ml.cli jobs scrape \
  --region cantabria --sources emcan --limit-per-source 200

# Optional local board, only after its terms are cleared
.venv/bin/python -m src.canarias_uni_ml.cli jobs scrape \
  --region cantabria --sources emcan,trabajocantabria --limit-per-source 200

.venv/bin/python -m src.canarias_uni_ml.cli jobs compact --region cantabria
sudo cp deploy/systemd/cantabria-jobs-daemon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cantabria-jobs-daemon.service
```

The Cantabria unit writes `data/processed/cantabria_jobs.db` and
`data/processed/cantabria_jobs.csv`, runs one complete cycle per nightly window,
and restarts only after a failed source-health threshold. EMCAN is enabled by
default; add `--sources trabajocantabria` only after documenting permission.

## 2) Preflight check (mandatory)

```bash
.venv/bin/python -m src.canarias_uni_ml.cli jobs daemon --run-once
```

Expected:

- command exits `0`
- logs include cycle summary with `strategy/scraped/inserted/updated/unchanged`
- files created:
  - `data/processed/canarias_jobs.db`
  - `data/processed/canarias_jobs.csv`

## 2b) One-time dedupe for existing DB

If DB has legacy duplicates, stop daemon and compact:

```bash
.venv/bin/python -m src.canarias_uni_ml.cli jobs compact --db-path data/processed/canarias_jobs.db
```

Take backup before first compaction:

```bash
cp data/processed/canarias_jobs.db data/processed/canarias_jobs.$(date +%F).bak.db
```

## 3) Continuous nightly mode

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

## 4) Service mode (`systemd`)

Install template from `deploy/systemd/canarias-jobs-daemon.service` and adjust:

- `User`
- `WorkingDirectory`
- `EnvironmentFile`

Enable service:

```bash
sudo cp deploy/systemd/canarias-jobs-daemon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now canarias-jobs-daemon.service
```

## 5) Monitoring and stop

```bash
sudo systemctl status canarias-jobs-daemon.service
sudo journalctl -u canarias-jobs-daemon.service -f
sudo systemctl stop canarias-jobs-daemon.service
```

Watch for source-health signals:
- repeated `[warn] unhealthy source cycle`
- `[warn] failure threshold reached`
- `[error] exiting non-zero to allow supervisor restart`

## 6) Git flow

- branch naming: `feat/canarias-*`
- include code + tests + docs in same change set
