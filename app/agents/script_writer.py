from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

from app.llm.factory import create_model
from app.models.fact_check import ClaimStatus, FactCheckResult
from app.models.research import ResearchProject
from app.models.script import Script, ScriptQualityReport, ScriptQualityStatus

logger = logging.getLogger(__name__)


class ScriptWriter:
    """Turn verified research into a traceable, fact-constrained script."""

    def __init__(self, model: Any | None = None, max_retries: int = 3):
        self.model = model
        self.max_retries = max_retries

    def write(
        self,
        research: ResearchProject,
        fact_check: FactCheckResult,
        *,
        project_id: str | None = None,
        project_dir: str | Path | None = None,
    ) -> Script:
        if project_dir is not None:
            cached = self.load_script(project_dir)
            if cached is not None:
                report = self.quality_report(cached, fact_check)
                if report.passed:
                    logger.info("[SCRIPT] Using cached script")
                    return cached

        if not research:
            raise ValueError("Script writing requires a research project.")
        if not fact_check:
            raise ValueError("Script writing requires a fact-check result.")
        verified = self._verified_claims(fact_check)
        if not verified:
            raise ValueError("Cannot write a confident script without verified claims.")

        logger.info("[SCRIPT] Starting; verified claims available: %d", len(verified))
        last_errors: list[str] = []
        for attempt in range(1, self.max_retries + 1):
            logger.info("[SCRIPT] Validation attempt %d", attempt)
            try:
                script = self._generate(research, fact_check, last_errors)
                report = self.quality_report(script, fact_check)
                logger.info("[SCRIPT] Word count: %d", report.word_count)
                if report.passed:
                    if project_dir is not None:
                        self.persist_script(script, project_dir)
                    logger.info("[SCRIPT] Complete")
                    return script
                last_errors = report.errors
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                last_errors = [str(exc)]
        raise ValueError(
            f"Script generation failed after {self.max_retries} attempts: {'; '.join(last_errors)}"
        )

    def _generate(
        self,
        research: ResearchProject,
        fact_check: FactCheckResult,
        previous_errors: list[str],
    ) -> Script:
        model = self.model or create_model(agent_name="script")
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a script writer for an original finance YouTube channel. Use only verified claims supplied below as established facts. Never invent statistics, dates, names, quotes, sources, or company facts. Exclude needs_review and rejected claims. Every factual section must list the exact claim IDs it uses. Write 1,100 to 1,800 spoken words at about 130 to 150 words per minute. Use six sections, each with roughly 250 to 300 words, plus the hook and conclusion. Do not stop early. The final narration must be at least 1,100 words. Return only the requested structured Script."),
            ("user", "Topic: {topic}\nVerified claims:\n{claims}\nResearch questions:\n{questions}\nPrevious validation errors to fix:\n{errors}\nRequired arc: hook, setup, relatable example, mechanism, how it works, growing complexity, important facts, why it matters, surprising insight, takeaway, ending."),
        ])
        verified = self._verified_claims(fact_check)
        claim_payload = [
            {"claim_id": claim.claim_id, "claim": claim.original_claim, "reasoning": claim.reasoning}
            for claim in verified
        ]
        messages = prompt.format_messages(
            topic=research.topic,
            claims=json.dumps(claim_payload),
            questions=json.dumps(research.key_questions),
            errors=json.dumps(previous_errors),
        )
        response = model.invoke(messages)
        return self._parse_script(response.content, topic=research.topic)

    @staticmethod
    def quality_report(script: Script, fact_check: FactCheckResult) -> ScriptQualityReport:
        errors: list[str] = []
        warnings: list[str] = []
        verified_ids = {
            claim.claim_id for claim in fact_check.claims if claim.status == ClaimStatus.VERIFIED
        }
        rejected_ids = {
            claim.claim_id for claim in fact_check.claims if claim.status == ClaimStatus.REJECTED
        }
        review_ids = {
            claim.claim_id for claim in fact_check.claims if claim.status == ClaimStatus.NEEDS_REVIEW
        }
        valid_ids = {claim.claim_id for claim in fact_check.claims}
        section_ids = [claim_id for section in script.sections for claim_id in section.claim_ids]
        referenced_ids = list(dict.fromkeys(script.factual_claim_ids + section_ids))
        unsupported_ids = [claim_id for claim_id in referenced_ids if claim_id not in verified_ids]
        rejected_references = [claim_id for claim_id in referenced_ids if claim_id in rejected_ids]

        if not 1_100 <= script.estimated_word_count <= 1_800:
            errors.append("estimated_word_count must be between 1100 and 1800 words")
        calculated_words = len(script.body.split())
        if not 1_100 <= calculated_words <= 1_800:
            errors.append("script narration must be between 1100 and 1800 words")
        expected_duration = round(calculated_words / (140 / 60))
        if not 8 * 60 <= script.estimated_duration_seconds <= 12 * 60:
            errors.append("estimated_duration_seconds must be between 8 and 12 minutes")
        if abs(script.estimated_duration_seconds - expected_duration) > 60:
            errors.append("estimated duration does not match the word count")
        if not script.hook.strip():
            errors.append("hook is required")
        if not script.conclusion.strip():
            errors.append("conclusion is required")
        if len(script.sections) < 5:
            errors.append("at least five narrative sections are required")
        if any(not section.narration.strip() for section in script.sections):
            errors.append("empty narration section found")
        if any(claim_id not in valid_ids for claim_id in referenced_ids):
            errors.append("script references a claim ID not present in FactCheckResult")
        if unsupported_ids:
            errors.append("script references claims that are not verified")
        if rejected_references:
            errors.append("script references rejected claims")
        if review_ids.intersection(referenced_ids):
            errors.append("script references needs_review claims as established facts")
        headings = " ".join(section.heading.lower() for section in script.sections)
        for label in ("setup", "example", "mechanism", "takeaway"):
            if label not in headings:
                warnings.append(f"story arc section '{label}' is not explicit")
        section_narration = [section.narration.strip() for section in script.sections]
        if len(set(section_narration)) != len(section_narration):
            warnings.append("repeated section content may reduce audience retention")

        return ScriptQualityReport(
            status=ScriptQualityStatus.PASS if not errors else ScriptQualityStatus.FAIL,
            word_count=calculated_words,
            estimated_duration_seconds=script.estimated_duration_seconds,
            errors=errors,
            warnings=warnings,
            referenced_claim_ids=referenced_ids,
            unsupported_claim_ids=unsupported_ids,
            rejected_claim_ids=rejected_references,
        )

    @staticmethod
    def _verified_claims(fact_check: FactCheckResult):
        return [claim for claim in fact_check.claims if claim.status == ClaimStatus.VERIFIED]

    @staticmethod
    def _parse_script(raw: Any, topic: str | None = None) -> Script:
        if isinstance(raw, dict):
            if "script_structure" in raw and isinstance(raw["script_structure"], dict):
                raw = raw["script_structure"]
            script_title = raw.get("script_title", raw.get("title"))
            sections_have_envelope_fields = any(
                isinstance(section, dict)
                and ("section_name" in section or "section_title" in section or "spoken_text" in section)
                for section in raw.get("sections", [])
            )
            if script_title and "sections" in raw and sections_have_envelope_fields:
                sections = raw.get("sections", [])
                normalized_sections = []
                for index, section in enumerate(sections, start=1):
                    if not isinstance(section, dict):
                        raise ValueError("script section must be an object")
                    narration = section.get("spoken_text", section.get("narration", ""))
                    normalized_sections.append({
                        "id": section.get("id", f"section_{index:03d}"),
                        "heading": section.get("section_name", section.get("section_title", section.get("heading", f"Section {index}"))),
                        "purpose": section.get("purpose", ""),
                        "narration": narration,
                        "visual_intent": section.get("visual_intent", ""),
                        "claim_ids": section.get("claim_ids", []),
                    })
                claim_ids = list(dict.fromkeys(
                    claim_id
                    for section in normalized_sections
                    for claim_id in section["claim_ids"]
                ))
                return Script.model_validate({
                    "topic": topic or raw.get("topic", "Script topic"),
                    "title": script_title,
                    "alternate_titles": raw.get("alternate_titles", []),
                    "hook": normalized_sections[0]["narration"] if normalized_sections else raw.get("hook", ""),
                    "sections": normalized_sections,
                    "conclusion": raw.get("conclusion", normalized_sections[-1]["narration"] if normalized_sections else ""),
                    "factual_claim_ids": raw.get("factual_claim_ids", claim_ids),
                })
            return Script.model_validate(raw)
        if isinstance(raw, list):
            text = "\n".join(
                block.get("text", "") for block in raw
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            )
            return ScriptWriter._parse_script(text, topic=topic)
        if not isinstance(raw, str):
            raise ValueError("script model returned an unsupported response")
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("script model returned invalid JSON") from exc
        return ScriptWriter._parse_script(payload, topic=topic)

    @staticmethod
    def persist_script(script: Script, project_dir: str | Path) -> tuple[Path, Path]:
        directory = Path(project_dir)
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / "script.json"
        text_path = directory / "script.txt"
        json_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
        lines = [script.title, "", script.hook, ""]
        for section in script.sections:
            lines.extend([section.heading, "", section.narration, ""])
        lines.extend(["Conclusion", "", script.conclusion, ""])
        text_path.write_text("\n".join(lines), encoding="utf-8")
        return json_path, text_path

    @staticmethod
    def load_script(project_dir: str | Path) -> Script | None:
        path = Path(project_dir) / "script.json"
        if not path.exists():
            return None
        try:
            return Script.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None
