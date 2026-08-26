from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from ..models import JobRecord
from ..utils import clean_text
from .base import SpiderError, SpiderResult


TRABAJO_CANTABRIA_LIST_URL = "https://www.trabajocantabria.com/ofertas/"
SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


class TrabajoCantabriaSpider:
    """Public active offers from CEOE-CEPYME Cantabria's placement agency."""

    source = "trabajocantabria"

    def __init__(self, list_url: str = TRABAJO_CANTABRIA_LIST_URL) -> None:
        self.list_url = list_url
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; canarias-cantabria-unis-ml/1.0; "
                    "+https://github.com/dgonzalezgonzalez/canarias-cantabria-unis-ml)"
                )
            }
        )

    def fetch(self, limit: int) -> SpiderResult:
        response = self.session.get(self.list_url, timeout=30)
        response.raise_for_status()
        detail_urls = self._parse_listing_links(response.text, response.url)
        if not detail_urls:
            raise SpiderError("Trabajo Cantabria returned no active offer links")

        records: list[JobRecord] = []
        detail_failures = 0
        for url in detail_urls:
            if len(records) >= limit:
                break
            try:
                detail_response = self.session.get(url, timeout=30)
                detail_response.raise_for_status()
                record = self._parse_detail(detail_response.text, detail_response.url)
            except (requests.RequestException, ValueError):
                detail_failures += 1
                continue
            if record is not None:
                records.append(record)

        if not records:
            raise SpiderError("Trabajo Cantabria detail pages could not be parsed")
        records.sort(key=lambda item: item.publication_date or "", reverse=True)
        return SpiderResult(
            source=self.source,
            records=records[:limit],
            complete=len(detail_urls) < limit and detail_failures == 0,
        )

    @staticmethod
    def _parse_listing_links(html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []
        for anchor in soup.find_all("a", href=True):
            absolute = urljoin(base_url, anchor["href"])
            path = urlsplit(absolute).path.rstrip("/")
            if re.fullmatch(r"/oferta/[^/]+", path):
                urls.append(absolute)
        return list(dict.fromkeys(urls))

    @classmethod
    def _parse_detail(cls, html: str, source_url: str) -> JobRecord | None:
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.find("h1")
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else None
        if not title:
            return None
        lines = [line for raw in soup.get_text("\n", strip=True).splitlines() if (line := clean_text(raw))]

        description = cls._description(lines)
        location_text = cls._section(lines, "Localidad, Provincia")
        municipality, province = cls._parse_location(location_text)
        publication_date = cls._publication_date(lines)
        closing_date = cls._section(lines, "Fecha fin inscripciones")
        vacancies = cls._section(lines, "Vacantes")
        contract_type = cls._section(lines, "Duración contrato")
        workday = cls._section(lines, "Tipo de Jornada")
        salary_text = cls._section(lines, "Salario")
        external_id = urlsplit(source_url).path.rstrip("/").rsplit("/", 1)[-1]

        return JobRecord(
            source=cls.source,
            external_id=external_id,
            title=title,
            company=None,
            description=description,
            salary_text=salary_text,
            salary_min=None,
            salary_max=None,
            salary_currency="EUR" if salary_text and re.search(r"(?:\beur\b|\beuros?\b|\u20ac)", salary_text, re.I) else None,
            salary_period=None,
            publication_date=publication_date,
            update_date=None,
            closing_date=cls._parse_date_value(closing_date),
            province=province or "Cantabria",
            municipality=municipality,
            island=None,
            raw_location=location_text,
            contract_type=contract_type,
            workday=workday,
            schedule=None,
            vacancies=vacancies,
            source_url=source_url,
            scraped_at=JobRecord.now(),
        )

    @staticmethod
    def _norm(value: str) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(char)
        ).strip()

    @classmethod
    def _section(cls, lines: list[str], label: str) -> str | None:
        target = cls._norm(label)
        index = next((i for i, line in enumerate(lines) if cls._norm(line) == target), None)
        if index is None:
            return None
        known_labels = {
            cls._norm(item)
            for item in {
                "Descripción",
                "Vacantes",
                "Localidad, Provincia",
                "Nivel Formativo y Académico mínimo",
                "Permisos de conducir",
                "Vehículo propio",
                "Duración contrato",
                "Tipo de Jornada",
                "Salario",
                "Fecha inicio inscripciones",
                "Fecha fin inscripciones",
                "Ámbitos de selección de candidatos/as",
                "Comparte esta oferta",
            }
        }
        for line in lines[index + 1 :]:
            if line not in {"* * *", "---"}:
                if cls._norm(line) in known_labels:
                    return None
                return clean_text(line)
        return None

    @classmethod
    def _description(cls, lines: list[str]) -> str | None:
        start = next((i for i, line in enumerate(lines) if cls._norm(line) == "descripcion"), None)
        if start is None:
            return None
        end_labels = {
            "localidad, provincia",
            "nivel formativo y academico minimo",
            "ambitos de seleccion de candidatos/as",
            "comparte esta oferta",
        }
        values: list[str] = []
        skip_next_vacancy_value = False
        for line in lines[start + 1 :]:
            normalized = cls._norm(line)
            if normalized in end_labels:
                break
            if normalized == "vacantes":
                skip_next_vacancy_value = True
                continue
            if skip_next_vacancy_value and re.fullmatch(r"\d+", line):
                skip_next_vacancy_value = False
                continue
            if line not in {"* * *", "---"}:
                values.append(line)
        structured: list[str] = []
        for label in (
            "Nivel Formativo y Académico mínimo",
            "Permisos de conducir",
            "Vehículo propio",
            "Ámbitos de selección de candidatos/as",
        ):
            value = cls._section(lines, label)
            if value:
                structured.append(f"{label}: {value}")
        return clean_text("\n".join([*values, *structured]))

    @classmethod
    def _publication_date(cls, lines: list[str]) -> str | None:
        text = next((line for line in lines if cls._norm(line).startswith("publicada:")), None)
        if not text:
            text = cls._section(lines, "Fecha inicio inscripciones")
        if not text:
            return None
        numeric = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", text)
        if numeric:
            try:
                return datetime.strptime(numeric.group(1), "%d/%m/%Y").isoformat()
            except ValueError:
                return None
        match = re.search(r"\b(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})\b", text, re.I)
        if not match:
            return None
        month = SPANISH_MONTHS.get(cls._norm(match.group(2)))
        if not month:
            return None
        try:
            return datetime(int(match.group(3)), month, int(match.group(1))).isoformat()
        except ValueError:
            return None

    @classmethod
    def _parse_date_value(cls, value: str | None) -> str | None:
        if not value:
            return None
        numeric = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", value)
        if numeric:
            try:
                return datetime.strptime(numeric.group(1), "%d/%m/%Y").isoformat()
            except ValueError:
                return None
        match = re.search(r"\b(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})\b", value, re.I)
        if not match:
            return None
        month = SPANISH_MONTHS.get(cls._norm(match.group(2)))
        if not month:
            return None
        try:
            return datetime(int(match.group(3)), month, int(match.group(1))).isoformat()
        except ValueError:
            return None

    @staticmethod
    def _parse_location(value: str | None) -> tuple[str | None, str | None]:
        if not value:
            return None, "Cantabria"
        parts = [clean_text(part) for part in value.split(",")]
        parts = [part for part in parts if part]
        municipality = parts[0].title() if parts else None
        province = parts[1].title() if len(parts) > 1 else "Cantabria"
        return municipality, province
