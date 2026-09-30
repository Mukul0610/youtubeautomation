from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

from app.llm.factory import create_model
from app.models.fact_check import ClaimStatus, FactCheckResult
from app.models.script import Script
from app.models.storyboard import Storyboard

logger = logging.getLogger(__name__)


class StoryboardAgent:
    """Convert a validated Script into a renderer-friendly storyboard."""

    def __init__(self, model: Any | None = None, max_retries: int = 3):
        self.model = model
        self.max_retries = max_retries

    def create(
        self,
        script: Script,
        fact_check: FactCheckResult | None = None,
        *,
        project_id: str | None = None,
        project_dir: str | Path | None = None,
    ) -> Storyboard:
        if project_dir is not None:
            cached = self.load_storyboard(project_dir)
            if cached is not None:
                self.validate_storyboard(cached, script, fact_check)
                logger.info("[STORYBOARD] Using cached storyboard")
                return cached

        if script is None:
            raise ValueError("Storyboard generation requires a validated Script.")
        if not script.hook.strip() or not script.conclusion.strip():
            raise ValueError("Storyboard generation requires a non-empty hook and conclusion.")
        if not script.sections:
            raise ValueError("Storyboard generation requires at least one Script section.")

        errors: list[str] = []
        for attempt in range(1, self.max_retries + 1):
            logger.info("[STORYBOARD] Validation attempt %d", attempt)
            try:
                storyboard = self._generate(script, fact_check, errors)
                self.validate_storyboard(storyboard, script, fact_check)
                if project_dir is not None:
                    self.persist_storyboard(storyboard, project_dir)
                logger.info("[STORYBOARD] Complete; scenes: %d", len(storyboard.scenes))
                return storyboard
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                errors = [str(exc)]
        raise ValueError(
            f"Storyboard generation failed after {self.max_retries} attempts: {'; '.join(errors)}"
        )

    def _generate(
        self,
        script: Script,
        fact_check: FactCheckResult | None,
        previous_errors: list[str],
    ) -> Storyboard:
        model = self.model or create_model(agent_name="storyboard")
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a storyboard planner. Convert the supplied Script into concrete renderer-friendly scenes. Do not rewrite narration or add factual claims. Copy narration from the Script exactly or use contiguous excerpts. Every factual scene must use only the Script claim_ids. Use stable asset IDs such as customer_01 and payment_terminal_01. Keep each scene 5 to 15 seconds and use concise on-screen text. Return only a JSON Storyboard."),
            ("user", "Script:\n{script}\nFact-check claim statuses:\n{claims}\nPrevious validation errors:\n{errors}"),
        ])
        claim_statuses = []
        if fact_check is not None:
            claim_statuses = [
                {"claim_id": claim.claim_id, "status": claim.status.value}
                for claim in fact_check.claims
            ]
        messages = prompt.format_messages(
            script=script.model_dump_json(),
            claims=json.dumps(claim_statuses),
            errors=json.dumps(previous_errors),
        )
        response = model.invoke(messages)
        return self._parse_storyboard(response.content, script.title)

    @classmethod
    def validate_storyboard(
        cls,
        storyboard: Storyboard,
        script: Script,
        fact_check: FactCheckResult | None = None,
    ) -> Storyboard:
        if not storyboard.scenes:
            raise ValueError("storyboard must contain at least one scene")
        script_claim_ids = set(script.factual_claim_ids)
        script_claim_ids.update(
            claim_id for section in script.sections for claim_id in section.claim_ids
        )
        checked_claims = {claim.claim_id: claim for claim in fact_check.claims} if fact_check else {}
        rejected_ids = {
            claim_id for claim_id, claim in checked_claims.items()
            if claim.status == ClaimStatus.REJECTED
        }
        verified_ids = {
            claim_id for claim_id, claim in checked_claims.items()
            if claim.status == ClaimStatus.VERIFIED
        }
        referenced_ids = [claim_id for scene in storyboard.scenes for claim_id in scene.claim_ids]
        unknown_ids = sorted(set(referenced_ids) - script_claim_ids)
        if unknown_ids:
            raise ValueError(f"storyboard references unknown Script claim IDs: {unknown_ids}")
        rejected_references = sorted(set(referenced_ids) & rejected_ids)
        if rejected_references:
            raise ValueError(f"storyboard references rejected claim IDs: {rejected_references}")
        if fact_check is not None:
            unresolved = sorted((set(referenced_ids) & set(checked_claims)) - verified_ids)
            if unresolved:
                raise ValueError(f"storyboard references non-verified claim IDs: {unresolved}")

        storyboard_text = " ".join(scene.narration for scene in storyboard.scenes)
        missing_parts = [part for part in (script.hook, script.conclusion) if part.strip() and part.strip() not in storyboard_text]
        missing_sections = [
            section.heading for section in script.sections
            if section.narration.strip() and section.narration.strip() not in storyboard_text
        ]
        if missing_parts:
            raise ValueError("storyboard does not cover the Script hook or conclusion")
        if missing_sections:
            raise ValueError(f"storyboard does not cover Script sections: {missing_sections}")

        expected_duration = script.estimated_duration_seconds
        actual_duration = storyboard.total_duration_seconds
        if expected_duration <= 0:
            raise ValueError("Script estimated duration must be positive")
        tolerance = max(5, round(expected_duration * 0.10))
        if abs(actual_duration - expected_duration) > tolerance:
            raise ValueError(
                f"storyboard duration {actual_duration}s differs from Script duration "
                f"{expected_duration}s by more than {tolerance}s"
            )
        return storyboard

    @staticmethod
    def _parse_storyboard(raw: Any, title: str) -> Storyboard:
        if isinstance(raw, list):
            text = "\n".join(
                block.get("text", "") for block in raw
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            )
            return StoryboardAgent._parse_storyboard(text, title)
        if isinstance(raw, dict):
            payload = dict(raw)
        elif isinstance(raw, str):
            text = raw.strip()
            if text.startswith("```"):
                text = text.strip("`").strip()
                if text.startswith("json"):
                    text = text[4:].strip()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("storyboard model returned invalid JSON") from exc
        else:
            raise ValueError("storyboard model returned an unsupported response")
        if "storyboard" in payload and isinstance(payload["storyboard"], dict):
            payload = payload["storyboard"]
        payload.setdefault("title", title)
        return Storyboard.model_validate(payload)

    @staticmethod
    def persist_storyboard(storyboard: Storyboard, project_dir: str | Path) -> Path:
        path = Path(project_dir) / "storyboard.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(storyboard.model_dump_json(indent=2), encoding="utf-8")
        return path

    @staticmethod
    def load_storyboard(project_dir: str | Path) -> Storyboard | None:
        path = Path(project_dir) / "storyboard.json"
        if not path.exists():
            return None
        try:
            return Storyboard.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None
