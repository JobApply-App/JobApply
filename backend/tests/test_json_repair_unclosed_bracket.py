"""
The CV writer (gemini-flash-latest) left a bracket open where
`military_service` ends: 14 "TailorAgent JSON unrecoverable" failures across
the stage 7 benchmark runs of 2026-11-17 to 2026-11-20, every one
"Expecting ',' delimiter" at column 5, 74-78% of the way into the output,
which is where that block closes. The user got no CV.

The fixture is the military block of a captured writer output (an invented
benchmark person, p05) with one closing line removed, the two ways the log
signature allows.
"""
import json

import pytest

from backend.utilities.json_repair import parse_json_robust

GOOD = """{
  "type": "cv",
  "cv_data": {
    "education": [
      {
        "degree": "B.A. Communication and Management",
        "institution": "The College of Management",
        "dates": "2016 - 2019"
      }
    ],
    "military_service": {
      "role_title": "Help Desk Team Lead (Signals NCO)",
      "unit_type": "IDF, C4I Corps",
      "dates": "2013 - 2016",
      "key_responsibilities": [
        "Operated the central communications help desk servicing 800 base personnel.",
        "Trained 12 soldiers on technical ticketing workflows and service escalation procedures."
      ]
    },
    "skills": {
      "categories": [
        {
          "label": "Customer Success & Operations",
          "items": ["Onboarding", "QBRs"]
        }
      ]
    },
    "volunteering": ""
  }
}"""


def _without_line(text: str, line: str) -> str:
    lines = text.split("\n")
    lines.remove(line)
    return "\n".join(lines)


@pytest.mark.parametrize("dropped", ["      ]", "    },"])
def test_bracket_left_open_at_the_end_of_military_service_is_closed(dropped):
    raw = _without_line(GOOD, dropped)
    with pytest.raises(json.JSONDecodeError) as exc:
        json.loads(raw)
    assert exc.value.msg == "Expecting ',' delimiter" and exc.value.colno == 5, \
        "the fixture must reproduce the logged failure"

    assert parse_json_robust(raw, context="test") == json.loads(GOOD)


def test_a_well_formed_cv_is_untouched():
    assert parse_json_robust(GOOD) == json.loads(GOOD)


def test_a_missing_comma_mid_line_is_not_guessed():
    assert parse_json_robust('{"a": ["x" "y"], "b": 1}') is None
