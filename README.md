# canarias-cantabria-unis-ml

Python pipeline for Canary Islands and Cantabria job postings plus Spanish university degree catalogs and alignment scoring based on text embeddings.

## Status

| Surface | Status | Notes |
|--------|--------|-------|
| SCE | ✅ Working | API JWT, número de ofertas variable |
| EMCAN / SNE | ✅ Added | Official Cantabria offer details, no credentials |
| Trabajo Cantabria | ✅ Added | CEOE-CEPYME Cantabria public listing/details |
| Turijobs | ✅ Working | Sitemap + detail pages |
| Indeed (JobSpy) | ✅ Working | Fuente principal para escalado |
| Geography / contract normalization | ✅ Working | Canonical + raw fields coexist |
| Degree catalog | 🧪 Working baseline | Fixture/live ANECA + university enrichments |
| Embeddings | 🧪 Working baseline | OpenAI + Ollama providers with cache |
| Alignment DB | 🧪 New | Candidate-gated cosine similarity in SQLite |

## Environment Variables

```bash
# JobSpy is optional; do not use proxies to bypass source controls.
export OPENAI_API_KEY='sk-...'                      # required for OpenAI embeddings
export GROQ_API_KEY='...'                           # optional experiments
export OLLAMA_BASE_URL='http://127.0.0.1:11434'    # local testing provider
export OLLAMA_EMBEDDING_MODEL='nomic-embed-text'   # local embedding model
```

Important: ChatGPT subscription and OpenAI API billing are separate. API usage must be configured on `platform.openai.com`.

## Quickstart

```bash
python3 --version  # Python 3.10+
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Only needed for Turijobs; install OS dependencies under the service user on Linux.
python -m playwright install --with-deps chromium

# Scrape jobs
python -m src.canarias_uni_ml.cli jobs scrape --limit-per-source 50

# Scrape Cantabria (writes cantabria_jobs.csv/.db by default)
python -m src.canarias_uni_ml.cli jobs scrape --region cantabria --limit-per-source 200
# Policy-safe official-only crawl (recommended default)
python -m src.canarias_uni_ml.cli jobs scrape --region cantabria --sources emcan --limit-per-source 200
# Opt into Trabajo Cantabria only after its source terms are cleared
python -m src.canarias_uni_ml.cli jobs scrape --region cantabria --sources emcan,trabajocantabria --limit-per-source 200

# Build degree catalog from fixture
python -m src.canarias_uni_ml.cli degrees catalog --fixture tests/fixtures/degrees_catalog_fixture.json

# Embedding dry run
python -m src.canarias_uni_ml.cli embed build --input tests/fixtures/semantic_corpus.jsonl --dry-run

# Alignment only (local Ollama by default)
python -m src.canarias_uni_ml.cli align run --provider ollama

# Full master pipeline in one command
python -m src.canarias_uni_ml.cli pipeline run --provider ollama

# Scale run with OpenAI
python -m src.canarias_uni_ml.cli pipeline run --provider openai --model text-embedding-3-small
```

Legacy job-only commands still route through compatibility wrapper in `src.canarias_jobs.cli`.

## Outputs

- `data/processed/canarias_jobs.csv`
- `data/processed/canarias_jobs.db`
- `data/processed/cantabria_jobs.csv`
- `data/processed/cantabria_jobs.db`
- `data/processed/degrees_catalog.csv`
- `data/processed/embeddings_manifest.json`
- `data/processed/program_job_alignment.db`
- `data/processed/program_job_similarity.csv`

## Project Layout

```text
src/canarias_uni_ml/
├── cli.py                # Multi-domain CLI
├── config.py             # Settings and output paths
├── io.py                 # CSV/JSONL writers
├── jobs/                 # Job scraping pipeline
├── degrees/              # Degree catalog pipeline
├── embeddings/           # Provider abstraction + cached vectors
├── alignment/            # Pairing + cosine similarity + DB persistence
├── pipeline/             # Master orchestration command
└── normalization/        # Canonical geography / contract type
```

## Job Data Contract

Canonical and raw values both persist:

