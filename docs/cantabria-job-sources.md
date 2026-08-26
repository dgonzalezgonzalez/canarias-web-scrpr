# Cantabria job-source research

Research date: 2026-08-25. Goal: collect occupation titles and substantive job descriptions for the Cantabrian labor market with a scraper that can run unattended on a separate Linux VM.

## Recommended production sources

### 1. EMCAN through the Sistema Nacional de Empleo (implemented)

- Official current-offer search: `https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?botonNavegacion=Enviar&modo=continuar&provincia=39`
- Regional portal: `https://empleacantabria.es/ofertas-cantabria`
- Coverage observed: roughly 100-140 simultaneous active offers during July-August 2026.
- Detail quality: occupation, publication/start and closing/end dates, municipality, long `Datos adicionales`, contract/workday/salary text, vacancies, requirements, and contact instructions.
- Implementation: `EmcanSpider` opens the province-39 result page with one `requests.Session`, follows offer and pagination links, and stores a stable detail URL without the transient `idFlujo` parameter.
- Main risk: legacy Java session/pagination parameters can change. Fixture tests cover current semantic labels instead of brittle CSS classes. The spider is isolated and failure-tolerant.

This is the closest Cantabrian replacement for the Canary Islands SCE source. Prefer it over attempting to reuse the Canary SCE JWT API, which is region-specific.

### 2. Trabajo Cantabria / CEOE-CEPYME Cantabria (implemented)

- Listing: `https://www.trabajocantabria.com/ofertas/`
- Publisher: Agencia de Colocación CEOE-CEPYME Cantabria.
- Coverage observed: dozens of active offers across Santander, Torrelavega, Camargo, Laredo, Reocín, and other municipalities.
- Detail quality: strong. Pages expose title, publication date, registration closing date, description, functions, offered conditions, location, vacancies, minimum education, contract duration, workday, and salary.
- Implementation: server-rendered HTML with `requests` + BeautifulSoup; no browser dependency.
- Main risk: HTML headings may change. Parser uses visible semantic labels and has fixture tests.

### 3. Indeed and LinkedIn through JobSpy (implemented, best effort)

- Reuses the existing JobSpy adapter with Cantabria and major-municipality searches.
- Best potential volume, but anti-bot behavior and upstream markup/API changes make it less stable than the two local sources.
- Records retain the originating site in `source` (`jobspy_indeed`, `jobspy_linkedin`).
- VM operators should expect intermittent zero-result or blocked cycles and should not treat this source as an official census.

### 4. Turijobs (implemented, complementary)

- Active-offer sitemap: `https://www.turijobs.com/es-es/sitemap/active-offers.xml`
- Useful for Cantabria tourism/hospitality postings. Filters sitemap URLs for `cantabria`, `santander`, and `torrelavega`, then reuses the existing detail parser.
- Requires Playwright/Chromium and should remain a bounded complementary source.

## Useful but not enabled by default

### Santander municipal open-data API

- Catalog: `https://datos.gob.es/es/catalogo/l01390759-ofertas-de-empleo`
- JSON: `http://datos.santander.es/api/rest/datasets/oferta_empleo.json`
- Observed payload: 8,635 records over nine pages, including occupation (`ayto:puesto`), vacancies, offer text (`ayto:seOfrece`), dates, education, and per-record URIs.
- License: CC BY 4.0 according to datos.gob.es.
- Value: excellent historical occupation/description corpus for Santander.
- Why excluded from nightly defaults: many records are historical and `dc:modified` appeared bulk-refreshed, so it cannot safely represent currently active vacancies without a separate historical-ingestion contract and explicit end-date logic.

Recommended future command: a separate `jobs history --source santander-open-data` workflow, never mixed silently into the current-offer snapshot.

### InfoJobs official API

- Official list API supports province filters, pagination, facets, salary, contract, workday, requirements, and publication/update dates.
- Detail API adds full description and candidate requirements.
- Requires registered developer credentials (`INFOJOBS_CLIENT_ID`, `INFOJOBS_CLIENT_SECRET`).
- Website robots rules disallow several offer/search surfaces, so use the documented API rather than HTML scraping.
- Existing adapter can be re-enabled after credentials and Cantabria's current province dictionary ID are verified.

### Cámara de Comercio de Cantabria

- `https://bolsa.empleocamaracantabria.com/`
- Current, local, server-rendered listing with about ten pages observed.
- Not implemented because coverage overlaps the stronger local sources and detail-page behavior needs more live verification. Good next source if recall is insufficient.

### Cámara de Torrelavega

- `https://www.empleocamaratorrelavega.es/`
- Very small visible inventory and WordPress plugin warnings were observed. Lower priority than CEOE/EMCAN.

## Rejected as primary sources

- Canary Islands SCE API: official and strong for Canarias, but its token/API and geography are Canary-specific.
- Generic HTML scraping of InfoJobs: official API exists and robots restrictions make HTML scraping unsuitable.
- Indeed direct HTML scraper: blocked/unstable in prior project testing; JobSpy remains best effort.
- Public-employment bulletins/BOC: measure public-sector selection processes, not the broad vacancy market targeted here.

## Operational and compliance notes

- Fetch only public pages; no login, candidate profiles, applications, cookies, or personal accounts.
- The production systemd unit enables EMCAN only (`--sources emcan`). Trabajo Cantabria is an explicit opt-in source until its reproduction/transformation terms have written permission or legal sign-off.
- Use `--sources emcan,trabajocantabria` only after that review; the CLI keeps source selection explicit so an operator can document the approved set.
- Default concurrency remains one worker per source. Each local spider requests detail pages sequentially with 30-second timeouts.
- Keep one complete nightly crawl (the Cantabria unit uses a 24-hour cooldown) and persistent deduplication. Do not hammer sources to manufacture volume.
- SQLite stores `is_active` plus `first_seen_at`/`last_seen_at`; EMCAN and Trabajo Cantabria deactivate missing rows only when the bounded crawl proves it reached the end of the listing. JobSpy/Turijobs are intentionally treated as partial.
- Re-check each source's current terms and `robots.txt` from the deployment VM before production; this research environment could inspect indexed public content but could not directly retrieve every robots endpoint.
- Contact instructions can contain public emails. The EMCAN parser intentionally excludes `Datos de contacto` from the normalized description because occupation analysis does not need it.

## GitHub-code review

Searches found older generic InfoJobs scrapers (for example `ander-elkoroaristizabal/InfojobsScraper`) but no maintained open-source scraper specifically for EMCAN, Trabajo Cantabria, or the Santander open-data endpoint. Existing InfoJobs HTML examples are less suitable than the official API. Implementation therefore reuses this repository's `JobRecord`, storage, cleanup, daemon, and failure-isolation patterns instead of importing an unmaintained scraper.
