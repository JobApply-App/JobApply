"""The proximity factor: where it applies, its size, and Principle 4."""
import pytest

from backend.services.israel_cities import (
    CITIES, CITY_BY_NAME, proximity_delta, resolve_city,
)
from backend.services.match_score_service import compute_match_score_async, finalize_composite


@pytest.mark.parametrize("location,expected", [
    ("Ramat Gan, Tel Aviv District, Israel", "Ramat Gan"),
    ("Tel Aviv District, Israel", "Tel Aviv"),
    ("Tel Aviv-Yafo, Tel Aviv District, Israel", "Tel Aviv"),
    ("Or Yehuda, Tel Aviv District, Israel", "Or Yehuda"),
    ("Yehud, Central District, Israel", "Yehud"),
    ("Be'er Sheva, Southern District, Israel", "Be'er Sheva"),
    ("Petah Tiqwa, Center District, Israel", "Petah Tikva"),
    ("קריית גת", "Kiryat Gat"),
    ("תל אביב-יפו", "Tel Aviv"),
    ("Ramat Gan, Tel Aviv", "Ramat Gan"),
])
def test_resolves_a_city(location, expected):
    assert resolve_city(location).en == expected


@pytest.mark.parametrize("location", [
    "", "Israel", "Central District, Israel", "Northern District, Israel",
    "Acre, Brazil", "London, England, United Kingdom", "Unknown", "Riverside",
])
def test_names_no_city_here(location):
    assert resolve_city(location) is None


def test_every_city_resolves_to_itself_in_both_languages():
    for city in CITIES:
        assert resolve_city(f"{city.en}, Israel") == city
        assert resolve_city(city.he) == city


def _goals(**kw):
    return {"home_city": "Tel Aviv", "search_mode": "radius", "radius_km": None, **kw}


@pytest.mark.parametrize("job,points", [
    ("Tel Aviv, Israel", 3.0),            # 0 km
    ("Ramat Gan, Israel", 3.0),           # ~5 km
    ("Kfar Saba, Israel", 2.0),           # ~15 km
    ("Rehovot, Israel", 2.0),             # ~22 km
    ("Netanya, Israel", 1.0),             # ~30 km
    ("Haifa, Israel", 0.0),               # ~80 km, whole country
])
def test_points_fall_with_distance(job, points):
    assert proximity_delta(_goals(), job) == points


def test_beyond_the_radius_gains_nothing():
    assert proximity_delta(_goals(radius_km=10), "Kfar Saba, Israel") == 0.0
    assert proximity_delta(_goals(radius_km=25), "Kfar Saba, Israel") == 2.0


def test_outside_the_chosen_regions_gains_nothing():
    goals = _goals(search_mode="regions", preferred_locations=["Tel Aviv"])
    assert proximity_delta(goals, "Ramat Gan, Israel") == 3.0
    assert proximity_delta(goals, "Herzliya, Israel") == 0.0


def test_regions_mode_with_none_picked_is_the_whole_country():
    goals = _goals(search_mode="regions", preferred_locations=[])
    assert proximity_delta(goals, "Herzliya, Israel") == 2.0


@pytest.mark.parametrize("goals,job", [
    ({}, "Tel Aviv, Israel"),                    # no home city: older profiles
    ({"home_city": "Atlantis"}, "Tel Aviv, Israel"),
    (_goals(), "Remote"),
    (_goals(), "Tel Aviv, Israel (Remote)"),
    (_goals(), "Israel"),
    (_goals(), ""),
])
def test_no_signal_is_none(goals, job):
    assert proximity_delta(goals, job) is None


def test_composite_without_signal_is_unchanged():
    assert finalize_composite(70, 80, 60, structural=75) == \
        finalize_composite(70, 80, 60, structural=75, proximity_delta=None)


def test_composite_adds_it_and_stays_in_bounds():
    base = finalize_composite(70, 80, 60, structural=75)
    assert finalize_composite(70, 80, 60, structural=75, proximity_delta=3.0) == round(base + 3.0, 1)
    assert finalize_composite(100, 100, 100, structural=100, proximity_delta=3.0) == 100.0


