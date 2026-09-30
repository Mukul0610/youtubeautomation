from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class ClaimStatus(str, Enum):
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class ResearchQuestion(BaseModel):
    question: str = Field(..., min_length=1)
    rationale: str | None = None


class Source(BaseModel):
    url: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    publisher: str = Field(..., min_length=1)
    publication_date: str | None = None
    accessed_at: str | None = None
    relevance: str = Field(default="medium")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if value.startswith("http://") or value.startswith("https://"):
            return value
        raise ValueError("url must be a valid HTTP URL")


class ResearchClaim(BaseModel):
    claim: str = Field(..., min_length=1)
    importance: str = Field(default="medium")
    source_url: str = Field(default="")
    source_title: str = Field(default="")
    evidence: str = Field(..., min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: ClaimStatus = ClaimStatus.VERIFIED

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        if not value:
            return value
        if value.startswith("http://") or value.startswith("https://"):
            return value
        raise ValueError("source_url must be a valid HTTP URL or an empty string")


class ResearchSection(BaseModel):
    title: str = Field(..., min_length=1)
    summary: str | None = None


class ResearchProject(BaseModel):
    topic: str = Field(..., min_length=1)
    questions: list[ResearchQuestion] = Field(default_factory=list)
    key_questions: list[str] = Field(default_factory=list)
    sections: list[str | ResearchSection] = Field(default_factory=list)
    claims: list[ResearchClaim] = Field(default_factory=list)
    sources: list[str | Source] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_fields(self):
        if not self.questions and self.key_questions:
            self.questions = [ResearchQuestion(question=q) for q in self.key_questions]

        if not self.key_questions and self.questions:
            self.key_questions = [q.question for q in self.questions]

        normalized_questions = []
        for item in self.questions:
            if isinstance(item, dict):
                normalized_questions.append(ResearchQuestion.model_validate(item))
            else:
                normalized_questions.append(item)
        self.questions = normalized_questions
        self.key_questions = [q.question for q in self.questions]

        normalized_sections = []
        for item in self.sections:
            if isinstance(item, dict):
                normalized_sections.append(ResearchSection.model_validate(item))
            else:
                normalized_sections.append(item)
        self.sections = normalized_sections

        normalized_claims = []
        for item in self.claims:
            if isinstance(item, dict):
                normalized_claims.append(ResearchClaim.model_validate(item))
            else:
                normalized_claims.append(item)
        self.claims = normalized_claims

        normalized_sources = []
        for item in self.sources:
            if isinstance(item, dict):
                normalized_sources.append(Source.model_validate(item))
            else:
                normalized_sources.append(item)
        self.sources = normalized_sources

        return self

    @property
    def summary_sections(self) -> list[str]:
        return [
            section.title if isinstance(section, ResearchSection) else str(section)
            for section in self.sections
        ]