- `province`, `municipality`, `island`, `contract_type`: canonical values
- `province_raw`, `municipality_raw`, `island_raw`, `contract_type_raw`: original scraped values
- `raw_location`: original free-text location

## Nightly Daemon

- Command: `python -m src.canarias_uni_ml.cli jobs daemon`
- Default schedule: `22:00` to `07:30` (`Europe/Madrid`)
- Behavior:
  - process stays alive and only scrapes inside configured window
  - writes canonical state to SQLite (`data/processed/canarias_jobs.db`)
  - exports snapshot CSV after each cycle (`data/processed/canarias_jobs.csv`)
  - avoids duplicates across nights
  - on repeated jobs, updates row only when payload changed; unchanged rows are skipped
  - source failures return non-zero and never overwrite the previous CSV snapshot
  - unchanged successful cycles are healthy; failure thresholds count source failures, not unchanged rows

Production deployment guide: `docs/operations/remote-nightly-deploy.md`

Cantabria VM command:

```bash
.venv/bin/python -m src.canarias_uni_ml.cli jobs daemon \
  --region cantabria \
  --sources emcan \
  --strategy scrape \
  --limit-per-source 200 \
  --window-start 22:00 \
  --window-end 07:30 \
  --cooldown-minutes 1440
```

Ready-made unit: `deploy/systemd/cantabria-jobs-daemon.service`. Source rationale, alternatives, and risks: `docs/cantabria-job-sources.md`.

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
.venv/bin/python -m src.canarias_uni_ml.cli jobs compact --region canarias
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

## Job-Degree Pairing (Detailed)

This section explains exactly how this project pairs job postings with academic degrees, including code paths, parameter values, and design rationale.

### Scope

The pairing logic is split in two stages:

1. **Rule + scoring mapping** (jobs pipeline): assigns each job a constrained candidate set using:
- `target_degree_titles`
- `target_degree_branches`
- `degree_match_status`

2. **Alignment pairing gate** (alignment pipeline): builds concrete `(job, degree)` pairs from those fields before embeddings/cosine similarity.

This two-stage design prevents all-vs-all matching noise.

### Where the logic lives

#### Stage 1: Job -> candidate degree targets

Primary module:
- `src/canarias_uni_ml/jobs/degree_mapping.py`

Entry points:
- `annotate_job_degree_targets(records, degrees_catalog_path=...)`
- Called from jobs pipeline in `src/canarias_uni_ml/jobs/pipeline.py`:
  - `run_jobs_pipeline_with_outcome(...)`
  - `run_jobs_merge(...)`

Output fields stored on `JobRecord` (`src/canarias_uni_ml/jobs/models.py`):
- `target_degree_titles` (pipe-separated)
- `target_degree_branches` (pipe-separated)
- `degree_match_status` (`matched` or `no_match`)

#### Stage 2: Candidate targets -> concrete job-degree pairs

Primary module:
- `src/canarias_uni_ml/alignment/pairing.py`

Entry point:
- `build_candidate_pairs(jobs, degrees, min_text_len=40)`

Used by alignment runner:
- `src/canarias_uni_ml/alignment/pipeline.py` in `run_alignment_pipeline(...)`

### End-to-end flow

1. Jobs are scraped and normalized.
2. `annotate_job_degree_targets` enriches each job with candidate degree titles/branches.
3. Jobs are written to DB/CSV with mapping fields.
4. `align run` loads jobs CSV + degrees CSV.
5. `build_candidate_pairs` creates only allowed pairs from mapped titles/branches.
6. Only these pairs are embedded and scored with cosine similarity.

### Stage 1 in detail: `annotate_job_degree_targets`

#### 1) Degree catalog indexing

`DegreeCatalogIndex.from_csv(...)` reads `degrees_catalog.csv` and builds indexes:
- `title_by_norm`: normalized title -> canonical title
- `branch_by_norm`: normalized branch -> canonical branch
- `branch_by_title_norm`: normalized title -> branch
- `description_by_title_norm`: normalized title -> normalized degree description

If branch is missing in catalog row, `_infer_branch_from_text(...)` attempts branch inference from title keywords.

#### 2) Rule matching (explicit priors)