def test_knockout_cap_lands_after_it():
    assert finalize_composite(100, 100, 100, knockout_failed=True, proximity_delta=3.0) == 40.0


async def test_thin_jd_never_gets_it():
    """Principle 4: a thin JD scores exactly 0.30 × local, close to home or not."""
    far = await compute_match_score_async({}, "short", job_title="PM", user_id="u")
    near = await compute_match_score_async(
        {}, "short", job_title="PM", user_id="u", job_location="Tel Aviv, Israel",
    )
    assert near.total == far.total
    assert near.proximity_delta is None


def test_home_city_names_are_unique():
    assert len(CITY_BY_NAME) == len(CITIES)


class _FakeSession:
    def __init__(self, *_): pass
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def commit(self): pass


class _Row:
    master_profile: dict = {}
    updated_at = ""


@pytest.fixture
def about(monkeypatch):
    """The about routes over an in-memory profile, so no database is touched."""
    from types import SimpleNamespace
    from backend.api.routes import profile as route
    row, answers = _Row(), {}
    repo = route.profile_repository
    monkeypatch.setattr(route, "Session", _FakeSession)
    monkeypatch.setattr(repo, "get_or_create", lambda *a, **k: (row, False))
    monkeypatch.setattr(repo, "save", lambda *a: None)
    monkeypatch.setattr(repo, "set_answer", lambda _u, k, v: answers.__setitem__(k, v))
    monkeypatch.setattr(repo, "get_answer", lambda _u, k: answers.get(k))
    monkeypatch.setattr(repo, "get_profile_json", lambda _u: row.master_profile)
    return SimpleNamespace(route=route, row=row, user=SimpleNamespace(user_id="u"))


def _payload(route, **kw):
    return route.AboutPayload(**{"gender": "male", "work_environment": "any", "career_change": "yes", **kw})


async def test_radius_answer_round_trips_and_drives_the_factor(about):
    body = _payload(about.route, home_city="Tel Aviv", search_mode="radius", radius_km=25, locations=["Sharon"])
    await about.route.save_about(body, about.user)
    got = await about.route.get_about(about.user)
    assert (got["home_city"], got["search_mode"], got["radius_km"]) == ("Tel Aviv", "radius", 25)
    assert got["locations"] == []    # areas are not kept in distance mode
    goals = about.row.master_profile["career_goals"]
    assert proximity_delta(goals, "Kfar Saba, Israel") == 2.0
    assert proximity_delta(goals, "Haifa, Israel") == 0.0


async def test_regions_answer_round_trips_and_drives_the_factor(about):
    body = _payload(about.route, home_city="Haifa", search_mode="regions", radius_km=10, locations=["Haifa & North"])
    await about.route.save_about(body, about.user)
    got = await about.route.get_about(about.user)
    assert (got["search_mode"], got["radius_km"], got["locations"]) == ("regions", None, ["Haifa & North"])
    goals = about.row.master_profile["career_goals"]
    assert proximity_delta(goals, "Nesher, Israel") == 3.0
    assert proximity_delta(goals, "Tel Aviv, Israel") == 0.0


async def test_older_answer_with_areas_reads_as_regions(about):
    about.row.master_profile = {"career_goals": {"preferred_locations": ["Sharon"]}}
    got = await about.route.get_about(about.user)
    assert (got["search_mode"], got["home_city"]) == ("regions", None)


@pytest.mark.parametrize("bad", [
    {"home_city": "Atlantis"}, {"search_mode": "anywhere"}, {"radius_km": 7},
])
async def test_rejects_unknown_answers(about, bad):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as err:
        await about.route.save_about(_payload(about.route, **bad), about.user)
    assert err.value.status_code == 422


async def test_cities_route_lists_every_city(about):
    cities = await about.route.get_cities(about.user)
    assert len(cities) == len(CITIES)
    assert {"en": "Tel Aviv", "he": "תל אביב"} in cities
