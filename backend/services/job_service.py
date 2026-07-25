"""
JobService — CRUD layer between the API routes and the database.
"""
from __future__ import annotations

from backend.schemas.job import JobMatch


class JobService:
    async def get_matches(
        self,
        user_id: str,
        filter: str = "all",
        sort: str = "match",
        limit: int = 50,
    ) -> list[JobMatch]:
        # TODO: query DB with filters
        return []

    async def save_job(self, user_id: str, job_id: str) -> None:
        # TODO: upsert saved_jobs table
        pass

    async def dismiss_job(self, user_id: str, job_id: str) -> None:
        # TODO: upsert dismissed_jobs table
        pass
