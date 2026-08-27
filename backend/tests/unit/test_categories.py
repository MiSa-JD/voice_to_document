from __future__ import annotations

import pytest
from app.categories import category_definitions, category_slug, parse_categories


def test_category_definitions_separate_display_name_and_slug() -> None:
    definitions = category_definitions(parse_categories("일상 대화,Team Notes"))

    assert [(item.display_name, item.slug) for item in definitions] == [
        ("일상 대화", "일상-대화"),
        ("Team Notes", "team-notes"),
    ]


@pytest.mark.parametrize("value", ["../회의", "a/b", "a\\b", "   "])
def test_category_slug_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        category_slug(value)
