from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryDefinition:
    display_name: str
    slug: str


def parse_categories(value: str, *, setting_name: str = "CATEGORIES") -> tuple[str, ...]:
    parts = value.split(",")
    values = tuple(part.strip() for part in parts)
    if not values or any(not item for item in values):
        raise ValueError(f"{setting_name} must not contain empty values")
    duplicates = sorted({item for item in values if values.count(item) > 1})
    if duplicates:
        raise ValueError(f"{setting_name} must not contain duplicates: {', '.join(duplicates)}")
    return values


def category_slug(display_name: str) -> str:
    value = unicodedata.normalize("NFKC", display_name).strip().casefold()
    if (
        not value
        or any(character in value for character in ("/", "\\", "\0"))
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise ValueError("category cannot be used as a path")
    slug = re.sub(r"[^\w]+", "-", value, flags=re.UNICODE).strip("-_")
    if not slug or slug in {".", ".."}:
        raise ValueError("category slug is empty or unsafe")
    return slug


def category_definitions(values: tuple[str, ...]) -> tuple[CategoryDefinition, ...]:
    definitions = tuple(CategoryDefinition(value, category_slug(value)) for value in values)
    slugs = tuple(item.slug for item in definitions)
    collisions = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    if collisions:
        raise ValueError("CATEGORIES contains colliding slugs: " + ", ".join(collisions))
    return definitions
