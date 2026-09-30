from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ScriptQualityStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class ScriptSection(BaseModel):
    id: str = ""
    heading: str = Field(..., min_length=1)
    purpose: str = ""
    narration: str = ""
    visual_intent: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    content: str = ""

    @model_validator(mode="after")
    def normalize_narration(self):
        if not self.id:
            self.id = self.heading.lower().replace(" ", "_")
        if not self.narration and self.content:
            self.narration = self.content
        if not self.content and self.narration:
            self.content = self.narration
        if not self.narration.strip():
            raise ValueError("script sections must contain narration")
        return self


class Script(BaseModel):
    topic: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    alternate_titles: list[str] = Field(default_factory=list)
    hook: str = Field(..., min_length=1)
    sections: list[ScriptSection] = Field(default_factory=list)
    conclusion: str = ""
    estimated_duration_seconds: int = Field(default=0, ge=0)
    estimated_word_count: int = Field(default=0, ge=0)
    factual_claim_ids: list[str] = Field(default_factory=list)
    body: str = ""
    takeaways: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def calculate_metrics(self):
        narration = " ".join(
            [self.hook, *(section.narration for section in self.sections), self.conclusion]
        )
        if not self.body:
            self.body = narration
        self.estimated_word_count = len(narration.split())
        self.estimated_duration_seconds = round(self.estimated_word_count / (140 / 60))
        return self


class ScriptQualityReport(BaseModel):
    status: ScriptQualityStatus
    word_count: int = Field(..., ge=0)
    estimated_duration_seconds: int = Field(..., ge=0)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    referenced_claim_ids: list[str] = Field(default_factory=list)
    unsupported_claim_ids: list[str] = Field(default_factory=list)
    rejected_claim_ids: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == ScriptQualityStatus.PASS
