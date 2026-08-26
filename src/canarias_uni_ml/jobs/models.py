from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class JobRecord:
    source: str
    external_id: str
    title: str
    company: str | None
    description: str | None
    salary_text: str | None
    salary_min: str | None
    salary_max: str | None
    salary_currency: str | None
    salary_period: str | None
    publication_date: str | None
    update_date: str | None
    closing_date: str | None = None
    is_active: bool = True
    province: str | None = None
    province_raw: str | None = None
    municipality: str | None = None
    municipality_raw: str | None = None
    island: str | None = None
    island_raw: str | None = None
    raw_location: str | None = None
    contract_type: str | None = None
    contract_type_raw: str | None = None
    workday: str | None = None
    schedule: str | None = None
    vacancies: str | None = None
    target_degree_branches: str | None = None
    target_degree_titles: str | None = None
    degree_match_status: str | None = None
    source_url: str = ""
    scraped_at: str = ""

    @classmethod
    def now(cls) -> str:
        return datetime.now(timezone.utc).isoformat()

    def to_row(self) -> dict[str, Any]:
        return asdict(self)
