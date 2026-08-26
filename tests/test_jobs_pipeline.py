from src.canarias_uni_ml.jobs.models import JobRecord
from src.canarias_uni_ml.jobs.pipeline import (
    _select_with_source_coverage,
    run_jobs_pipeline,
    run_jobs_pipeline_with_outcome,
    run_jobs_scale_with_outcome,
)
from src.canarias_uni_ml.jobs.spiders.base import SpiderError, SpiderResult


def _record(source: str, idx: int, *, title: str | None = None) -> JobRecord:
    return JobRecord(
        source=source,
        external_id=str(idx),
        title=title or f"title-{idx}",
        company=None,
        description=None,
        salary_text=None,
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        salary_period=None,
        publication_date=f"2026-04-{20+idx:02d}",
        update_date=None,
        source_url=f"https://example.org/{source}/{idx}",
        scraped_at=JobRecord.now(),
    )


def test_select_with_source_coverage_keeps_at_least_one_per_source():
    records = [
        _record("jobspy_indeed", 1),
        _record("jobspy_indeed", 2),
        _record("sce", 3),
        _record("sce", 4),
        _record("turijobs", 5),
        _record("turijobs", 6),
    ]
    selected = _select_with_source_coverage(records, 4)
    assert len(selected) == 4
    assert {record.source for record in selected} == {"jobspy_indeed", "sce", "turijobs"}


class StaticSpider:
    def __init__(self, source: str, records: list[JobRecord], *, complete: bool = True) -> None:
        self.source = source
        self._records = records
        self._complete = complete

    def fetch(self, limit: int) -> SpiderResult:
        return SpiderResult(source=self.source, records=self._records[:limit], complete=self._complete)


class FailingSpider:
    def __init__(self, source: str) -> None:
        self.source = source

    def fetch(self, limit: int) -> SpiderResult:  # pragma: no cover - expected to raise
        raise SpiderError("boom")


def test_run_jobs_pipeline_upserts_and_updates(tmp_path):
    output = tmp_path / "jobs.csv"
    db_path = tmp_path / "jobs.db"

    first_run = run_jobs_pipeline(
        limit_per_source=10,
        output_path=str(output),
        db_path=str(db_path),
        spiders=[StaticSpider("sce", [_record("sce", 1, title="title-v1")])],
    )
    assert first_run == 0

    second_run = run_jobs_pipeline(
        limit_per_source=10,
        output_path=str(output),
        db_path=str(db_path),
        spiders=[StaticSpider("sce", [_record("sce", 1, title="title-v2")])],
    )
    assert second_run == 0

    rows = output.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    assert "title-v2" in rows[1]


def test_run_jobs_pipeline_continues_when_one_source_fails(tmp_path):
    output = tmp_path / "jobs.csv"
    db_path = tmp_path / "jobs.db"
    exit_code = run_jobs_pipeline(
        limit_per_source=10,
        output_path=str(output),
        db_path=str(db_path),
        spiders=[
            FailingSpider("turijobs"),
            StaticSpider("sce", [_record("sce", 1)]),
        ],
    )
    assert exit_code == 0
    assert output.exists()


def test_run_jobs_pipeline_all_sources_fail_preserves_previous_snapshot(tmp_path):
    output = tmp_path / "jobs.csv"
    db_path = tmp_path / "jobs.db"
    output.write_text("previous\n", encoding="utf-8")
    exit_code = run_jobs_pipeline(
        limit_per_source=10,
        output_path=str(output),
        db_path=str(db_path),
        spiders=[FailingSpider("emcan"), FailingSpider("trabajocantabria")],
    )
    assert exit_code == 1
    assert output.read_text(encoding="utf-8") == "previous\n"


def test_run_jobs_pipeline_with_outcome_reports_updates(tmp_path):
    output = tmp_path / "jobs.csv"
    db_path = tmp_path / "jobs.db"
    outcome = run_jobs_pipeline_with_outcome(
        limit_per_source=10,
        output_path=str(output),
        db_path=str(db_path),
        spiders=[StaticSpider("sce", [_record("sce", 1, title="title-v1")])],
    )
    assert outcome.exit_code == 0
    assert outcome.inserted == 1
    assert outcome.strategy == "scrape"


def test_run_jobs_pipeline_deactivates_missing_complete_source_rows(tmp_path):
    output = tmp_path / "jobs.csv"
    db_path = tmp_path / "jobs.db"
    old = _record("emcan", 1, title="old")
    new = _record("emcan", 2, title="new")
    run_jobs_pipeline(
        limit_per_source=10,
        output_path=str(output),
        db_path=str(db_path),
        spiders=[StaticSpider("emcan", [old, new])],
    )
    run_jobs_pipeline(
        limit_per_source=10,
        output_path=str(output),
        db_path=str(db_path),
        spiders=[StaticSpider("emcan", [new])],
    )
    rows = output.read_text(encoding="utf-8")
    assert "new" in rows
    assert "old" not in rows


def test_run_jobs_pipeline_keeps_rows_for_partial_source(tmp_path):
    output = tmp_path / "jobs.csv"
    db_path = tmp_path / "jobs.db"
    old = _record("jobspy_indeed", 1, title="old")
    new = _record("jobspy_indeed", 2, title="new")
    run_jobs_pipeline(
        limit_per_source=10,
        output_path=str(output),
        db_path=str(db_path),
        spiders=[StaticSpider("jobspy", [old, new], complete=False)],
    )
    run_jobs_pipeline(
        limit_per_source=10,
        output_path=str(output),
        db_path=str(db_path),
        spiders=[StaticSpider("jobspy", [new], complete=False)],
    )
    rows = output.read_text(encoding="utf-8")
    assert "new" in rows
    assert "old" in rows


def test_run_jobs_scale_with_outcome_uses_scale_stats(tmp_path, monkeypatch):
    def fake_run_scaled(**kwargs):
        return {
            "scraped": 100,
            "written": 90,
            "inserted": 70,
            "updated": 10,
            "unchanged": 10,
            "failures": ["x"],
        }

    monkeypatch.setattr("src.canarias_uni_ml.jobs.pipeline.run_scaled", fake_run_scaled)
    outcome = run_jobs_scale_with_outcome(
        output_path=str(tmp_path / "jobs.csv"),
        db_path=str(tmp_path / "jobs.db"),
        time_limit_minutes=20,
        max_total=123,
    )
    assert outcome.exit_code == 0
    assert outcome.scraped == 100
    assert outcome.inserted == 70
    assert outcome.strategy == "scale"
