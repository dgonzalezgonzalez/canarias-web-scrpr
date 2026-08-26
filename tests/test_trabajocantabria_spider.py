from src.canarias_uni_ml.jobs.spiders.trabajocantabria import TrabajoCantabriaSpider


LISTING_HTML = """
<html><body>
  <a href="/oferta/administrativo-a-contable-11">Administrativo/a contable</a>
  <a href="/ofertas/">Volver</a>
  <a href="/oferta/administrativo-a-contable-11">Ver oferta</a>
</body></html>
"""


DETAIL_HTML = """
<html><body>
<h1>Administrativo/a contable</h1>
<p>Publicada: miércoles, 19 de agosto de 2026</p>
<h4>Fecha fin inscripciones</h4><p>31/08/2026</p>
  <h4>Fecha inicio inscripciones</h4><p>19/08/2026</p>
  <h4>Descripción</h4>
  <p>Despacho profesional busca incorporar un/a Administrativo/a Contable.</p>
  <h4>Vacantes</h4><p>1</p>
  <p>Se ofrece:</p><ul><li>Contrato estable e indefinido</li><li>30 horas semanales</li></ul>
  <p>Funciones principales:</p><p>Registro de facturas y conciliación bancaria.</p>
  <h4>Localidad, Provincia</h4><p>TORRELAVEGA, Cantabria</p>
  <h4>Nivel Formativo y Académico mínimo</h4><p>Ciclo de grado medio o FP I</p>
  <h4>Duración contrato</h4><p>Indefinido</p>
  <h4>Tipo de Jornada</h4><p>Intensiva/Continua</p>
  <h4>Salario</h4><p>Según Convenio</p>
</body></html>
"""


def test_trabajocantabria_listing_deduplicates_offer_links():
    urls = TrabajoCantabriaSpider._parse_listing_links(
        LISTING_HTML,
        "https://www.trabajocantabria.com/ofertas/",
    )
    assert urls == ["https://www.trabajocantabria.com/oferta/administrativo-a-contable-11"]


def test_trabajocantabria_detail_parser_keeps_functions_and_conditions():
    record = TrabajoCantabriaSpider._parse_detail(
        DETAIL_HTML,
        "https://www.trabajocantabria.com/oferta/administrativo-a-contable-11",
    )
    assert record is not None
    assert record.external_id == "administrativo-a-contable-11"
    assert record.publication_date == "2026-08-19T00:00:00"
    assert record.closing_date == "2026-08-31T00:00:00"
    assert record.municipality == "Torrelavega"
    assert record.province == "Cantabria"
    assert "Registro de facturas" in record.description
    assert "Contrato estable" in record.description
    assert "Nivel Formativo" in record.description
    assert record.vacancies == "1"
    assert record.contract_type == "Indefinido"
    assert record.workday == "Intensiva/Continua"


def test_trabajocantabria_scalar_section_does_not_consume_next_heading():
    lines = ["Salario", "Tipo de Jornada", "Continua"]
    assert TrabajoCantabriaSpider._section(lines, "Salario") is None


def test_trabajocantabria_numeric_date_is_day_first():
    lines = ["Fecha inicio inscripciones", "12/08/2026"]
    assert TrabajoCantabriaSpider._publication_date(lines) == "2026-08-12T00:00:00"
