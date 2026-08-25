# Source Notes (Current Pipeline)

## Active Sources

- `indeed` (via `jobspy_indeed`): fuente principal para volumen.
- `sce`: fuente pública oficial del Servicio Canario de Empleo.
- `turijobs`: fuente complementaria para hostelería/turismo.
- `emcan`: fuente pública oficial para Cantabria mediante el portal SNE (`--region cantabria`).
- `trabajocantabria`: ofertas de la agencia de colocación CEOE-CEPYME Cantabria.

Investigación y decisiones para Cantabria: `docs/cantabria-job-sources.md`.

## Excluded Source

- `infojobs`: fuera del alcance actual del pipeline.

## Scaling Strategy

El modo de escala (`--scale`) usa un máximo configurable de filas (`--max-total`) con cuotas objetivo por fuente:

- `--indeed-share` (default `0.82`)
- `--sce-share` (default `0.13`)
- `--turijobs-share` (default `0.05`)

Si una fuente secundaria no alcanza su cuota (normalmente SCE/Turijobs), el remanente pasa a Indeed.

## Recommended Command

```bash
.venv/bin/python -m src.canarias_jobs.cli --scale --time-limit 45 --max-total 40000
```

## Data Cleanup in Scale Mode

Al final del scraping escalado, el pipeline aplica:

- normalización de texto/campos clave
- inferencia de provincia desde isla cuando falta
- deduplicación por `source_url` con fallback por `source + external_id`
- recorte al máximo total solicitado

## Nightly Daemon + Persistence

Nuevo modo recomendado para operación remota:

- comando: `python -m src.canarias_uni_ml.cli jobs daemon`
- ventana por defecto: `22:00-07:30` en `Europe/Madrid`
- proceso vivo de larga duración (no requiere relanzar cada noche)

Persistencia:

- base canónica: `data/processed/canarias_jobs.db` (SQLite)
- snapshot de salida: `data/processed/canarias_jobs.csv`

Semántica anti-duplicado:

1. Se calcula clave canónica por oferta (`source + external_id`, fallback `source_url`).
2. Si clave no existe: inserta.
3. Si clave existe y payload cambia: actualiza.
4. Si clave existe y payload no cambia: no sobrescribe contenido (skip).

## Job-Degree Matching Policy (Current)

- `target_degree_titles` now comes from scored title candidates, not broad branch-wide title expansion.
- Selector keeps degrees with score near each job's best candidate (`best - delta`), with max cap per job.
- Weak-evidence jobs may return `degree_match_status=no_match` and empty `target_degree_titles`.
