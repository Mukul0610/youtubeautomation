from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.agents.fact_checker import FactChecker
from app.agents.script_writer import ScriptWriter
from app.agents.storyboard_agent import StoryboardAgent
from app.agents.tts_agent import TTSAgent
from app.graph.state import VideoState


def node_start(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    return state


def node_research(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    return state


def node_fact_check(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    project = state.get("research")
    if project is None:
        state["errors"].append("Fact checking requires a completed research project.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        state["fact_check"] = FactChecker().check(
            project,
            project_id=state.get("project_id"),
            project_dir=project_dir,
        )
    except Exception as exc:
        state["errors"].append(f"Fact checking failed: {exc}")
        state["status"] = "failed"
    return state


def node_script(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    research = state.get("research")
    fact_check = state.get("fact_check")
    if research is None:
        state["errors"].append("Script writing requires a completed research project.")
        state["status"] = "failed"
        return state
    if fact_check is None:
        state["errors"].append("Script writing requires a completed fact-check result.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        state["script"] = ScriptWriter().write(
            research,
            fact_check,
            project_id=state.get("project_id"),
            project_dir=project_dir,
        )
    except Exception as exc:
        state["errors"].append(f"Script writing failed: {exc}")
        state["status"] = "failed"
    return state


def node_storyboard(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    script = state.get("script")
    if script is None:
        state["errors"].append("Storyboard generation requires a completed script.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        state["storyboard"] = StoryboardAgent().create(
            script,
            state.get("fact_check"),
            project_id=state.get("project_id"),
            project_dir=project_dir,
        )
    except Exception as exc:
        state["errors"].append(f"Storyboard generation failed: {exc}")
        state["status"] = "failed"
    return state


def node_tts(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    storyboard = state.get("storyboard")
    if storyboard is None:
        state["errors"].append("TTS requires a completed storyboard.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        state["tts_result"] = TTSAgent().synthesize(
            storyboard,
            project_id=state.get("project_id"),
            project_dir=project_dir,
        )
    except Exception as exc:
        state["errors"].append(f"TTS failed: {exc}")
        state["status"] = "failed"
    return state


def node_render(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    return state


def node_compose(state: VideoState) -> VideoState:
    state["status"] = "completed"
    return state


def build_workflow() -> StateGraph:
    workflow = StateGraph(VideoState)
    workflow.add_node("start", node_start)
    workflow.add_node("research", node_research)
    workflow.add_node("fact_check", node_fact_check)
    workflow.add_node("script", node_script)
    workflow.add_node("storyboard", node_storyboard)
    workflow.add_node("tts", node_tts)
    workflow.add_node("render", node_render)
    workflow.add_node("compose", node_compose)

    workflow.add_edge(START, "start")
    workflow.add_edge("start", "research")
    workflow.add_edge("research", "fact_check")
    workflow.add_edge("fact_check", "script")
    workflow.add_edge("script", "storyboard")
    workflow.add_edge("storyboard", "tts")
    workflow.add_edge("tts", END)
    return workflow
