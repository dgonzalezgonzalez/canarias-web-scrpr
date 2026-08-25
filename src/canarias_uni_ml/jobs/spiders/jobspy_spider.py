from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..models import JobRecord
from ..utils import clean_text, infer_province_from_island, parse_date
from .base import SpiderError, SpiderResult

if TYPE_CHECKING:
    import pandas as pd


CANARY_ISLANDS_LOCATIONS = [
    "Canary Islands",
    "Islas Canarias",
    "Las Palmas",
    "Santa Cruz de Tenerife",
    "Tenerife",
    "Gran Canaria",
    "Lanzarote",
    "Fuerteventura",
    "La Palma",
    "Gomera",
    "El Hierro",
    "Las Palmas de Gran Canaria",
    "Santa Cruz de Tenerife",
    "San Cristóbal de La Laguna",
]

CANTABRIA_LOCATIONS = [
    "Cantabria, Spain",
    "Santander, Cantabria",
    "Torrelavega, Cantabria",
    "Camargo, Cantabria",
    "Castro-Urdiales, Cantabria",
    "Laredo, Cantabria",
    "Piélagos, Cantabria",
    "El Astillero, Cantabria",
    "Santa Cruz de Bezana, Cantabria",
    "Los Corrales de Buelna, Cantabria",
]

REGION_LOCATIONS = {
    "canarias": CANARY_ISLANDS_LOCATIONS,
    "cantabria": CANTABRIA_LOCATIONS,
}


