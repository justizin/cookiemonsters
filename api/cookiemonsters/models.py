"""Wire formats. Everything the server accepts is closed: unknown fields are
rejected, strings are enums or tightly patterned, integers are bounded."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .scoring import FLAGS, OUTCOMES

SCHEMA_VERSION = 1

Outcome = Literal[OUTCOMES]  # type: ignore[valid-type]
Flag = Literal[FLAGS]  # type: ignore[valid-type]
Browser = Literal["chrome", "firefox", "safari", "edge", "other"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClientInfo(Strict):
    extension_version: str = Field(pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
    rules_version: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}(\.\d{1,2})?$")
    browser: Browser


class Report(Strict):
    """One visit's measurement. No identifiers, no time, no URL."""

    site: str = Field(min_length=3, max_length=253, description="Hostname or registrable domain; the server re-derives the registrable domain.")
    outcome: Outcome
    clicks: int = Field(ge=0, le=50)
    toggles_unticked: int = Field(ge=0, le=200)
    flags: list[Flag] = Field(default_factory=list, max_length=len(FLAGS))
    cmp: str = Field(default="generic", pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    client: ClientInfo

    @field_validator("flags")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("flags must be unique")
        return sorted(v)


class ReportBatch(Strict):
    reports: list[Report] = Field(min_length=1, max_length=25)


class ReportResult(BaseModel):
    accepted: int
    rejected: list[dict]


class SiteRecord(BaseModel):
    """One line of the ranking feed. Stable, versioned, documented in docs/DATA_FEED.md."""

    schema_version: int = SCHEMA_VERSION
    scoring_version: int
    site: str
    score: int = Field(ge=0, le=100, description="100 - friction; higher means refusing tracking is easier.")
    friction: int = Field(ge=0, le=100)
    grade: Literal["A", "B", "C", "D", "F"]
    confidence: Literal["low", "medium", "high"]
    reports: int = Field(ge=1, description="Reports inside the scoring window.")
    rank_signal: float = Field(ge=0, le=1, description="score/100 shrunk toward 0.5 by sample size; safe to use directly as a ranking feature.")
    window_weeks: int
    first_seen_week: str = Field(description="ISO week, e.g. 2026-W41.")
    last_seen_week: str
    outcomes: dict[str, float] = Field(description="Share of reports per outcome.")
    flags: dict[str, float] = Field(description="Share of reports with each dark-pattern flag.")
    dominant_flags: list[str]
    cmps: dict[str, float] = Field(description="Share of reports per consent-management platform.")
