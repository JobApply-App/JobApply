"""
Deep User Profile models.

A profile is more than a CV — it encodes not just what was done but
*why it matters* and *how it transfers* to new contexts.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class ProfessionalRole(BaseModel):
    title: str
    company: str
    industry: str
    employment_type: str                  # full-time | contract | internship
    start_year: int
    end_year: Optional[int] = None        # None = current
    location: str
    summary: str
    responsibilities: list[str]
    achievements: list[str]
    skills_gained: list[str]
    keywords: list[str]                   # for gap-analysis matching


class Education(BaseModel):
    institution: str
    degree: str
    field_of_study: str
    start_year: int
    end_year: int
    location: str
    highlights: list[str]
    notable_projects: list["ProjectAchievement"] = []


class VolunteerRole(BaseModel):
    organization: str
    role: str
    cause: str
    start_year: int
    end_year: Optional[int] = None
    duration_years: float
    description: str
    skills_demonstrated: list[str]
    measurable_impact: str
    cultural_signal: str   # what this says about the person


class SoftSkill(BaseModel):
    skill: str
    proficiency: str                 # foundational | proficient | expert
    evidence: list[str]              # concrete examples from experience


class ProjectAchievement(BaseModel):
    title: str
    context: str                     # academic | work | personal | hackathon
    year: Optional[int] = None
    organization: Optional[str] = None
    description: str
    technologies: list[str]
    outcome: str
    transferable_learnings: list[str]


class CandidateProfile(BaseModel):
    full_name: str
    current_title: str
    location: str
    languages: list[str]
    values: list[str]
    elevator_pitch: str              # 2-3 sentence narrative for recruiters

    professional_history: list[ProfessionalRole]
    education: list[Education]
    volunteer_work: list[VolunteerRole]
    soft_skills: list[SoftSkill]
    project_achievements: list[ProjectAchievement]

    # Derived helper used by the gap-analysis node
    @property
    def all_keywords(self) -> set[str]:
        kws: set[str] = set()
        for role in self.professional_history:
            kws.update(k.lower() for k in role.keywords)
        return kws

    @property
    def all_companies(self) -> list[str]:
        return [r.company for r in self.professional_history]

    @property
    def total_years_experience(self) -> float:
        total = 0.0
        for role in self.professional_history:
            end = role.end_year or 2025
            total += end - role.start_year
        return total
