from __future__ import annotations

import random
import time

from ..normalization import normalize_contract_type, normalize_geography
from .degree_mapping import annotate_job_degree_targets
from .models import JobRecord
from .spiders.base import SpiderError, SpiderResult
from .spiders.jobspy_spider import JobspySpider
from .spiders.sce import SCESpider
from .storage import JobsRepository
from .spiders.turijobs import TurijobsSpider
from .utils import clean_text, infer_province_from_island, parse_date, write_csv


CANARY_LOCATIONS = [
    "Canary Islands",
    "Islas Canarias",
    "Las Palmas",
    "Santa Cruz de Tenerife",
    "Tenerife",
    "Gran Canaria",
    "Lanzarote",
    "Fuerteventura",
    "La Palma",
    "Gomera",
    "El Hierro",
    "Las Palmas de Gran Canaria",
    "Santa Cruz de Tenerife",
    "San Cristóbal de La Laguna",
    "Arucas",
    "Puerto del Rosario",
    "San Bartolomé de Tirajana",
    "Adeje",
    "Granadilla de Abona",
    "Puerto de la Cruz",
    "Arona",
    "Santiago del Teide",
    "Los Cristianos",
    "Playa de las Américas",
    "Maspalomas",
    "Corralejo",
]

SEARCH_TERMS = [
    "",
    "administrativo",
    "comercial",
    "hosteleria",
    "ingeniero",
    "dependiente",
    "marketing",
    "logistica",
    "enfermeria",
    "atencion al cliente",
]

DEFAULT_MAX_TOTAL = 40_000
DEFAULT_INDEED_SHARE = 0.82
DEFAULT_SCE_SHARE = 0.13
DEFAULT_TURIJOBS_SHARE = 0.05


class ScalableJobspySpider:
    source = "jobspy"

    def __init__(self, max_runtime_seconds: int = 2700) -> None:
        self.max_runtime_seconds = max_runtime_seconds
        self.start_time = None
        self.records: list[JobRecord] = []
        self.errors: list[str] = []

    def _time_remaining(self) -> bool:
        if self.start_time is None:
            return True
        elapsed = time.time() - self.start_time
        return elapsed < self.max_runtime_seconds

    def fetch(self, limit: int) -> SpiderResult:
        from jobspy import scrape_jobs

        self.start_time = time.time()
        self.records = []
        target = min(limit, 40_000)
        seen_urls: set[str] = set()
        seen_ids: set[str] = set()
        spider = JobspySpider()
        location = "Canary Islands, Spain"
        offset = 0
        batch_size = 100

        while len(self.records) < target and self._time_remaining():
            try:
                jobs = scrape_jobs(
                    site_name=["indeed"],
                    search_term="",
                    location=location,
                    results_wanted=batch_size,
                    country_indeed="spain",
                    offset=offset,
                    timeout_seconds=30,
                )
            except Exception as exc:
                self.errors.append(str(exc))
                break

            if jobs is None or len(jobs) == 0:
                break

            added_in_batch = 0
            for _, row in jobs.iterrows():
                if len(self.records) >= target or not self._time_remaining():
                    break
                record = spider._convert_row_to_record(row)
                if not record:
                    continue

                source_url = (clean_text(record.source_url) or "").lower()
                fallback_id = f"{record.source}|{record.external_id}"
                if source_url and source_url in seen_urls:
                    continue
                if fallback_id in seen_ids:
                    continue

                if source_url:
                    seen_urls.add(source_url)
                seen_ids.add(fallback_id)
                self.records.append(record)
                added_in_batch += 1

            if len(jobs) < batch_size or added_in_batch == 0:
                break

            offset += batch_size
            time.sleep(0.5)

        if not self.records:
            raise SpiderError(f"No jobs scraped. Errors: {self.errors[:3]}")
        return SpiderResult(source=self.source, records=self.records[:limit])


