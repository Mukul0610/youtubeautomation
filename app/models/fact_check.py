from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.models.research import ClaimStatus


class RecommendedAction(str, Enum):
    ACCEPT = "accept"
    RESEARCH_MORE = "research_more"
    REMOVE_OR_REWRITE = "remove_or_rewrite"


class FactCheckedClaim(BaseModel):
    claim_id: str = ""
    original_claim: str = Field(..., min_length=1)
    status: ClaimStatus
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., min_length=1)
    supporting_sources: list[str] = Field(default_factory=list)
    contradictory_sources: list[str] = Field(default_factory=list)
    recommended_action: RecommendedAction


class FactCheckResult(BaseModel):
    project_id: str | None = None
    total_claims: int = Field(..., ge=0)
    verified_claims: int = Field(..., ge=0)
    needs_review_claims: int = Field(..., ge=0)
    rejected_claims: int = Field(..., ge=0)
    claims: list[FactCheckedClaim] = Field(default_factory=list)
    overall_status: ClaimStatus
    needs_more_research: bool = False

    @model_validator(mode="after")
    def validate_counts(self):
        for index, claim in enumerate(self.claims, start=1):
            if not claim.claim_id:
                claim.claim_id = f"claim_{index:03d}"
        counts = {
            ClaimStatus.VERIFIED: self.verified_claims,
            ClaimStatus.NEEDS_REVIEW: self.needs_review_claims,
            ClaimStatus.REJECTED: self.rejected_claims,
        }
        if self.total_claims != len(self.claims):
            raise ValueError("total_claims must match the number of checked claims")
        if sum(counts.values()) != self.total_claims:
            raise ValueError("claim status counts must sum to total_claims")
        actual_counts = {status: 0 for status in counts}
        for claim in self.claims:
            actual_counts[claim.status] += 1
        if actual_counts != counts:
            raise ValueError("claim status counts do not match claims")
        if self.needs_more_research != (
            self.needs_review_claims > 0 or self.rejected_claims > 0
        ):
            raise ValueError("needs_more_research must reflect unresolved claims")
        return self
