from __future__ import annotations

import re
import hashlib
import unicodedata
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from ..models import JobRecord
from ..utils import clean_text, infer_province_from_island, parse_date
from ...normalization.geography import CANTABRIA_MUNICIPALITIES as SHARED_CANTABRIA_MUNICIPALITIES, geography_key
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

# Complete enough municipality coverage for validating third-party results. The
# search locations above are deliberately smaller; this set is used only as a
# positive geography gate after JobSpy returns a row.
CANTABRIA_MUNICIPALITIES = {
    "alfoz de lloredo", "ampuero", "anievas", "arenas de iguna", "argonos", "arnuero",
    "arredondo", "astillero", "barcena de cicero", "barcena de pie de concha", "bareyo",
    "cabezon de la sal", "cabezon de liebana", "cabuerniga", "camaleno", "camargo",
    "campoo de enmedio", "campoo de yuso", "cartes", "castaneda", "castro-urdiales",
    "castro urdiales", "cieza", "cillorigo de liebana", "colindres", "comillas",
    "corrales de buelna, los", "los corrales de buelna", "corvera de toranzo",
    "entrambasaguas", "escalante", "guriezo", "hazas de cesto",
    "hermandad de campoo de suso", "herrerias", "laredo", "liendo", "lierganes", "limpias",
    "luena", "marina de cudeyo", "mazcuerras", "medio cudeyo", "meruelo", "miengo", "miera",
    "molledo", "noja", "penagos", "penarrubia", "pesaguero", "pesquera", "pielagos", "polaciones",
    "polanco", "potes", "puente viesgo", "ramales de la victoria", "rasines", "reinosa", "reocin",
    "ribamontan al mar", "ribamontan al monte", "rionansa", "riotuerto", "rozas de valdearroyo, las",
    "ruente", "ruesga", "ruiloba", "san felices de buelna", "san miguel de aguayo", "san pedro del romeral",
    "san roque de riomiera", "santa cruz de bezana", "santa maria de cayon", "santander",
    "santillana del mar", "santiurde de reinosa", "santiurde de toranzo", "santona", "saro", "selaya",
    "soba", "solorzano", "suances", "tojos, los", "tresviso", "tudanca", "udias", "val de san vicente",
    "valdaliga", "valdeolea", "valdeprado del rio", "valderredible", "valle de villaverde",
    "vega de liebana", "vega de pas", "voto", "villacarriedo", "villafufre", "torrelavega",
    "camargo", "el astillero", "santa cruz de bezana", "laredo",
}

OUT_OF_REGION_MARKERS = {
    "asturias", "bizkaia", "vizcaya", "bilbao", "burgos", "palencia", "alava", "araba",
    "guipuzcoa", "gipuzkoa", "leon", "madrid", "barcelona", "navarra", "salamanca",
}

