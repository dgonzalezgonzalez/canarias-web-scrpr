from __future__ import annotations

from .spiders import EmcanSpider, JobspySpider, SCESpider, TrabajoCantabriaSpider, TurijobsSpider


SUPPORTED_REGIONS = ("canarias", "cantabria")


def default_spiders(region: str) -> list[object]:
    normalized = region.strip().lower()
    if normalized == "canarias":
        return [SCESpider(), TurijobsSpider(region=normalized), JobspySpider(region=normalized)]
    if normalized == "cantabria":
        return [
            EmcanSpider(),
            TrabajoCantabriaSpider(),
            TurijobsSpider(region=normalized),
            JobspySpider(region=normalized),
        ]
    raise ValueError(f"Unsupported jobs region: {region}")
