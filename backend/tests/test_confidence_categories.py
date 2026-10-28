"""
The capability radar used four axes built from the founder's career
(Technical / Product Leadership / Data Analysis / Customer Success), and every
unrecognised "experience" entity fell into Product Leadership, every "domain"
into Customer Success. A senior software engineer saw Product Leadership and
Customer Success on her radar. Categories are now profession-neutral, matched
on word boundaries, and only the ones a user has are shown.
"""
from __future__ import annotations

import pytest

from backend.services import confidence_matrix_service as cm


@pytest.mark.parametrize("name,etype,expected", [
    ("Java", "skill", "Technical"),
    ("Go", "skill", "Technical"),                       # not "go_to_market"
    ("Go to Market", "skill", "Product"),
    ("Development Team Lead at Ofek unit, IAF", "experience", "Leadership"),
    ("Business Intelligence", "domain", "Data"),
    ("Software Development", "domain", "Technical"),
    ("Customer Success", "skill", "Business"),
    ("Pension Migrations", "domain", "Domain"),
    ("ניהול צוות", "skill", "Leadership"),
])
def test_classification(name, etype, expected):
    assert cm._resolve_category("", etype, name) == expected


def _row(name, etype):
    return ("id-" + name, name, etype, name.lower(), 20.0, 20.0, 0.0, None, "UNVERIFIED")


def test_engineer_radar_has_no_product_or_customer_axis():
    rows = [
        _row("Java", "skill"), _row("Node.js", "skill"), _row("Docker", "skill"),
        _row("SQL", "skill"), _row("ETL", "skill"),
        _row("Development Team Lead at Ofek unit, IAF", "experience"),
    ]
    cats = {d["category"] for d in cm.compute_radar(rows, {}, "u")}
    assert cats == {"Technical", "Data", "Leadership"}


def test_narrow_profile_is_padded_to_three_axes():
    radar = cm.compute_radar([_row("Java", "skill")], {}, "u")
    assert len(radar) == 3
    assert next(d for d in radar if d["category"] == "Technical")["count"] == 1
