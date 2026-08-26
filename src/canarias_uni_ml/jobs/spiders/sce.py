from __future__ import annotations

import re
from urllib.parse import quote

import requests

from ..models import JobRecord
from ..utils import clean_text, infer_province_from_island, parse_date
from .base import SpiderError, SpiderResult


SCE_IFRAME_URL = (
    "https://www.gobiernodecanarias.org/empleo/sce/principal/componentes/"
    "buscadores_angular/index_ofertas_empleo.jsp"
)
SCE_API_URL = (
    "https://www3.gobiernodecanarias.org/empleo/SERELE-Inter/api/v2.0/"
    "ofertas/difusion?plataformaCliente="
    "LGOPTIMUSL5::APPMOVIL::ANDROID-2.1::V2.0"
)
SCE_DETAIL_URL = (
    "https://www.gobiernodecanarias.org/empleo/sce/principal/areas_tematicas/"
    "empleo/demanda_y_ofertas_de_empleo/buscador_ofertas_empleo.html"
    "?cod_buscar={code}&is_open=true"
)


class SCESpider:
    source = "sce"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    def fetch(self, limit: int) -> SpiderResult:
        token = self._fetch_token()
        payload = self._fetch_payload(token)
        offers = payload.get("data", {}).get("ofertasDifusion", [])
        if not offers:
            raise SpiderError("SCE returned no offers")
        records = [self._normalize_offer(offer) for offer in offers]
        records.sort(key=lambda item: item.publication_date or "", reverse=True)
        return SpiderResult(source=self.source, records=records[:limit], complete=len(records) <= limit)

    def _fetch_token(self) -> str:
        response = self.session.get(SCE_IFRAME_URL, timeout=30)
        response.raise_for_status()
        match = re.search(r'token="([^"]+)"', response.text)
        if not match:
            raise SpiderError("Could not extract SCE JWT token from iframe")
        return match.group(1)

    def _fetch_payload(self, token: str) -> dict:
        response = self.session.get(
            SCE_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _normalize_offer(self, offer: dict) -> JobRecord:
        sequence = clean_text(offer.get("codigoSecuenciaOferta")) or ""
        island = clean_text(offer.get("islaUbicacionPuesto"))
        municipality = clean_text(offer.get("municipioUbicacionPuesto"))
        salary_min = clean_text(offer.get("salarioMinimo"))
        salary_max = clean_text(offer.get("salarioMaximo"))
        salary_text = None
        if salary_min and salary_min != "-" and salary_max and salary_max != "-":
            salary_text = f"{salary_min} - {salary_max}"
        elif salary_min and salary_min != "-":
            salary_text = salary_min
        elif salary_max and salary_max != "-":
            salary_text = salary_max
        description = clean_text(offer.get("informacionAdicional"))
        if description == "-":
            description = None

        external_id = ".".join(
            filter(
                None,
                [
                    clean_text(offer.get("codigoCAOferta")),
                    clean_text(offer.get("codigoAnioOferta")),
                    sequence,
                ],
            )
        )
        return JobRecord(
            source=self.source,
            external_id=external_id,
            title=clean_text(offer.get("ocupacionSolicitadaDefinicion")) or "Oferta SCE",
            company=self._nullish(offer.get("razonSocialEmpresario")),
            description=description,
            salary_text=salary_text,
            salary_min=self._nullish(salary_min),
            salary_max=self._nullish(salary_max),
            salary_currency="EUR" if salary_text else None,
            salary_period=None,
            publication_date=parse_date(offer.get("fechaPublicacion")),
            update_date=None,
            province=infer_province_from_island(island),
            municipality=municipality,
            island=island,
            raw_location=clean_text(" / ".join(filter(None, [municipality, island]))),
            contract_type=self._nullish(offer.get("tipoRelacionContractual")),
            workday=None,
            schedule=self._nullish(offer.get("horarioTrabajo")),
            vacancies=self._nullish(offer.get("numeroPuestosOfrecidos")),
            source_url=SCE_DETAIL_URL.format(code=quote(sequence)),
            scraped_at=JobRecord.now(),
        )

    @staticmethod
    def _nullish(value: str | None) -> str | None:
        cleaned = clean_text(value)
        if cleaned in {None, "-", ""}:
            return None
        return cleaned
