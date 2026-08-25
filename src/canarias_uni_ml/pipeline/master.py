from __future__ import annotations

from ..alignment.pipeline import run_alignment_pipeline
from ..config import Settings
from ..degrees.catalog import write_degree_catalog
from ..jobs.pipeline import run_jobs_pipeline


def run_master_pipeline(
    *,
    settings: Settings,
    skip_jobs: bool,
    skip_degrees: bool,
    jobs_limit_per_source: int,
    jobs_max_total: int | None,
    provider_name: str,
    model: str | None,
    jobs_csv_path: str,
    degrees_csv_path: str,
    alignment_db_path: str,
    jobs_region: str = "canarias",
) -> int:
    if not skip_jobs:
        run_jobs_pipeline(
            limit_per_source=jobs_limit_per_source,
            output_path=jobs_csv_path,
            max_total=jobs_max_total,
            db_path=str(settings.jobs_db_output),
            region=jobs_region,
        )

    if not skip_degrees:
        write_degree_catalog(
            output_path=degrees_csv_path,
            fixture_path=None,
            live_universities=False,
            live_aneca=False,
            cycles=("grado", "master", "doctorado"),
            limit=None,
            max_pages=None,
            http_timeout=30,
            skip_description_fetch=False,
            with_report_text=False,
            min_inventory_completeness=None,
            require_all_scoped_universities=False,
            min_description_coverage=None,
            canary_only=False,
            resolve_university_memory=False,
            db_path=str(settings.degrees_db_output),
        )

    return run_alignment_pipeline(
        jobs_csv_path=jobs_csv_path,
        degrees_csv_path=degrees_csv_path,
        db_path=alignment_db_path,
        provider_name=provider_name,
        model=model,
        settings=settings,
    )
