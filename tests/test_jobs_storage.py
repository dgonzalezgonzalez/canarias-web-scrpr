from src.canarias_uni_ml.jobs.models import JobRecord
from src.canarias_uni_ml.jobs.storage import JOB_FIELDS, JobsRepository, canonical_job_key


def _record(
    *,
    source: str = "sce",
    external_id: str = "1",
    source_url: str = "https://example.org/jobs/1",
    title: str = "title-1",
) -> JobRecord:
    return JobRecord(
        source=source,
        external_id=external_id,
        title=title,
        company="Acme",
        description="desc",
        salary_text=None,
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        salary_period=None,
        publication_date="2026-04-22T00:00:00+00:00",
        update_date=None,
        source_url=source_url,
        scraped_at=JobRecord.now(),
    )


def test_jobs_repository_insert_update_unchanged(tmp_path):
    repo = JobsRepository(tmp_path / "jobs.db")

    inserted = repo.upsert_records([_record(title="title-v1")])
    assert inserted.inserted == 1
    assert inserted.updated == 0
    assert inserted.unchanged == 0

    unchanged = repo.upsert_records([_record(title="title-v1")])
    assert unchanged.inserted == 0
    assert unchanged.updated == 0
    assert unchanged.unchanged == 1

    updated = repo.upsert_records([_record(title="title-v2")])
    assert updated.inserted == 0
    assert updated.updated == 1
    assert updated.unchanged == 0

    output = tmp_path / "jobs.csv"
    written = repo.export_csv(output)
    assert written == 1
    content = output.read_text(encoding="utf-8")
    assert "title-v2" in content


def test_jobs_repository_uses_source_url_when_external_id_missing(tmp_path):
    repo = JobsRepository(tmp_path / "jobs.db")
    record = _record(external_id="", source_url="https://example.org/jobs/same")
    stats = repo.upsert_records([record, record])
    assert stats.inserted == 1
    assert stats.unchanged == 1


def test_canonical_job_key_requires_identity_fields():
    record = _record(external_id="", source_url="", title="")
    record.company = None
    record.publication_date = None
    record.raw_location = None
    try:
        canonical_job_key(record)
        assert False, "expected ValueError"
    except ValueError:
        assert True


def test_jobs_repository_compacts_to_latest_logical_record(tmp_path):
    repo = JobsRepository(tmp_path / "jobs.db")
    row_v1 = _record(external_id="", source_url="https://example.org/jobs/same", title="title-v1")
    row_v2 = _record(external_id="", source_url="https://example.org/jobs/same", title="title-v2")
    with repo._connect() as conn:  # characterization: simulate old duplicated storage state
        columns = ("job_key", *JOB_FIELDS, "payload_hash", "first_seen_at", "last_seen_at", "updated_at")
        quoted = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        base = ["legacy::1", *[row_v1.to_row().get(name) for name in JOB_FIELDS], "h1", "2026-01-01", "2026-01-01", "2026-01-01"]
        newer = ["legacy::2", *[row_v2.to_row().get(name) for name in JOB_FIELDS], "h2", "2026-01-02", "2026-01-02", "2026-01-03"]
        conn.execute(f"INSERT INTO jobs ({quoted}) VALUES ({placeholders})", tuple(base))
        conn.execute(f"INSERT INTO jobs ({quoted}) VALUES ({placeholders})", tuple(newer))
        conn.commit()

    stats = repo.compact_latest_records()
    assert stats.before == 2
    assert stats.after == 1
    assert stats.removed == 1

    output = tmp_path / "jobs.csv"
    repo.export_csv(output)
    rows = output.read_text(encoding="utf-8")
    assert "title-v2" in rows


def test_jobs_repository_merges_secondary_duplicate_signature(tmp_path):
    repo = JobsRepository(tmp_path / "jobs.db")
    base = _record(
        source="jobspy_indeed",
        external_id="indeed_1",
        source_url="https://es.indeed.com/viewjob?jk=aaa",
        title="Especialista de Mantenimiento ( Sustitución 40 h ) - SHC",
    )
    base.company = "Hilton Grand Vacations"
    base.publication_date = "2026-04-23T00:00:00"
    base.municipality = "Club Miraverde"
    newer = _record(
        source="jobspy_indeed",
        external_id="indeed_2",
        source_url="https://es.indeed.com/viewjob?jk=bbb",
        title=base.title,
    )
    newer.company = base.company
    newer.publication_date = base.publication_date
    newer.municipality = base.municipality
    newer.description = "updated description"

    first = repo.upsert_records([base])
    second = repo.upsert_records([newer])
    assert first.inserted == 1
    assert second.updated == 1

    output = tmp_path / "jobs.csv"
    repo.export_csv(output)
    lines = output.read_text(encoding="utf-8")
    assert lines.count("Especialista de Mantenimiento") == 1
    assert "updated description" in lines


def test_jobs_repository_deactivates_only_missing_source_snapshot(tmp_path):
    repo = JobsRepository(tmp_path / "jobs.db")
    first = _record(external_id="1", source_url="https://example.org/jobs/1", title="keep")
    second = _record(external_id="2", source_url="https://example.org/jobs/2", title="expire")
    repo.upsert_records([first, second])

    removed = repo.deactivate_missing_source("sce", [first])
    assert removed == 1
    assert len(repo.read_all()) == 2
    assert [item.title for item in repo.read_all(active_only=True)] == ["keep"]

    output = tmp_path / "active.csv"
    assert repo.export_csv(output) == 1
    assert "keep" in output.read_text(encoding="utf-8")
    assert "expire" not in output.read_text(encoding="utf-8")

    # A returning offer is reactivated even when its payload is unchanged.
    stats = repo.upsert_records([second])
    assert stats.unchanged == 1
    assert len(repo.read_all(active_only=True)) == 2