def _target_counts(
    max_total: int,
    indeed_share: float,
    sce_share: float,
    turijobs_share: float,
) -> dict[str, int]:
    shares_sum = indeed_share + sce_share + turijobs_share
    if shares_sum <= 0:
        indeed_share, sce_share, turijobs_share = (
            DEFAULT_INDEED_SHARE,
            DEFAULT_SCE_SHARE,
            DEFAULT_TURIJOBS_SHARE,
        )
        shares_sum = indeed_share + sce_share + turijobs_share
    indeed_share /= shares_sum
    sce_share /= shares_sum
    turijobs_share /= shares_sum

    indeed_target = int(max_total * indeed_share)
    sce_target = int(max_total * sce_share)
    turijobs_target = max_total - indeed_target - sce_target
    return {
        "indeed": indeed_target,
        "sce": sce_target,
        "turijobs": turijobs_target,
    }


def _canonical_dedupe_key(record: JobRecord) -> str:
    url = (clean_text(record.source_url) or "").lower()
    if url:
        return f"url::{url}"
    external_id = clean_text(record.external_id)
    if external_id:
        return f"id::{clean_text(record.source)}::{external_id}"
    return "row::{source}::{title}::{company}::{date}::{loc}".format(
        source=clean_text(record.source) or "",
        title=clean_text(record.title) or "",
        company=clean_text(record.company) or "",
        date=clean_text(record.publication_date) or "",
        loc=clean_text(record.raw_location or record.municipality or "") or "",
    )


def _clean_record(record: JobRecord) -> JobRecord | None:
    title = clean_text(record.title)
    if not title:
        return None
    source = clean_text(record.source) or "unknown"
    raw_location = clean_text(record.raw_location)
    geography = normalize_geography(record.province, record.municipality, record.island, raw_location)
    if not geography.raw_location:
        raw_location = clean_text(
            " / ".join(filter(None, [geography.municipality, geography.island, geography.province]))
        )
    else:
        raw_location = geography.raw_location
    contract = normalize_contract_type(record.contract_type)

    return JobRecord(
        source=source.lower(),
        external_id=clean_text(record.external_id) or "",
        title=title,
        company=clean_text(record.company),
        description=clean_text(record.description),
        salary_text=clean_text(record.salary_text),
        salary_min=clean_text(record.salary_min),
        salary_max=clean_text(record.salary_max),
        salary_currency=clean_text(record.salary_currency),
        salary_period=clean_text(record.salary_period),
        publication_date=parse_date(record.publication_date),
        update_date=parse_date(record.update_date),
        closing_date=parse_date(record.closing_date),
        is_active=_coerce_active(record.is_active),
        province=geography.province,
        province_raw=clean_text(record.province),
        municipality=geography.municipality,
        municipality_raw=clean_text(record.municipality),
        island=geography.island,
        island_raw=clean_text(record.island),
        raw_location=raw_location,
        contract_type=contract.contract_type,
        contract_type_raw=clean_text(record.contract_type),
        workday=clean_text(record.workday),
        schedule=clean_text(record.schedule),
        vacancies=clean_text(record.vacancies),
        source_url=clean_text(record.source_url) or "",
        scraped_at=record.scraped_at,
    )


def _coerce_active(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    return str(value).strip().casefold() not in {"", "0", "false", "no", "off"}


def _clean_and_dedupe(records: list[JobRecord], max_total: int) -> list[JobRecord]:
    unique: list[JobRecord] = []
    seen: set[str] = set()

    for record in records:
        cleaned = _clean_record(record)
        if not cleaned:
            continue
        key = _canonical_dedupe_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)

    unique.sort(key=lambda r: (r.publication_date or "", r.source), reverse=True)
    return unique[:max_total]


