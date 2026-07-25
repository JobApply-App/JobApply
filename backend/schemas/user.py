from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class UserProfile(BaseModel):
    skills: list[str] = []
    years_of_experience: int = 0
    seniority_level: str = "senior"
    preferred_locations: list[str] = []
    salary_target_min: Optional[int] = None
    salary_target_max: Optional[int] = None
    open_to_remote: bool = True
    summary: Optional[str] = None


class AutomationSettings(BaseModel):
    auto_apply: bool = True
    threshold: int = 85
    daily_limit: int = 15
    daily_used: int = 0
    tailor_cover_letter: bool = True
    skip_duplicate_companies: bool = True
    pause_on_rejection: bool = False
    approve_below_salary: bool = True
    salary_target: int = 120000
