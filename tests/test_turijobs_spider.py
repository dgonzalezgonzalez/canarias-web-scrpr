from src.canarias_uni_ml.jobs.spiders.turijobs import TurijobsSpider


def test_turijobs_cantabria_detail_rejects_out_of_region_province():
    assert TurijobsSpider._is_cantabria_location("Cantabria", "Santander") is True
    assert TurijobsSpider._is_cantabria_location("Bizkaia", "Bilbao") is False
    assert TurijobsSpider._is_cantabria_location(None, "Santander") is True
