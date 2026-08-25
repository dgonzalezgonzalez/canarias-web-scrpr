from __future__ import annotations

from ..jobs.utils import clean_text, infer_province_from_island
from .models import GeographyNormalization


MUNICIPALITY_INDEX = {
    "las palmas de gran canaria": ("Las Palmas de Gran Canaria", "Gran Canaria", "Las Palmas"),
    "las palmas de g.c.": ("Las Palmas de Gran Canaria", "Gran Canaria", "Las Palmas"),
    "santa cruz de tenerife": ("Santa Cruz de Tenerife", "Tenerife", "Santa Cruz de Tenerife"),
    "san cristobal de la laguna": ("San Cristobal de La Laguna", "Tenerife", "Santa Cruz de Tenerife"),
    "san cristóbal de la laguna": ("San Cristobal de La Laguna", "Tenerife", "Santa Cruz de Tenerife"),
    "arrecife": ("Arrecife", "Lanzarote", "Las Palmas"),
    "puerto del rosario": ("Puerto del Rosario", "Fuerteventura", "Las Palmas"),
    "santander": ("Santander", None, "Cantabria"),
    "torrelavega": ("Torrelavega", None, "Cantabria"),
    "camargo": ("Camargo", None, "Cantabria"),
    "maliaño": ("Maliaño", None, "Cantabria"),
    "castro urdiales": ("Castro-Urdiales", None, "Cantabria"),
    "castro-urdiales": ("Castro-Urdiales", None, "Cantabria"),
    "laredo": ("Laredo", None, "Cantabria"),
    "pielagos": ("Piélagos", None, "Cantabria"),
    "piélagos": ("Piélagos", None, "Cantabria"),
    "astillero, el": ("El Astillero", None, "Cantabria"),
    "el astillero": ("El Astillero", None, "Cantabria"),
    "santa cruz de bezana": ("Santa Cruz de Bezana", None, "Cantabria"),
}

ISLAND_ALIASES = {
    "tenerife": "Tenerife",
    "gran canaria": "Gran Canaria",
    "lanzarote": "Lanzarote",
    "fuerteventura": "Fuerteventura",
    "la palma": "La Palma",
    "la gomera": "La Gomera",
    "el hierro": "El Hierro",
}

PROVINCE_ALIASES = {
    "las palmas": "Las Palmas",
    "santa cruz de tenerife": "Santa Cruz de Tenerife",
    "cantabria": "Cantabria",
}


def normalize_geography(
    province: str | None,
    municipality: str | None,
    island: str | None,
    raw_location: str | None,
) -> GeographyNormalization:
    municipality_clean = clean_text(municipality)
    province_clean = clean_text(province)
    island_clean = clean_text(island)
    raw_location_clean = clean_text(raw_location)

    if municipality_clean:
        key = municipality_clean.lower()
        if key in MUNICIPALITY_INDEX:
            canonical_municipality, canonical_island, canonical_province = MUNICIPALITY_INDEX[key]
            return GeographyNormalization(
                province=canonical_province,
                municipality=canonical_municipality,
                island=canonical_island,
                raw_location=raw_location_clean,
                confidence="municipality_index",
            )

    if island_clean:
        island_key = island_clean.lower()
        canonical_island = ISLAND_ALIASES.get(island_key, island_clean)
        canonical_province = infer_province_from_island(canonical_island) or province_clean
        return GeographyNormalization(
            province=canonical_province,
            municipality=municipality_clean,
            island=canonical_island,
            raw_location=raw_location_clean,
            confidence="island",
        )

    if province_clean:
        canonical_province = PROVINCE_ALIASES.get(province_clean.lower(), province_clean)
        return GeographyNormalization(
            province=canonical_province,
            municipality=municipality_clean,
            island=island_clean,
            raw_location=raw_location_clean,
            confidence="province",
        )

    if raw_location_clean and raw_location_clean.lower() in MUNICIPALITY_INDEX:
        canonical_municipality, canonical_island, canonical_province = MUNICIPALITY_INDEX[raw_location_clean.lower()]
        return GeographyNormalization(
            province=canonical_province,
            municipality=canonical_municipality,
            island=canonical_island,
            raw_location=raw_location_clean,
            confidence="raw_location_index",
        )

    return GeographyNormalization(
        province=province_clean,
        municipality=municipality_clean,
        island=island_clean,
        raw_location=raw_location_clean,
        confidence="unresolved" if raw_location_clean else "missing",
    )
