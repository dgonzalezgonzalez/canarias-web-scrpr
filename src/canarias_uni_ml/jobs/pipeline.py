from __future__ import annotations

import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .degree_mapping import annotate_job_degree_targets
from .scale import _clean_record
from .models import JobRecord
from .regions import default_spiders
from .scale import run_scaled
from .spiders import SpiderError
from .storage import JobsRepository

PROCESSED_DIR = Path("data/processed")
DEFAULT_JOBS_DB = Path("data/processed/canarias_jobs.db")


@dataclass(slots=True)
class PipelineOutcome:
    exit_code: int
    scraped: int
    inserted: int
    updated: int
    unchanged: int
    failures: list[str]
    elapsed_seconds: float
    strategy: str = "scrape"


def run_jobs_merge(output_path: str) -> int:
    all_records: list[JobRecord] = []
    csv_files = sorted(PROCESSED_DIR.glob("*.csv"))
    if not csv_files:
        print("[skip] No CSV files found in data/processed/")
        return 1
    for csv_file in csv_files:
        with open(csv_file, encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            all_records.extend(JobRecord(**row) for row in reader)
    seen_urls: set[str] = set()
    unique_records: list[JobRecord] = []
    for record in all_records:
        if record.source_url not in seen_urls:
            seen_urls.add(record.source_url)
            unique_records.append(record)
    unique_records.sort(key=lambda r: (r.source, r.publication_date or ""), reverse=True)
    mapped_records = annotate_job_degree_targets(unique_records)
    written = write_csv_rows(mapped_records, output_path)
    print(f"[done] wrote {written} merged rows to {output_path}")
    return 0


def _select_with_source_coverage(records: list[JobRecord], max_total: int | None) -> list[JobRecord]:
    if max_total is None or len(records) <= max_total:
        return records
    grouped: dict[str, list[JobRecord]] = {}
    for record in records:
        grouped.setdefault(record.source, []).append(record)
    selected: list[JobRecord] = []
    seen_urls: set[str] = set()
    for source in sorted(grouped):
        record = grouped[source][0]
        if record.source_url in seen_urls:
            continue
        selected.append(record)
        seen_urls.add(record.source_url)
    for record in records:
        if len(selected) >= max_total:
            break
        if record.source_url in seen_urls:
            continue
        selected.append(record)
        seen_urls.add(record.source_url)
    return selected[:max_total]


def _collect_records(spiders: Iterable[object], limit_per_source: int) -> tuple[list[JobRecord], list[str]]:
    all_records: list[JobRecord] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(spider.fetch, limit_per_source): spider.source for spider in spiders}
        for future in as_completed(futures):
            source = futures[future]
            try:
                result = future.result()
                all_records.extend(result.records)
                print(f"[ok] {source}: {len(result.records)} records")
            except SpiderError as exc:
                failures.append(f"{source}: {exc}")
                print(f"[skip] {source}: {exc}")
            except Exception as exc:  # pragma: no cover
                failures.append(f"{source}: {exc}")
                print(f"[error] {source}: {exc}")
    return all_records, failures


def run_jobs_pipeline(
    limit_per_source: int,
    output_path: str,
    max_total: int | None = None,
    db_path: str | None = None,
    spiders: list[object] | None = None,
    region: str = "canarias",
) -> int:
    outcome = run_jobs_pipeline_with_outcome(
        limit_per_source=limit_per_source,
        output_path=output_path,
        max_total=max_total,
        db_path=db_path,
        spiders=spiders,
        region=region,
    )
    return outcome.exit_code


def run_jobs_pipeline_with_outcome(
    limit_per_source: int,
    output_path: str,
    max_total: int | None = None,
    db_path: str | None = None,
    spiders: list[object] | None = None,
    region: str = "canarias",
) -> PipelineOutcome:
    start = time.time()
    spiders = spiders or default_spiders(region)
    all_records, failures = _collect_records(spiders, limit_per_source)

    cleaned_records = [cleaned for record in all_records if (cleaned := _clean_record(record)) is not None]
    cleaned_records.sort(key=lambda record: (record.publication_date or "", record.source), reverse=True)
    output_records = _select_with_source_coverage(cleaned_records, max_total)
    mapped_records = annotate_job_degree_targets(output_records)
    repo = JobsRepository(db_path or DEFAULT_JOBS_DB)
    stats = repo.upsert_records(mapped_records)
    written = repo.export_csv(output_path)
    print(
        "[done] wrote {written} rows to {output} (inserted={inserted}, updated={updated}, unchanged={unchanged})".format(
            written=written,
            output=output_path,
            inserted=stats.inserted,
            updated=stats.updated,
            unchanged=stats.unchanged,
        )
    )
    if failures:
        print("[failures]")
        for failure in failures:
            print(f" - {failure}")
    return PipelineOutcome(
        exit_code=0,
        scraped=len(all_records),
        inserted=stats.inserted,
        updated=stats.updated,
        unchanged=stats.unchanged,
        failures=failures,
        elapsed_seconds=time.time() - start,
        strategy="scrape",
    )


def run_jobs_scale(**kwargs) -> int:
    return run_scaled(**kwargs)


def run_jobs_scale_with_outcome(
    *,
    output_path: str,
    db_path: str,
    time_limit_minutes: int = 45,
    max_total: int = 40_000,
) -> PipelineOutcome:
    start = time.time()
    stats = run_scaled(
        output_path=output_path,
        db_path=db_path,
        time_limit_minutes=time_limit_minutes,
        max_total=max_total,
        return_stats=True,
    )
    failures = list(stats.get("failures", []))
    return PipelineOutcome(
        exit_code=0,
        scraped=int(stats.get("scraped", 0)),
        inserted=int(stats.get("inserted", 0)),
        updated=int(stats.get("updated", 0)),
        unchanged=int(stats.get("unchanged", 0)),
        failures=failures,
        elapsed_seconds=time.time() - start,
        strategy="scale",
    )
