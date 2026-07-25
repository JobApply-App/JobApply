"""
HTTP tests for the Ariel Mock Interview Simulator routes (JOB-61).

  POST /api/jobs/{job_id}/interview/question
  POST /api/jobs/{job_id}/interview/answer

Strategy mirrors test_outreach_service.py's TestDirectPitchEndpoint:
  • Override get_current_user so no real JWT is needed.
  • Patch job_store.get_by_id (as imported into the route module).
  • Patch the interview_simulator functions (their own behavior is covered by
    test_interview_simulator.py) — no real LLM calls.
"""
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from backend.schemas.job import DetailedAnalysis, JobMatch, ReasonTag


def _fake_job(job_id: str = "job-123", jd_text: str = "We need a PM with SQL and Jira experience.") -> JobMatch:
    return JobMatch(
        job_id=job_id,
        title="Senior Product Manager",
        company="VentureTech",
        location="Tel Aviv",
        score=88.0,
        confidence_score=80,
        culture_fit_score=70,
        trajectory_alignment="",
        company_dna_inference="",
        detailed_analysis=DetailedAnalysis(
            strengths=[], critical_gaps=["No people-management experience"], strategic_advice=[],
        ),
        investigation_points=[],
        reasons=[ReasonTag(kind="neg", label="No SQL exp. (required)")],
        apply_url="https://example.com/apply",
        jd_text=jd_text,
        user_id="test-user",
        created_at="2026-07-12T00:00:00Z",
    )


class TestInterviewEndpoints:
    def _make_client(self, caller_user_id: str = "interview-test-user") -> TestClient:
        from backend.main import app
        from backend.api.deps import CurrentUser, get_current_user, llm_rate_limit

        def _override():
            return CurrentUser(user_id=caller_user_id, email="test@example.com")

        app.dependency_overrides[get_current_user] = _override
        # Neutralize the per-caller LLM budget: without this, these tests
        # exhaust the shared in-process bucket and later suites hitting
        # llm_rate_limit routes (e.g. the pitch endpoint tests) 429.
        app.dependency_overrides[llm_rate_limit] = lambda: None
        return TestClient(app, raise_server_exceptions=False)

    def _teardown_client(self) -> None:
        from backend.main import app
        from backend.api.deps import get_current_user, llm_rate_limit
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(llm_rate_limit, None)

    # ── Question generation ───────────────────────────────────────────────────

    def test_question_success_and_gap_context(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=_fake_job()), \
                 patch("backend.services.interview_simulator.generate_interview_question",
                       new=AsyncMock(return_value="How have you used SQL to drive a product decision?")) as mock_gen:
                res = client.post("/api/jobs/job-123/interview/question")

            assert res.status_code == 200
            data = res.json()
            assert data["job_id"] == "job-123"
            assert data["question"].startswith("How have you used SQL")

            # skills_gap arg is derived from stored neg reasons + critical gaps,
            # deduplicated — never a second LLM call.
            skills_gap = mock_gen.call_args.args[2]
            assert "No SQL exp. (required)" in skills_gap
            assert "No people-management experience" in skills_gap
        finally:
            self._teardown_client()

    def test_question_job_not_found_returns_404(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=None):
                res = client.post("/api/jobs/missing/interview/question")
            assert res.status_code == 404
        finally:
            self._teardown_client()

    def test_question_thin_jd_returns_400(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id",
                       return_value=_fake_job(jd_text="")):
                res = client.post("/api/jobs/job-123/interview/question")
            assert res.status_code == 400
            assert "JD text" in res.json()["detail"]
        finally:
            self._teardown_client()

    def test_question_missing_api_key_sentinel_maps_to_503(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=_fake_job()), \
                 patch("backend.services.interview_simulator.generate_interview_question",
                       new=AsyncMock(return_value="API Key missing. Unable to generate question.")):
                res = client.post("/api/jobs/job-123/interview/question")
            assert res.status_code == 503
        finally:
            self._teardown_client()

    def test_question_failure_sentinel_maps_to_502(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=_fake_job()), \
                 patch("backend.services.interview_simulator.generate_interview_question",
                       new=AsyncMock(return_value="Failed to generate interview question.")):
                res = client.post("/api/jobs/job-123/interview/question")
            assert res.status_code == 502
        finally:
            self._teardown_client()

    # ── Answer evaluation ─────────────────────────────────────────────────────

    def test_answer_success(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=_fake_job()), \
                 patch("backend.services.interview_simulator.evaluate_interview_answer",
                       new=AsyncMock(return_value="Strong on process; quantify the outcome next time.")) as mock_eval:
                res = client.post("/api/jobs/job-123/interview/answer", json={
                    "question": "How have you used SQL?",
                    "answer":   "I built retention dashboards querying Postgres directly.",
                })

            assert res.status_code == 200
            data = res.json()
            assert data["job_id"] == "job-123"
            assert "quantify" in data["feedback"]
            # Evaluation receives (question, answer, jd_text) in order
            q, a, jd = mock_eval.call_args.args
            assert q == "How have you used SQL?"
            assert "retention dashboards" in a
            assert "PM with SQL" in jd
        finally:
            self._teardown_client()

    def test_answer_empty_body_rejected_422(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=_fake_job()):
                res = client.post("/api/jobs/job-123/interview/answer", json={
                    "question": "Q?", "answer": "",
                })
            assert res.status_code == 422    # pydantic min_length gate
        finally:
            self._teardown_client()

    def test_answer_job_not_found_returns_404(self):
        client = self._make_client()
        try:
            with patch("backend.api.routes.jobs.job_store.get_by_id", return_value=None):
                res = client.post("/api/jobs/missing/interview/answer", json={
                    "question": "Q?", "answer": "A.",
                })
            assert res.status_code == 404
        finally:
            self._teardown_client()
