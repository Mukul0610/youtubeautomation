from __future__ import annotations

from enum import Enum

from app.models.fact_check import FactCheckResult
from app.models.research import ResearchProject
from app.models.script import Script
from app.models.storyboard import Storyboard
from app.models.tts import TTSResult


class PipelineStatus(str, Enum):
    """Pipeline lifecycle status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoState(dict):
    """Runtime-safe shared state for the video pipeline.

    This keeps the field names typed at the class level while ensuring defaults are
    populated for every new project state.
    """

    project_id: str
    topic: str
    status: PipelineStatus
    research: ResearchProject | None
    fact_check: FactCheckResult | None
    script: Script | None
    storyboard: Storyboard | None
    tts_result: TTSResult | None
    audio_path: str | None
    scene_paths: list[str]
    final_video_path: str | None
    errors: list[str]
    fact_check_iteration: int
    max_fact_check_iterations: int

    def __init__(self, **kwargs):
        base_state = {
            "status": PipelineStatus.PENDING,
            "research": None,
            "fact_check": None,
            "script": None,
            "storyboard": None,
            "tts_result": None,
            "errors": [],
            "scene_paths": [],
            "fact_check_iteration": 0,
            "max_fact_check_iterations": 3,
        }
        base_state.update(kwargs)
        super().__init__(base_state)


def make_video_state(**kwargs) -> VideoState:
    return VideoState(**kwargs)
