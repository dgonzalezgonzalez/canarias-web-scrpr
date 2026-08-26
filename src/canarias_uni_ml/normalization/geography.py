from __future__ import annotations

import re
import unicodedata

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


def geography_key(value: str | None) -> str:
    """Accent/punctuation-insensitive key for municipality and province matching."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


# Complete Cantabrian municipality gazetteer used as a positive region gate for
# third-party sources. Values are the canonical display names used in exports.
_CANTABRIA_MUNICIPALITY_NAMES = (
    "Alfoz de Lloredo", "Ampuero", "Anievas", "Arenas de Iguña", "Argoños", "Arnuero",
    "Arredondo", "El Astillero", "Bárcena de Cicero", "Bárcena de Pie de Concha", "Bareyo",
    "Cabezón de la Sal", "Cabezón de Liébana", "Cabuérniga", "Camaleño", "Camargo",
    "Campoo de Enmedio", "Campoo de Yuso", "Cartes", "Castañeda", "Castro-Urdiales", "Cieza",
    "Cillorigo de Liébana", "Colindres", "Comillas", "Los Corrales de Buelna", "Corvera de Toranzo",
    "Entrambasaguas", "Escalante", "Guriezo", "Hazas de Cesto", "Hermandad de Campoo de Suso",
    "Herrerías", "Lamasón", "Laredo", "Liendo", "Liérganes", "Limpias", "Luena", "Marina de Cudeyo",
    "Mazcuerras", "Medio Cudeyo", "Meruelo", "Miengo", "Miera", "Molledo", "Noja", "Penagos",
    "Peñarrubia", "Pesaguero", "Pesquera", "Piélagos", "Polaciones", "Polanco", "Potes",
    "Puente Viesgo", "Ramales de la Victoria", "Rasines", "Reinosa", "Reocín", "Ribamontán al Mar",
    "Ribamontán al Monte", "Rionansa", "Riotuerto", "Las Rozas de Valdearroyo", "Ruente", "Ruesga",
    "Ruiloba", "San Felices de Buelna", "San Miguel de Aguayo", "San Pedro del Romeral",
    "San Roque de Riomiera", "Santa Cruz de Bezana", "Santa María de Cayón", "Santander",
    "Santillana del Mar", "Santiurde de Reinosa", "Santiurde de Toranzo", "San Vicente de la Barquera", "Santoña", "Saro", "Selaya",
    "Soba", "Solórzano", "Suances", "Los Tojos", "Tresviso", "Tudanca", "Udías", "Val de San Vicente",
    "Valdáliga", "Valdeolea", "Valdeprado del Río", "Valderredible", "Valle de Villaverde",
    "Vega de Liébana", "Vega de Pas", "Villacarriedo", "Villaescusa", "Villafufre", "Voto",
    "Torrelavega",
)

CANTABRIA_MUNICIPALITIES = {
    geography_key(name): name for name in _CANTABRIA_MUNICIPALITY_NAMES
}
for _alias, _canonical in {
    "Astillero": "El Astillero",
    "Corrales de Buelna": "Los Corrales de Buelna",
    "Tojos": "Los Tojos",
    "Rozas de Valdearroyo": "Las Rozas de Valdearroyo",
    # Maliaño is a major locality in the municipality of Camargo, and appears
    # as a location label in third-party job feeds even though it is not a
    # standalone municipality.
    "Maliaño": "Maliaño",
}.items():
    CANTABRIA_MUNICIPALITIES[geography_key(_alias)] = _canonical

MUNICIPALITY_LOOKUP = {
    geography_key(key): value for key, value in MUNICIPALITY_INDEX.items()
}
for _key, _name in CANTABRIA_MUNICIPALITIES.items():
    MUNICIPALITY_LOOKUP.setdefault(_key, (_name, None, "Cantabria"))


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
        key = geography_key(municipality_clean)
        if key in MUNICIPALITY_LOOKUP:
            canonical_municipality, canonical_island, canonical_province = MUNICIPALITY_LOOKUP[key]
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
        canonical_province = PROVINCE_ALIASES.get(geography_key(province_clean), province_clean)
        return GeographyNormalization(
            province=canonical_province,
            municipality=municipality_clean,
            island=island_clean,
            raw_location=raw_location_clean,
            confidence="province",
        )

    raw_key = geography_key(raw_location_clean.split(",", 1)[0] if raw_location_clean else None)
    if raw_key in MUNICIPALITY_LOOKUP:
        canonical_municipality, canonical_island, canonical_province = MUNICIPALITY_LOOKUP[raw_key]
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