# Use the shared gazetteer as the authoritative validation set. The local
# legacy aliases above remain harmless for backwards imports, but all matching
# below uses normalized shared keys.
CANTABRIA_MUNICIPALITIES = set(SHARED_CANTABRIA_MUNICIPALITIES)

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
            raise SpiderError("JobSpy is not installed. Run: pip install python-jobspy")

        scrape_jobs = self._get_jobspy()
        records: list[JobRecord] = []
        seen_keys: set[str] = set()

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
                    key = f"{record.source}|{record.external_id}"
                    source_url = (clean_text(record.source_url) or "").casefold()
                    if key in seen_keys or (source_url and source_url in seen_keys):
                        continue
                    seen_keys.add(key)
                    if source_url:
                        seen_keys.add(source_url)
                    records.append(record)

        if not records:
            raise SpiderError(f"JobSpy found no jobs in {self.region}")
        # JobSpy queries are provider-capped/best-effort; never deactivate
        # previously seen provider rows from a partial third-party result.
        return SpiderResult(source=self.source, records=records[:limit], complete=False)

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
        min_amount = self._numeric_amount(row.get("min_amount"))
        max_amount = self._numeric_amount(row.get("max_amount"))
        if min_amount is not None or max_amount is not None:
            salary_min = str(int(min_amount)) if min_amount is not None else None
            salary_max = str(int(max_amount)) if max_amount is not None else None
            salary_currency = "EUR"
            salary_period = self._normalize_interval(interval)
            if salary_min and salary_max:
                salary_text = f"{salary_min} - {salary_max} {salary_period or ''}"
            elif salary_min:
                salary_text = f"{salary_min} {salary_period or ''}"

        location = clean_text(row.get("location")) or ""
        province = self._extract_province(location, self.region)
        municipality = self._extract_municipality(location, province)
        if self.region == "cantabria" and province != "Cantabria":
            return None
        island = self._extract_island(location) if self.region == "canarias" else None

        site = clean_text(row.get("site")) or "unknown"
        publication_date = self._parse_job_date(row.get("date_posted"))
        job_url = clean_text(row.get("job_url"))

        return JobRecord(
            source=f"{self.source}_{site}",
            external_id=self._generate_external_id(
                job_url,
                site,
                title=title,
                company=company,
                location=location,
                publication_date=publication_date,
            ),
            title=title,
            company=company,
            description=description,
            salary_text=salary_text,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_period=salary_period,
            publication_date=publication_date,
            update_date=None,
            province=province,
            municipality=municipality,
            island=island,
            raw_location=location,
            contract_type=self._extract_contract_type(row.get("job_type"), description),
            workday=None,
            schedule=None,
            vacancies=None,
            source_url=job_url or "",
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
    def _numeric_amount(value) -> float | None:
        cleaned = clean_text(value)
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_province(location: str, region: str = "canarias") -> str | None:
        location_lower = location.lower()
        if region == "cantabria":
            if not location_lower:
                return None
            folded = JobspySpider._fold(location_lower)
            if "cantabria" in folded:
                return "Cantabria"
            first = geography_key(location.split(",", 1)[0])
            if first in CANTABRIA_MUNICIPALITIES:
                return "Cantabria"
            if any(marker in folded for marker in OUT_OF_REGION_MARKERS):
                return None
            return None
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
            candidate = clean_text(parts[0])
            return None if geography_key(candidate) in {"cantabria", "cantabria spain"} else candidate
        if geography_key(location_clean) in {"cantabria", "cantabria spain"}:
            return None
        if province == "Cantabria" and geography_key(location_clean) in CANTABRIA_MUNICIPALITIES:
            return SHARED_CANTABRIA_MUNICIPALITIES[geography_key(location_clean)]
        if province == "Cantabria":
            return location_clean
        return None

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
    def _generate_external_id(
        job_url: str | None,
        site: str,
        *,
        title: str | None = None,
        company: str | None = None,
        location: str | None = None,
        publication_date: str | None = None,
    ) -> str:
        site_key = clean_text(site) or "unknown"
        if job_url:
            parsed = urlsplit(job_url)
            query = parse_qs(parsed.query)
            for key in ("jk", "job_id", "jobid"):
                value = clean_text((query.get(key) or [None])[0])
                if value:
                    return f"{site_key}_{value}"
            match = re.search(r"/jobs/view/(\d+)", parsed.path, re.I)
            if match:
                return f"{site_key}_{match.group(1)}"
            match = re.search(r"/job/(?:[^/]+/)?([a-zA-Z0-9_-]+)", parsed.path, re.I)
            if match:
                return f"{site_key}_{match.group(1)}"
            canonical_query = urlencode(sorted((key, value) for key, values in query.items() if key.lower() not in {"utm_source", "utm_medium", "utm_campaign"} for value in values))
            canonical = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), canonical_query, ""))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
            return f"{site_key}_url_{digest}"

        fingerprint = "|".join(
            JobspySpider._fold(value or "")
            for value in (site_key, title, company, location, publication_date)
        )
        digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20]
        return f"{site_key}_fp_{digest}"

    @staticmethod
    def _fold(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        return re.sub(r"\s+", " ", "".join(ch for ch in normalized if not unicodedata.combining(ch))).strip().lower()

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
