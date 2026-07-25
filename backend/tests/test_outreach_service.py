import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from backend.services.outreach_service import generate_pitch_from_raw
from backend.schemas.job import DetailedAnalysis, JobMatch, RawJobPosting

@pytest.fixture
def mock_job_posting():
    return RawJobPosting(
        id="test-job",
        title="Senior AI Engineer",
        company="VentureTech",
        source_url="https://example.com/job",
        raw_text="Looking for an AI engineer to build amazing LLM products.",
        scraped_at="2026-07-12T00:00:00Z"
    )

@pytest.fixture
def mock_user_profile():
    return "Senior AI Engineer with 10 years of experience in Python and LLMs."

@pytest.mark.asyncio
async def test_generate_pitch_from_raw(mock_job_posting, mock_user_profile):
    # Setup mock LLM response with an AI tell
    mock_result = MagicMock()
    # "As an AI" should be stripped, "delve" should be replaced
    mock_result.text = "As an AI, I suggest you delve into this candidate. They are great!"
    mock_call_llm = AsyncMock(return_value=mock_result)

    # Execute
    with patch("backend.services.outreach_service.call_llm", new=mock_call_llm):
        result = await generate_pitch_from_raw(mock_job_posting, mock_user_profile)

    # Verify LLM was called
    mock_call_llm.assert_called_once()

    # Verify the scrubber was applied ("As an AI, I suggest you " is stripped in some scrubber logic,
    # but at least "delve" should be changed to "explore", and "As an AI" should be handled).
    # Since we know `clean_ai_text` cleans these, let's just assert the result doesn't have them.
    assert "As an AI" not in result
    assert "delve" not in result
    assert "explore" in result or "I suggest you" in result # "delve" is replaced with "explore"


# ---------------------------------------------------------------------------
# HTTP integration tests: POST /api/outreach/pitch/{job_id}
# ---------------------------------------------------------------------------
#
# Strategy (mirrors test_profile_trust.py's TestTrustScoreEndpoint):
#   • Override get_current_user so no real JWT is needed.
#   • Patch job_store.get_by_id (as imported into the route module) to avoid
#     touching the real DB.
#   • Patch generate_pitch_from_raw (as imported into the route module) to
#     avoid a real LLM call — its own behavior is already unit-tested above.

def _fake_job(job_id: str = "job-123") -> JobMatch:
    return JobMatch(
        job_id=job_id,
        title="Senior AI Engineer",
        company="VentureTech",
        location="Tel Aviv",
        score=88.0,
        confidence_score=80,
        culture_fit_score=70,
        trajectory_alignment="",
        company_dna_inference="",
        detailed_analysis=DetailedAnalysis(strengths=[], critical_gaps=[], strategic_advice=[]),
        investigation_points=[],
        reasons=[],
        apply_url="https://example.com/apply",
        jd_text="We need an AI engineer to build LLM products.",
        user_id="test-user",
        created_at="2026-07-12T00:00:00Z",
    )


class TestDirectPitchEndpoint:
    def _make_client(self, caller_user_id: str = "test-user") -> TestClient:
        from backend.main import app
        from backend.api.deps import CurrentUser, get_current_user

        def _override():
            return CurrentUser(user_id=caller_user_id, email="test@example.com")

        app.dependency_overrides[get_current_user] = _override
        return TestClient(app, raise_server_exceptions=False)

    def _teardown_client(self) -> None:
        from backend.main import app
        from backend.api.deps import get_current_user
        app.dependency_overrides.pop(get_current_user, None)

    def test_pitch_success(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.outreach.job_store.get_by_id", return_value=_fake_job()), \
                 patch("backend.api.routes.outreach.generate_pitch_from_raw", return_value="Short punchy pitch text here.") as mock_gen:
                res = client.post("/api/outreach/pitch/job-123")

            assert res.status_code == 200
            data = res.json()
            assert data["job_id"] == "job-123"
            assert data["pitch"] == "Short punchy pitch text here."
            assert data["word_count"] == 5
            mock_gen.assert_called_once()
            # First positional arg is the RawJobPosting bridged from the JobMatch
            posting = mock_gen.call_args.args[0]
            assert posting.id == "job-123"
            assert posting.title == "Senior AI Engineer"
            assert posting.company == "VentureTech"
            assert posting.source_url == "https://example.com/apply"
            assert posting.raw_text == "We need an AI engineer to build LLM products."
        finally:
            self._teardown_client()

    def test_pitch_job_not_found_returns_404(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.outreach.job_store.get_by_id", return_value=None):
                res = client.post("/api/outreach/pitch/missing-job")
            assert res.status_code == 404
        finally:
            self._teardown_client()

    def test_pitch_missing_api_key_returns_503(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.outreach.job_store.get_by_id", return_value=_fake_job()), \
                 patch("backend.api.routes.outreach.generate_pitch_from_raw",
                       side_effect=RuntimeError("ANTHROPIC_API_KEY is not set.")):
                res = client.post("/api/outreach/pitch/job-123")
            assert res.status_code == 503
        finally:
            self._teardown_client()

    def test_pitch_generation_failure_returns_502(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.outreach.job_store.get_by_id", return_value=_fake_job()), \
                 patch("backend.api.routes.outreach.generate_pitch_from_raw",
                       side_effect=Exception("LLM exploded")):
                res = client.post("/api/outreach/pitch/job-123")
            assert res.status_code == 502
        finally:
            self._teardown_client()

    def test_pitch_falls_back_to_placeholder_when_jd_text_missing(self):
        client = self._make_client()
        job = _fake_job()
        job = job.model_copy(update={"jd_text": None})
        try:
            with patch("backend.api.routes.outreach.job_store.get_by_id", return_value=job), \
                 patch("backend.api.routes.outreach.generate_pitch_from_raw", return_value="Pitch.") as mock_gen:
                res = client.post("/api/outreach/pitch/job-123")
            assert res.status_code == 200
            posting = mock_gen.call_args.args[0]
            assert "No full description stored" in posting.raw_text
            assert "Senior AI Engineer" in posting.raw_text
        finally:
            self._teardown_client()
