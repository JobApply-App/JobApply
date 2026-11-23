"""
Logs stay free of personal data (security report, 2026-11-23).

Render keeps the backend's logs and nothing scrubs them, so an email
address, a verification code or the text of a recruiter email written to a
log line stays there for anyone with dashboard access.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import webhooks
from backend.core.errors import install_error_handlers


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(webhooks, "_WEBHOOK_SECRET", "")
    monkeypatch.setattr(webhooks.kv_repository, "upsert", lambda key, value: None)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(webhooks.router, prefix="/api/webhooks")
    return TestClient(app)


def test_gmail_verification_code_is_not_logged(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=webhooks.logger.name)
    r = _client(monkeypatch).post("/api/webhooks/inbound-email", json={
        "sender": "forwarding-noreply@google.com",
        "subject": "Gmail Forwarding Confirmation - Receive Mail from dana.levi@example.com",
        "body_text": "Confirmation code: 123456789",
    })
    assert r.status_code == 200, r.text
    logged = caplog.text
    assert "Stored Gmail verification code" in logged   # the check really ran
    assert "123456789" not in logged
    assert "dana.levi" not in logged                    # address in the subject
    assert "forwarding-noreply@" not in logged          # sender kept to its domain
    assert "google.com" in logged
