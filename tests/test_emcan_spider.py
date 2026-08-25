from src.canarias_uni_ml.jobs.spiders.emcan import EmcanSpider


LISTING_HTML = """
<html><body>
  <a href="detalleOferta.do?CA=06&id=062026002089&idFlujo=abc&modo=inicio">Auxiliar</a>
  <a href="detalleOferta.do?CA=13&id=132026005630&idFlujo=abc&modo=inicio">Madrid</a>
  <a href="busquedaOfertas.do?botonNavegacion=2&pagina=2">2</a>
</body></html>
"""


DETAIL_HTML = """
<html><body>
  <h3>Datos de la oferta número: 062026002089</h3>
  <p>Fecha de inicio: 19/06/2026</p>
  <p>Fecha de fin: 04/07/2026</p>
  <p>Provincia: CANTABRIA</p>
  <h4>Descripción</h4>
  <p>1 AUXILIAR ADMINISTRATIVO/A DE PERSONAL.</p>
  <h4>Datos</h4>
  <p>Localidad de Ubicación del Puesto: PIELAGOS(CANTABRIA)</p>
  <h5>Datos adicionales</h5>
  <p>ASESORÍA PRECISA AUXILIAR PARA GESTIÓN DOCUMENTAL Y CONTRATOS.</p>
  <p>SE OFRECE CONTRATO LABORAL INDEFINIDO, A JORNADA PARCIAL DE 20H.</p>
  <p>SALARIO: SEGÚN CONVENIO VIGENTE.</p>
  <h5>Datos de contacto</h5>
  <p>Texto de contacto que no debe formar parte de la descripción.</p>
  <h4>Requerimientos</h4>
</body></html>
"""


def test_emcan_listing_keeps_only_cantabria_and_pagination():
    details, pages = EmcanSpider._parse_listing_links(
        LISTING_HTML,
        "https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do",
    )
    assert len(details) == 1
    assert "062026002089" in details[0]
    assert len(pages) == 1


def test_emcan_listing_accepts_current_listado_pagination_shape():
    html = """
    <a href="detalleOferta.do?id=062026002090">Oferta</a>
    <a href="listadoOfertas.do?idFlujo=flow-123&indice=41&modo=pagina">2</a>
    """
    details, pages = EmcanSpider._parse_listing_links(
        html,
        "https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do",
    )
    assert len(details) == 1
    assert pages == [
        "https://www.sistemanacionalempleo.es/OfertaDifusionWEB/listadoOfertas.do?idFlujo=flow-123&indice=41&modo=pagina"
    ]


def test_emcan_session_cancelled_page_is_detected():
    assert EmcanSpider._is_session_cancelled("<html>Sesión Cancelada</html>") is True


def test_emcan_detail_parser_extracts_occupation_and_full_description():
    record = EmcanSpider._parse_detail(
        DETAIL_HTML,
        "https://www.sistemanacionalempleo.es/OfertaDifusionWEB/detalleOferta.do?id=062026002089",
    )
    assert record is not None
    assert record.external_id == "062026002089"
    assert record.title == "1 AUXILIAR ADMINISTRATIVO/A DE PERSONAL."
    assert "GESTIÓN DOCUMENTAL" in record.description
    assert "Texto de contacto" not in record.description
    assert record.municipality == "PIELAGOS"
    assert record.province == "Cantabria"
    assert record.publication_date == "2026-06-19T00:00:00"
    assert record.update_date is None
    assert record.contract_type == "INDEFINIDO"
    assert record.workday == "PARCIAL DE 20H"
    assert record.vacancies == "1"
