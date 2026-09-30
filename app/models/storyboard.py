from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class StoryboardScene(BaseModel):
    id: int | str
    duration_seconds: int = Field(..., ge=5, le=15)
    narration: str = Field(..., min_length=1)
    visual_description: str = Field(..., min_length=1)
    on_screen_text: str = Field(default="")
    background: str = Field(..., min_length=1)
    characters: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    camera: str = Field(default="static")
    transition: str = Field(default="cut")
    claim_ids: list[str] = Field(default_factory=list)

    @field_validator("characters", "props")
    @classmethod
    def normalize_lists(cls, value):
        return [item.strip() for item in value if item and item.strip()]

    @field_validator("claim_ids")
    @classmethod
    def normalize_claim_ids(cls, value):
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))

    @field_validator("narration", "visual_description", "background")
    @classmethod
    def reject_blank_text(cls, value):
        if not value.strip():
            raise ValueError("storyboard scene text cannot be blank")
        return value


class Storyboard(BaseModel):
    title: str = ""
    estimated_duration_seconds: int = Field(default=0, ge=0)
    scenes: list[StoryboardScene] = Field(default_factory=list)

    @model_validator(mode="after")
    def calculate_duration(self):
        self.estimated_duration_seconds = self.total_duration_seconds
        return self

    @property
    def total_duration_seconds(self) -> int:
        return sum(scene.duration_seconds for scene in self.scenes)
