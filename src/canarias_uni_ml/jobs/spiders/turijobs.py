from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

from ..models import JobRecord
from ..utils import clean_text, parse_date
from .base import SpiderError, SpiderResult

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


TURIJOBS_BASE = "https://www.turijobs.com"
TURIJOBS_SITEMAP_URL = "https://www.turijobs.com/es-es/sitemap/active-offers.xml"
TURIJOBS_LOCATION_MARKERS = {
    "canarias": ("islas-canarias", "las-palmas", "santa-cruz-de-tenerife"),
    "cantabria": ("cantabria", "santander", "torrelavega"),
}
CANTABRIA_CITIES = {
    "santander",
    "torrelavega",
    "camargo",
    "castro-urdiales",
    "laredo",
    "pielagos",
    "el astillero",
    "santa cruz de bezana",
    "los corrales de buelna",
}


class TurijobsSpider:
    source = "turijobs"

    def __init__(self, region: str = "canarias") -> None:
        normalized = region.strip().lower()
        if normalized not in TURIJOBS_LOCATION_MARKERS:
            raise ValueError(f"Unsupported Turijobs region: {region}")
        self.region = normalized
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    def fetch(self, limit: int) -> SpiderResult:
        if sync_playwright is None:
            raise SpiderError("Turijobs scraper requires playwright to be installed")
        detail_urls = self._fetch_candidate_urls(limit * 3)
        if not detail_urls:
            raise SpiderError(f"Turijobs sitemap returned no {self.region} offers")

        records: list[JobRecord] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            for url in detail_urls:
                try:
                    record = self._fetch_detail_record(page, url)
                except Exception:
                    continue
                if record:
                    records.append(record)
                if len(records) >= limit:
                    break
            browser.close()

        if not records:
            raise SpiderError("Turijobs detail pages could not be scraped")
        return SpiderResult(source=self.source, records=records[:limit])

    def _fetch_candidate_urls(self, cap: int) -> list[str]:
        response = self.session.get(TURIJOBS_SITEMAP_URL, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls: list[str] = []
        for loc in root.findall(".//sm:loc", namespace):
            url = clean_text(loc.text)
            if not url:
                continue
            if "/es-es/oferta-trabajo/" not in url:
                continue
            if not any(marker in url.lower() for marker in TURIJOBS_LOCATION_MARKERS[self.region]):
                continue
            urls.append(url)
            if len(urls) >= cap:
                break
        return urls

    def _fetch_detail_record(self, page, url: str) -> JobRecord | None:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        html = page.content()
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html,
            re.S,
        )
        if not match:
            return None
        data = json.loads(match.group(1))
        detail = data["props"]["pageProps"].get("offerData", {}).get("offerDetail", {})
        if not detail:
            return None
        salary = detail.get("salary") or {}
        company = detail.get("company") or {}
        location = detail.get("location") or {}
        features = detail.get("features") or {}
        salary_min = self._stringify_number(salary.get("salaryMin"))
        salary_max = self._stringify_number(salary.get("salaryMax"))
        salary_text = None
        if salary.get("salaryVisible"):
            parts = [part for part in [salary_min, salary_max] if part]
            if parts:
                salary_text = " - ".join(parts)
                if salary.get("salaryType"):
                    salary_text = f"{salary_text} {salary.get('salaryType')}"

        province = clean_text(location.get("regionName"))
        municipality = clean_text(location.get("cityName"))
        if self.region == "cantabria" and not self._is_cantabria_location(province, municipality):
            return None
        return JobRecord(
            source=self.source,
            external_id=str(detail.get("id")),
            title=clean_text(detail.get("title")) or "Oferta Turijobs",
            company=clean_text(company.get("enterpriseName")),
            description=self._html_to_text(detail.get("description")),
            salary_text=salary_text,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="EUR" if salary_text else None,
            salary_period=clean_text(salary.get("salaryType")),
            publication_date=parse_date(
                detail.get("dates", {}).get("publicationDate") or detail.get("publicationDate")
            ),
            update_date=None,
            province=province,
            municipality=municipality,
            island=(
                "Islas Canarias"
                if self.region == "canarias" and "canarias" in (url.lower() + (province or "").lower())
                else None
            ),
            raw_location=clean_text(" / ".join(filter(None, [municipality, province]))),
            contract_type=clean_text((features.get("3") or {}).get("label")),
            workday=clean_text((features.get("4") or {}).get("label")),
            schedule=None,
            vacancies=None,
            source_url=url,
            scraped_at=JobRecord.now(),
        )

    @staticmethod
    def _stringify_number(value: object) -> str | None:
        if value is None:
            return None
        cleaned = clean_text(value)
        if cleaned in {None, "0", "0.0"}:
            return None
        return cleaned

    @staticmethod
    def _html_to_text(value: object) -> str | None:
        cleaned = clean_text(value)
        if not cleaned:
            return None
        return clean_text(BeautifulSoup(cleaned, "html.parser").get_text(" ", strip=True))

    @staticmethod
    def _fold(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold())
        return "".join(char for char in normalized if not unicodedata.combining(char)).strip()

    @classmethod
    def _is_cantabria_location(cls, province: str | None, municipality: str | None) -> bool:
        if province:
            return cls._fold(province) == "cantabria"
        return cls._fold(municipality or "") in CANTABRIA_CITIES