def run_scaled(
    output_path: str,
    db_path: str | None = None,
    time_limit_minutes: int = 45,
    max_total: int = DEFAULT_MAX_TOTAL,
    indeed_share: float = DEFAULT_INDEED_SHARE,
    sce_share: float = DEFAULT_SCE_SHARE,
    turijobs_share: float = DEFAULT_TURIJOBS_SHARE,
    sce_only: bool = False,
    return_stats: bool = False,
) -> int | dict[str, object]:
    time_limit_seconds = time_limit_minutes * 60
    all_records: list[JobRecord] = []
    failures: list[str] = []

    start_total = time.time()

    print(f"[start] Scaling for {time_limit_minutes} minutes (max_total={max_total})...")

    if sce_only:
        print("[start] SCE only mode")
        try:
            spider = SCESpider()
            result = spider.fetch(max_total)
            all_records.extend(result.records)
            print(f"[ok] SCE: {len(result.records)} records")
        except (SpiderError, Exception) as exc:
            failures.append(f"SCE: {exc}")
            print(f"[skip] SCE: {exc}")
    else:
        targets = _target_counts(max_total, indeed_share, sce_share, turijobs_share)
        print(
            "[plan] target distribution "
            f"indeed={targets['indeed']} sce={targets['sce']} turijobs={targets['turijobs']}"
        )

        # SCE first: usually capped by site supply, so we try to fetch all and then cap at target.
        try:
            spider = SCESpider()
            result = spider.fetch(max_total)
            sce_records = result.records[: targets["sce"]]
            all_records.extend(sce_records)
            print(f"[ok] SCE: {len(sce_records)} records")
        except (SpiderError, Exception) as exc:
            failures.append(f"SCE: {exc}")
            print(f"[skip] SCE: {exc}")

        if len(all_records) < max_total and time.time() - start_total < time_limit_seconds - 30:
            try:
                spider = TurijobsSpider()
                # Turijobs detail scraping is expensive; keep it as a bounded complementary slice.
                turijobs_cap = min(targets["turijobs"], 120)
                if turijobs_cap > 0:
                    result = spider.fetch(turijobs_cap)
                    turijobs_records = result.records[:turijobs_cap]
                    all_records.extend(turijobs_records)
                    print(f"[ok] Turijobs: {len(turijobs_records)} records")
            except (SpiderError, Exception) as exc:
                failures.append(f"Turijobs: {exc}")
                print(f"[skip] Turijobs: {exc}")

        remaining_slots = max_total - len(all_records)
        if remaining_slots > 0 and time.time() - start_total < time_limit_seconds - 20:
            spider_start = time.time()
            spider = ScalableJobspySpider(max_runtime_seconds=time_limit_seconds - 10)
            indeed_target = remaining_slots

            try:
                result = spider.fetch(indeed_target)
                all_records.extend(result.records)
                spider_elapsed = time.time() - spider_start
                print(f"[ok] Indeed: {len(result.records)} records in {spider_elapsed:.1f}s")
            except (SpiderError, Exception) as exc:
                failures.append(f"Indeed(JobSpy): {exc}")
                print(f"[skip] Indeed(JobSpy): {exc}")

    total_elapsed = time.time() - start_total
    cleaned_records = _clean_and_dedupe(all_records, max_total=max_total)
    mapped_records = annotate_job_degree_targets(cleaned_records)
    inserted = 0
    updated = 0
    unchanged = 0
    if db_path:
        repo = JobsRepository(db_path)
        upsert = repo.upsert_records(mapped_records)
        inserted, updated, unchanged = upsert.inserted, upsert.updated, upsert.unchanged
        written = repo.export_csv(output_path)
    else:
        written = write_csv(mapped_records, output_path)

    source_counts: dict[str, int] = {}
    for record in mapped_records:
        source_root = (record.source or "").split("_")[0]
        source_counts[source_root] = source_counts.get(source_root, 0) + 1

    print(f"\n[done] {written} cleaned records in {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")
    print(f"[done] Wrote to {output_path}")
    if source_counts:
        print("[distribution]")
        for source_name, count in sorted(source_counts.items(), key=lambda kv: kv[1], reverse=True):
            print(f" - {source_name}: {count}")

    if failures:
        print("\n[failures]")
        for failure in failures:
            print(f" - {failure}")

    if return_stats:
        return {
            "scraped": len(all_records),
            "written": written,
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "failures": failures,
            "elapsed_seconds": total_elapsed,
        }
    return 0
