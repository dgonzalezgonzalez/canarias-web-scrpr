from src.canarias_uni_ml.jobs.spiders.jobspy_spider import JobspySpider


def test_jobspy_external_ids_are_stable_for_provider_urls():
    assert JobspySpider._generate_external_id(
        "https://es.indeed.com/viewjob?jk=abc123&utm_source=x", "indeed"
    ) == "indeed_abc123"
    assert JobspySpider._generate_external_id(
        "https://www.linkedin.com/jobs/view/987654321/", "linkedin"
    ) == "linkedin_987654321"
    first = JobspySpider._generate_external_id("https://example.org/jobs/one", "indeed")
    second = JobspySpider._generate_external_id("https://example.org/jobs/two", "indeed")
    assert first == JobspySpider._generate_external_id("https://example.org/jobs/one", "indeed")
    assert first != second


def test_jobspy_cantabria_filter_rejects_out_of_region_and_cantabria_is_not_municipality():
    spider = JobspySpider(region="cantabria")
    assert spider._convert_row_to_record(
        {"title": "Operario", "location": "Bilbao, Bizkaia", "site": "indeed"}
    ) is None
    record = spider._convert_row_to_record(
        {"title": "Operario", "location": "Cantabria, Spain", "site": "indeed"}
    )
    assert record is not None
    assert record.province == "Cantabria"
    assert record.municipality is None


def test_jobspy_missing_salary_values_do_not_crash():
    spider = JobspySpider(region="cantabria")
    record = spider._convert_row_to_record(
        {
            "title": "Administrativo",
            "company": "Acme",
            "location": "Santander, Cantabria",
            "site": "indeed",
            "min_amount": float("nan"),
            "max_amount": "<NA>",
        }
    )
    assert record is not None
    assert record.salary_min is None
    assert record.salary_max is None