Rules are declared in `DEGREE_RULES` as `DegreeRule(...)` objects.

Each rule has:
- `keywords`
- optional `branches`
- optional `titles`
- `scope`: `all` (title+description) or `title`

Text preprocessing:
- `_norm(...)`: lowercase, remove accents, strip punctuation, normalize spaces
- `_rule_matches(...)`: substring keyword matching on normalized text

Special guardrail:
- If post looks like teaching (`profesor/profesora/docente/maestro` in title), technical engineering/software/data rules are skipped to avoid false technical matches for teaching vacancies.

#### 3) Catalog-wide scoring

After explicit rule extraction, mapper scores **all catalog titles** with `_score_catalog_titles(...)`.

Score formula (current constants):
- `TITLE_WEIGHT = 0.70`
- `DESCRIPTION_WEIGHT = 0.30`
- `base = 0.70 * title_score + 0.30 * desc_score`

Where:
- `title_score = _text_similarity(job_title_norm, degree_title_norm)`
- `desc_score = _text_similarity(all_job_text_norm, degree_description_norm)` when description exists, else `0.0`

`_text_similarity(...)`:
- tokenizes via `_tokenize(...)` (drops stopwords like `grado`, `master`, `de`, `y`, etc.)
- computes overlap ratio against degree tokens
- token matching allows exact match or prefix match for tokens length >= 5 (`_token_match`)

Additive bonuses:
- `+0.15` if title was explicitly suggested by rule
- `+0.10` if degree branch matches explicit rule branch

Electric-role specialization (`_looks_electric_role`):
- Signals: `electricista`, `electrico/electrica`, `instalaciones electricas`, `baja/alta tension`, `electrotecn`
- If role is electric:
  - `+0.15` bonus for `Ingenieria y Arquitectura`
  - `-0.30` penalty for non-technical branches
  - additional filter: non-technical titles with final score `< 0.65` are dropped

Scores are clipped into `[0, 1]` and sorted deterministically by:
1. score descending
2. title ascending

#### 4) Candidate selection policy

`_select_titles(...)` chooses final titles from scored rows.

Current thresholds:
- `CANDIDATE_SCORE_MIN = 0.28`
- `CANDIDATE_SCORE_DELTA = 0.10`
- `CANDIDATE_MAX_KEEP = 5`

Selection:
1. If no rows, return empty.
2. Let `best_score` be top score.
3. If `best_score < 0.28`, return empty (`no_match`).
4. Keep rows with:
- `score >= best_score - 0.10`
- `score >= 0.28`
5. Cap to top `5` rows.

Then branches are reconstructed from selected titles using catalog index.

Final status:
- `matched` if at least one title kept
- `no_match` if no title passes

### Stage 2 in detail: `build_candidate_pairs`

File: `src/canarias_uni_ml/alignment/pairing.py`

#### 1) Build degree lookup structures

From degrees CSV:
- `by_title[title] -> list[degree_rows]`
- `by_branch[branch] -> list[degree_rows]`
- `titles_by_family[family_key] -> set[titles]`

#### 2) Gate on match status

Only jobs with:
- `degree_match_status == "matched"`

All other jobs are skipped.

#### 3) Parse mapped targets

Pipe fields are parsed with `parse_pipe_values(...)`.

#### 4) Family expansion for close title variants

`_family_keys(...)` + `_expand_target_title(...)` conservatively expands variants in same family, for example:
- `Grado en Psicología`
- `Grado en Psicología online`
- `Grado en Psicología - Presencial ...`

This avoids brittle exact-title dependence while preventing broad fuzzy expansion.

#### 5) Branch-based addition constrained by family overlap

For `target_degree_branches`, branch rows are added:
- directly if there are no target families
- or only if degree family intersects target families

This prevents adding unrelated degrees from the same macro-branch.

#### 6) Text-length and dedup filters

- Job text = `description` fallback `title`; must satisfy `len >= min_text_len`
- Degree text = `description` fallback `title`; must satisfy `len >= min_text_len`
- Dedup key: `(job_key, degree_key)`

