from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class AssetType(str, Enum):
    CHARACTER = "character"
    BACKGROUND = "background"
    PROP = "prop"
    ICON = "icon"
    ILLUSTRATION = "illustration"
    CHART = "chart"
    DIAGRAM = "diagram"
    TEXT = "text"


class AssetRequest(BaseModel):
    asset_id: str = Field(..., min_length=1)
    type: AssetType
    description: str = Field(..., min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    reusable: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_claim_ids(self):
        self.claim_ids = list(dict.fromkeys(self.claim_ids))
        return self


class Asset(BaseModel):
    asset_id: str = Field(..., min_length=1)
    type: AssetType
    description: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    format: str = Field(default="png", min_length=1)
    reusable: bool = True
    status: str = "ready"
    claim_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class AssetRegistry(BaseModel):
    project_id: str | None = None
    visual_style: str = Field(default="modern_finance", min_length=1)
    assets: list[Asset] = Field(default_factory=list)


class ChartAssetRequest(BaseModel):
    asset_id: str = Field(..., min_length=1)
    chart_type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    labels: list[str] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)
    source_claim_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_values(self):
        if self.values and len(self.values) != len(self.labels):
            raise ValueError("chart labels and values must have equal lengths")
        return self


class DiagramAssetRequest(BaseModel):
    asset_id: str = Field(..., min_length=1)
    nodes: list[str] = Field(default_factory=list)
    edges: list[tuple[str, str]] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
