import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from backend.schemas.job import DetailedAnalysis, JobMatch

# ---------------------------------------------------------------------------
# HTTP integration tests: POST /api/jobs/{job_id}/skills-gap
# ---------------------------------------------------------------------------
# Mirrors TestDirectPitchEndpoint in test_outreach_service.py: override auth,
# patch job_store.get_by_id and analyze_skills_gap (as imported into the
# route module) so no real DB or LLM call happens.


def _fake_job(job_id: str = "job-123", jd_text: str = "Needs Django, React, Kubernetes.") -> JobMatch:
    return JobMatch(
        job_id=job_id,
        title="Backend Engineer",
        company="VentureTech",
        location="Tel Aviv",
        score=75.0,
        confidence_score=60,
        culture_fit_score=60,
        trajectory_alignment="",
        company_dna_inference="",
        detailed_analysis=DetailedAnalysis(strengths=[], critical_gaps=[], strategic_advice=[]),
        investigation_points=[],
        reasons=[],
        jd_text=jd_text,
        user_id="test-user",
    )


class TestSkillsGapEndpoint:
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

    def test_skills_gap_success(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=_fake_job()), \
                 patch("backend.services.skills_gap_service.analyze_skills_gap",
                       new=AsyncMock(return_value="- Missing Django\n- Missing Kubernetes")) as mock_gap:
                res = client.post("/api/jobs/job-123/skills-gap")

            assert res.status_code == 200
            data = res.json()
            assert data["job_id"] == "job-123"
            assert "Missing Django" in data["analysis"]
            mock_gap.assert_called_once()
            assert mock_gap.call_args.args[0] == "Needs Django, React, Kubernetes."
        finally:
            self._teardown_client()

    def test_skills_gap_job_not_found_returns_404(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=None):
                res = client.post("/api/jobs/missing-job/skills-gap")
            assert res.status_code == 404
        finally:
            self._teardown_client()

    def test_skills_gap_no_jd_text_returns_400(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=_fake_job(jd_text="")):
                res = client.post("/api/jobs/job-123/skills-gap")
            assert res.status_code == 400
        finally:
            self._teardown_client()

    def test_skills_gap_service_failure_returns_500(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=_fake_job()), \
                 patch("backend.services.skills_gap_service.analyze_skills_gap",
                       new=AsyncMock(side_effect=Exception("LLM exploded"))):
                res = client.post("/api/jobs/job-123/skills-gap")
            assert res.status_code == 500
        finally:
            self._teardown_client()