Key construction:
- `_job_key`: prefers `source + external_id`, fallback `source_url`, fallback row index
- `_degree_key`: prefers `source + source_id`, fallback normalized title + row index

Output is a list of `CandidatePair` objects.

### Alignment execution after pairing

`run_alignment_pipeline(...)` (`src/canarias_uni_ml/alignment/pipeline.py`):

1. Read jobs/degrees CSV.
2. Build candidate pairs with `min_text_len` (CLI default: `40`).
3. Collect unique texts across all pairs.
4. Embed unique texts with cache (`embed_with_cache(...)`).
5. Compute cosine via `cosine_similarity(...)`.
6. Upsert `program_job_similarity` rows.
7. Delete stale rows for same provider/model not in current run.
8. Export `program_job_similarity.csv`.

### Parameters and defaults (current)

#### Mapping-stage constants (`degree_mapping.py`)

- `TITLE_WEIGHT = 0.70`
- `DESCRIPTION_WEIGHT = 0.30`
- `CANDIDATE_SCORE_MIN = 0.28`
- `CANDIDATE_SCORE_DELTA = 0.10`
- `CANDIDATE_MAX_KEEP = 5`
- `TECH_BRANCH = "ingenieria y arquitectura"`

#### Alignment-stage CLI default (`cli.py`)

- `align run --min-text-len 40`

#### Provider/model defaults (`alignment/pipeline.py`)

- provider `openai` -> default model `text-embedding-3-small`
- provider `ollama` -> default model `settings.ollama_embedding_model`
- provider `groq` -> placeholder fallback model string

### Why these settings exist

1. **Precision-first gating before similarity**
- Design intent from planning docs was to remove noisy branch-wide expansion and allow explicit `no_match`.
- Current mapper uses relative threshold + minimum score + cap to keep high-confidence, bounded candidate sets.

2. **Hybrid deterministic logic**
- Rules encode strong domain priors (nursing, law, software, tourism, etc.).
- Scoring across full catalog catches relevant titles not explicitly hardcoded.

3. **Bounded compute and stable outputs**
- `max_keep=5` limits pair explosion.
- deterministic sorting avoids run-to-run drift.
- text-length filter avoids embedding very short/noisy strings.

4. **Safety against incoherent matches**
- teaching-role exclusion for certain technical rules.
- electric-role penalties against non-technical branches.
- family-constrained expansion for title variants.

### Known evolution and tuning history

Planning docs for the precision upgrade originally discussed looser values (`delta=0.15`, `max_keep=8`).
Current code tightened these to:
- `delta=0.10`
- `max_keep=5`

This indicates a stricter precision posture in implementation.

### How to run and inspect

Rebuild jobs with mapping fields:

```bash
.venv/bin/python -m src.canarias_uni_ml.cli jobs scrape \
  --limit-per-source 50 \
  --output data/processed/canarias_jobs.csv
```

Run alignment:

```bash
.venv/bin/python -m src.canarias_uni_ml.cli align run \
  --jobs-csv data/processed/canarias_jobs.csv \
  --degrees-csv data/processed/degrees_catalog.csv \
  --db-path data/processed/program_job_alignment.db \
  --provider ollama \
  --min-text-len 40
```

Inspect mapped fields in jobs CSV:
- `target_degree_titles`
- `target_degree_branches`
- `degree_match_status`

Inspect output similarity CSV:
- `data/processed/program_job_similarity.csv`

### Test coverage that validates behavior

Mapping tests:
- `tests/test_degree_mapping.py`
- validates `no_match`, technical-role behavior, deterministic order, and max-keep cap

Pairing tests:
- `tests/test_alignment_pairing.py`
- validates matched-only gating, title/branch use, and degree-family variant expansion

Similarity math:
- `tests/test_alignment_similarity.py`

CLI contract:
- `tests/test_cli_master_pipeline.py` (includes align parser assertions)

### Practical caveats

- `degree_match_status` values outside `matched` are ignored by alignment pairing.
- Pairing relies on quality/completeness of `degrees_catalog.csv` titles, branches, and descriptions.
- If degree descriptions are sparse, ranking leans more on title overlap.
- Very short job/degree text can be filtered by `min_text_len` and not scored.