class JobspySpider:
    source = "jobspy"

    def __init__(self, region: str = "canarias") -> None:
        normalized = region.strip().lower()
        if normalized not in REGION_LOCATIONS:
            raise ValueError(f"Unsupported JobSpy region: {region}")
        self.region = normalized
        self._jobspy = None

    def _get_jobspy(self):
        if self._jobspy is None:
            from jobspy import scrape_jobs
            self._jobspy = scrape_jobs
        return self._jobspy

    def fetch(self, limit: int) -> SpiderResult:
        try:
            import jobspy
        except ImportError:
            raise SpiderError("JobSpy is not installed. Run: pip install jobspy")

        scrape_jobs = self._get_jobspy()
        records: list[JobRecord] = []

        for location in REGION_LOCATIONS[self.region]:
            if len(records) >= limit:
                break

            try:
                jobs = scrape_jobs(
                    site_name=["indeed", "linkedin"],
                    search_term="",
                    location=location,
                    results_wanted=min(limit, 50),
                    country_indeed="spain",
                    is_remote=False,
                    timeout_seconds=30,
                )
            except Exception as exc:
                continue

            if jobs is None or len(jobs) == 0:
                continue

            df = jobs
            for _, row in df.iterrows():
                if len(records) >= limit:
                    break

                record = self._convert_row_to_record(row)
                if record:
                    records.append(record)

        if not records:
            raise SpiderError(f"JobSpy found no jobs in {self.region}")
        return SpiderResult(source=self.source, records=records[:limit])

    def _convert_row_to_record(self, row) -> JobRecord | None:
        title = clean_text(row.get("title"))
        if not title:
            return None

        company = clean_text(row.get("company"))
        description = self._clean_description(row.get("description"))

        salary_text = None
        salary_min = None
        salary_max = None
        salary_currency = None
        salary_period = None

        interval = clean_text(row.get("interval"))
        min_amount = row.get("min_amount")
        max_amount = row.get("max_amount")
        if min_amount or max_amount:
            salary_min = str(int(min_amount)) if min_amount else None
            salary_max = str(int(max_amount)) if max_amount else None
            salary_currency = "EUR"
            salary_period = self._normalize_interval(interval)
            if salary_min and salary_max:
                salary_text = f"{salary_min} - {salary_max} {salary_period or ''}"
            elif salary_min:
                salary_text = f"{salary_min} {salary_period or ''}"

        location = clean_text(row.get("location")) or ""
        province = self._extract_province(location, self.region)
        municipality = self._extract_municipality(location, province)
        island = self._extract_island(location) if self.region == "canarias" else None

        site = clean_text(row.get("site")) or "unknown"

        return JobRecord(
            source=f"{self.source}_{site}",
            external_id=self._generate_external_id(row.get("job_url"), site),
            title=title,
            company=company,
            description=description,
            salary_text=salary_text,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_period=salary_period,
            publication_date=self._parse_job_date(row.get("date_posted")),
            update_date=None,
            province=province,
            municipality=municipality,
            island=island,
            raw_location=location,
            contract_type=self._extract_contract_type(row.get("job_type"), description),
            workday=None,
            schedule=None,
            vacancies=None,
            source_url=clean_text(row.get("job_url")) or "",
            scraped_at=JobRecord.now(),
        )

    METADATA_PATTERNS = [
        r"Información del empleo.*?(?=Descripción del empleo|$)",
        r"ID de Oferta de empleo.*?\n",
        r"Fecha abierta.*?\n",
        r"Sector.*?\n",
        r"Tipo de empleo.*?\n",
        r"Experiencia laboral.*?\n",
        r"Ciudad.*?\n",
        r"Estado/provincia.*?\n",
        r"País.*?\n",
        r"Código postal.*?\n",
        r"-job_details.*?(?=\w)",
        r"Job details.*?(?=Description|$)",
    ]

    @staticmethod
    def _clean_description(description) -> str | None:
        if not description:
            return None
        text = str(description)
        text = re.sub(r"Información del empleo\s*", "", text)
        text = re.sub(r"ID de Oferta de empleo[:\s]+[^\n]*", "", text)
        text = re.sub(r"Fecha abierta[:\s]+[^\n]*", "", text)
        text = re.sub(r"Sector[:\s]+[^\n]*", "", text)
        text = re.sub(r"Tipo de empleo[:\s]+[^\n]*", "", text)
        text = re.sub(r"Experiencia laboral[:\s]+[^\n]*", "", text)
        text = re.sub(r"Ciudad[:\s]+[^\n]*", "", text)
        text = re.sub(r"Estado/provincia[:\s]+[^\n]*", "", text)
        text = re.sub(r"País[:\s]+[^\n]*", "", text)
        text = re.sub(r"Código postal[:\s]+[^\n]*", "", text)
        text = re.sub(r"Descripción del empleo[:\s*]+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"Job Description[:\s*]+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"Job details[:\s*]+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\*+", "", text)
        text = re.sub(r"\s+", " ", text)
        text = text.strip()
        if not text:
            return None
        if len(text) > 10000:
            text = text[:10000] + "..."
        return text

    @staticmethod
    def _normalize_interval(interval: str | None) -> str | None:
        if not interval:
            return None
        interval_lower = interval.lower()
        if "hour" in interval_lower:
            return "hour"
        if "month" in interval_lower:
            return "month"
        if "year" in interval_lower:
            return "year"
        if "week" in interval_lower:
            return "week"
        if "day" in interval_lower:
            return "day"
        return interval

    @staticmethod
    def _extract_province(location: str, region: str = "canarias") -> str | None:
        location_lower = location.lower()
        if region == "cantabria":
            return "Cantabria" if location_lower else None
        if "santa cruz" in location_lower or "tenerife" in location_lower:
            return "Santa Cruz de Tenerife"
        if "las palmas" in location_lower or "gran canaria" in location_lower or "lanzarote" in location_lower or "fuerteventura" in location_lower:
            return "Las Palmas"
        if "canarias" in location_lower or "canary" in location_lower:
            return "Canarias"
        return None

    @staticmethod
    def _extract_municipality(location: str, province: str | None) -> str | None:
        if not location:
            return None
        location_clean = clean_text(location)
        if not location_clean:
            return None
        parts = location_clean.split(",")
        if len(parts) > 1:
            return clean_text(parts[0])
        return location_clean

    @staticmethod
    def _extract_island(location: str) -> str | None:
        location_lower = location.lower()
        islands = {
            "tenerife": "Tenerife",
            "gran canaria": "Gran Canaria",
            "lanzarote": "Lanzarote",
            "fuerteventura": "Fuerteventura",
            "la palma": "La Palma",
            "gomera": "La Gomera",
            "el hierro": "El Hierro",
        }
        for key, island in islands.items():
            if key in location_lower:
                return island
        return None

    @staticmethod
    def _generate_external_id(job_url: str | None, site: str) -> str:
        if job_url:
            match = re.search(r"/job/(?:[^/]+/)?([a-zA-Z0-9]+)", job_url)
            if match:
                return f"{site}_{match.group(1)}"
        from datetime import datetime
        return f"{site}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    @staticmethod
    def _parse_job_date(date_value) -> str | None:
        if not date_value:
            return None
        return parse_date(str(date_value))

    @staticmethod
    def _extract_contract_type(job_type: str | None, description: str | None) -> str | None:
        if job_type:
            return clean_text(job_type)
        if description:
            desc_lower = description.lower()
            if "indefinido" in desc_lower or "contrato indefinido" in desc_lower:
                return "Contrato Indefinido"
            if "temporal" in desc_lower or "duración determinada" in desc_lower:
                return "Contrato Temporal"
            if "prácticas" in desc_lower:
                return "Prácticas"
            if "becario" in desc_lower:
                return "Beca"
        return None
