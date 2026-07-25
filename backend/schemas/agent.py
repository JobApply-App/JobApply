from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel

AgentState = Literal["active", "idle", "queued", "error", "paused"]

AgentName = Literal[
    "Scraper",
    "Sourcing Specialist",
    "Content Strategist",
    "Quality Guard",
]


class AgentStats(BaseModel):
    today: int = 0
    queue: int = 0
    spark: list[int] = []


class AgentStatus(BaseModel):
    id: str
    name: AgentName
    role: str
    state: AgentState
    current_task:  Optional[str] = None
    queue_msg:     Optional[str] = None
    error_msg:     Optional[str] = None
    stats: AgentStats
