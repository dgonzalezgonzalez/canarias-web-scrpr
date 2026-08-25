from src.canarias_uni_ml.jobs.models import JobRecord
from src.canarias_uni_ml.jobs.scale import _clean_record
from src.canarias_uni_ml.normalization.geography import normalize_geography


def test_normalize_geography_alias():
    result = normalize_geography(None, "Las Palmas de G.C.", None, None)
    assert result.municipality == "Las Palmas de Gran Canaria"
    assert result.island == "Gran Canaria"
    assert result.province == "Las Palmas"


def test_normalize_cantabria_municipality_has_no_island():
    result = normalize_geography(None, "PIELAGOS", None, "PIELAGOS / Cantabria")
    assert result.municipality == "Piélagos"
    assert result.island is None
    assert result.province == "Cantabria"


def test_clean_record_normalizes_geography_and_contract():
    record = JobRecord(
        source="jobspy_indeed",
        external_id="1",
        title="Analista",
        company="Empresa",
        description="Desc",
        salary_text=None,
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        salary_period=None,
        publication_date="2026-04-20",
        update_date=None,
        province=None,
        municipality="Las Palmas de G.C.",
        island=None,
        raw_location="Las Palmas de G.C.",
        contract_type="CONTRATO INDEFINIDO",
        workday=None,
        schedule=None,
        vacancies=None,
        source_url="https://example.org/job/1",
        scraped_at=JobRecord.now(),
    )
    cleaned = _clean_record(record)
    assert cleaned is not None
    assert cleaned.municipality == "Las Palmas de Gran Canaria"
    assert cleaned.island == "Gran Canaria"
    assert cleaned.province == "Las Palmas"
    assert cleaned.contract_type == "indefinido"
    assert cleaned.contract_type_raw == "CONTRATO INDEFINIDO"
