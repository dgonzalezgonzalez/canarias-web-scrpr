from __future__ import annotations

import re
from collections import deque
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from ..models import JobRecord
from ..utils import clean_text, parse_date
from .base import SpiderError, SpiderResult


SNE_BASE_URL = "https://www.sistemanacionalempleo.es/OfertaDifusionWEB/"
SNE_CANTABRIA_SEARCH_URL = urljoin(
    SNE_BASE_URL,
    "busquedaOfertas.do?botonNavegacion=Enviar&modo=continuar&provincia=39",
)


class EmcanSpider:
    """Current Cantabria offers published by EMCAN through the national SNE portal."""

    source = "emcan"

    def __init__(self, search_url: str = SNE_CANTABRIA_SEARCH_URL) -> None:
        self.search_url = search_url
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
        detail_urls = self._fetch_detail_urls(limit)
        if not detail_urls:
            raise SpiderError("EMCAN/SNE returned no Cantabria offer links")

        records: list[JobRecord] = []
        failures: list[str] = []
        for detail_url in detail_urls:
            if len(records) >= limit:
                break
            try:
                response = self.session.get(detail_url, timeout=30)
                response.raise_for_status()
                record = self._parse_detail(response.text, response.url)
            except (requests.RequestException, ValueError) as exc:
                failures.append(str(exc))
                continue
            if record is not None:
                records.append(record)
            else:
                failures.append(f"unparseable detail: {detail_url}")

        if not records:
            suffix = f"; first error: {failures[0]}" if failures else ""
            raise SpiderError(f"EMCAN/SNE detail pages could not be parsed{suffix}")
        records.sort(key=lambda item: item.publication_date or "", reverse=True)
        return SpiderResult(
            source=self.source,
            records=records[:limit],
            complete=len(detail_urls) < limit and not failures,
        )

    def _fetch_detail_urls(self, limit: int) -> list[str]:
        pending = deque([self.search_url])
        visited_pages: set[str] = set()
        detail_urls: list[str] = []
        seen_details: set[str] = set()

        # SNE normally exposes roughly ten offers per page. Keep crawl bounded.
        while pending and len(visited_pages) < 25 and len(detail_urls) < limit:
            page_url = pending.popleft()
            if page_url in visited_pages:
                continue
            visited_pages.add(page_url)
            response = self.session.get(page_url, timeout=30)
            response.raise_for_status()
            if self._is_session_cancelled(response.text):
                raise SpiderError(
                    "EMCAN/SNE cancelled the search session; retry the crawl with a fresh session"
                )
            details, pages = self._parse_listing_links(response.text, response.url)
            for detail_url in details:
                stable_key = self._offer_id_from_url(detail_url) or detail_url
                if stable_key in seen_details:
                    continue
                seen_details.add(stable_key)
                detail_urls.append(detail_url)
                if len(detail_urls) >= limit:
                    break
            for next_url in pages:
                if next_url not in visited_pages:
                    pending.append(next_url)
        return detail_urls

    @classmethod
    def _parse_listing_links(cls, html: str, base_url: str) -> tuple[list[str], list[str]]:
        soup = BeautifulSoup(html, "html.parser")
        detail_urls: list[str] = []
        page_urls: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = clean_text(anchor.get("href"))
            if not href:
                continue
            absolute = urljoin(base_url, href)
            if "detalleOferta.do" in absolute:
                offer_id = cls._offer_id_from_url(absolute)
                if offer_id and offer_id.startswith("06"):
                    detail_urls.append(absolute)
                continue
            anchor_text = clean_text(anchor.get_text(" ", strip=True)) or ""
            if not cls._is_pagination_link(absolute, anchor_text=anchor_text):
                continue
            page_urls.append(absolute)
        return list(dict.fromkeys(detail_urls)), list(dict.fromkeys(page_urls))

    @staticmethod
    def _is_pagination_link(url: str, *, anchor_text: str = "") -> bool:
        """Recognize both legacy and current SNE result-page URLs.

        Current SNE pages use ``listadoOfertas.do?idFlujo=...&indice=41&modo=pagina``;
        older fixtures and deployments used ``busquedaOfertas.do?...pagina=2``.
        Keep the full query string, including the transient ``idFlujo`` token, for
        requests made during one crawl.
        """
        parsed = urlsplit(url)
        path = parsed.path.lower()
        query = parse_qs(parsed.query)
        lowered = url.lower()
        text = (anchor_text or "").strip().lower()
        if path.endswith("listadoofertas.do"):
            return query.get("modo", [""])[0].lower() == "pagina" and bool(query.get("indice"))
        if path.endswith("busquedaofertas.do"):
            return (
                "pagina" in lowered
                or "navegacion" in lowered
                or text.isdigit()
                or text in {"siguiente", ">", ">>"}
            )
        return False

    @staticmethod
    def _is_session_cancelled(html: str) -> bool:
        lowered = clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
        if not lowered:
            return False
        lowered = lowered.casefold()
        return "sesión cancelada" in lowered or "sesion cancelada" in lowered or "session cancelled" in lowered

    @classmethod
    def _parse_detail(cls, html: str, source_url: str) -> JobRecord | None:
        soup = BeautifulSoup(html, "html.parser")
        lines = cls._text_lines(soup)
        full_text = "\n".join(lines)
        external_id = cls._offer_id_from_url(source_url)
        if not external_id:
            match = re.search(r"Datos de la oferta n(?:u|\u00fa)mero:\s*(06\d+)", full_text, re.I)
            external_id = match.group(1) if match else None
        if not external_id or not external_id.startswith("06"):
            return None

        title = cls._section(lines, "Descripción", {"Datos"})
        description = cls._section(
            lines,
            "Datos adicionales",
            {"Datos de contacto", "Requerimientos", "Requeridos/Deseables", "Nivel Profesional buscado"},
        )
        requirements = cls._section(
            lines,
            "Requerimientos",
            {
                "Datos de contacto",
                "Datos adicionales",
                "Descripción",
                "Datos",
                "Nivel Profesional buscado",
                "Permisos de conducir",
            },
        )
        if requirements:
            safe_lines = [
                line
                for line in requirements.splitlines()
                if not re.search(r"(?:tel[eé]fono|correo|email|@|www\.|http)", line, re.I)
            ]
            if safe_lines:
                description = "\n".join(filter(None, [description, "Requerimientos:", *safe_lines]))
        if not title:
            return None

        municipality = None
        location_match = re.search(
            r"Localidad de Ubicaci(?:o|\u00f3)n del Puesto:\s*(.*?)\s*\(\s*CANTABRIA\s*\)",
            full_text,
            re.I,
        )
        if location_match:
            municipality = clean_text(location_match.group(1))

        publication_date = cls._label_value(lines, "Fecha de inicio")
        closing_date = cls._label_value(lines, "Fecha de fin")
        salary_text = cls._sentence_value(description, r"\bsalario\s*[:\-]?\s*([^\n.]+)")
        contract_type = cls._sentence_value(
            description,
            r"\bcontrato(?:\s+laboral)?\s+((?:fijo discontinuo|indefinido|temporal|formativo|de duraci[oó]n determinada)[^\n.,;]*)",
        )
        workday = cls._sentence_value(
            description,
            r"\bjornada\s+((?:completa|parcial|continua|intensiva)[^\n.,;]*)",
        )
        vacancies_match = re.match(r"\s*(\d+)\b", title)

        return JobRecord(
            source=cls.source,
            external_id=external_id,
            title=title,
            company=None,
            description=description or title,
            salary_text=salary_text,
            salary_min=None,
            salary_max=None,
            salary_currency="EUR" if salary_text else None,
            salary_period=None,
            publication_date=parse_date(publication_date),
            # SNE's "Fecha de fin" is the application/diffusion deadline, not a
            # last-modified timestamp. Keep it separate from the closing date.
            update_date=None,
            closing_date=parse_date(closing_date),
            province="Cantabria",
            municipality=municipality,
            island=None,
            raw_location=clean_text(" / ".join(filter(None, [municipality, "Cantabria"]))),
            contract_type=contract_type,
            workday=workday,
            schedule=None,
            vacancies=vacancies_match.group(1) if vacancies_match else None,
            source_url=cls._stable_detail_url(external_id),
            scraped_at=JobRecord.now(),
        )

    @staticmethod
    def _text_lines(soup: BeautifulSoup) -> list[str]:
        return [line for raw in soup.get_text("\n", strip=True).splitlines() if (line := clean_text(raw))]

    @staticmethod
    def _section(lines: list[str], label: str, end_labels: set[str]) -> str | None:
        normalized_label = label.casefold()
        start = next((i for i, line in enumerate(lines) if line.casefold() == normalized_label), None)
        if start is None:
            return None
        values: list[str] = []
        end_normalized = {item.casefold() for item in end_labels}
        for line in lines[start + 1 :]:
            if line.casefold() in end_normalized:
                break
            values.append(line)
        return clean_text("\n".join(values))

    @staticmethod
    def _label_value(lines: list[str], label: str) -> str | None:
        pattern = re.compile(rf"^{re.escape(label)}\s*:\s*(.+)$", re.I)
        for line in lines:
            match = pattern.match(line)
            if match:
                return clean_text(match.group(1))
        return None

    @staticmethod
    def _sentence_value(text: str | None, pattern: str) -> str | None:
        if not text:
            return None
        match = re.search(pattern, text, re.I)
        return clean_text(match.group(1)) if match else None

    @staticmethod
    def _offer_id_from_url(url: str) -> str | None:
        values = parse_qs(urlsplit(url).query).get("id", [])
        return clean_text(values[0]) if values else None

    @staticmethod
    def _stable_detail_url(external_id: str) -> str:
        query = urlencode({"id": external_id, "modo": "inicio", "ret": "B"})
        return urlunsplit(("https", "www.sistemanacionalempleo.es", "/OfertaDifusionWEB/detalleOferta.do", query, ""))
