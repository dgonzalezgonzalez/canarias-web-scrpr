from src.canarias_uni_ml.jobs.utils import parse_date


def test_parse_date_preserves_iso_month_day_order():
    assert parse_date("2026-08-12T00:00:00") == "2026-08-12T00:00:00"


def test_parse_date_keeps_spanish_numeric_dates_day_first():
    assert parse_date("12/08/2026") == "2026-08-12T00:00:00"
