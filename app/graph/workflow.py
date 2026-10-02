from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from app.agents.fact_checker import FactChecker
from app.agents.script_writer import ScriptWriter
from app.agents.storyboard_agent import StoryboardAgent
from app.agents.tts_agent import TTSAgent
from app.agents.asset_agent import AssetAgent
from app.renderer.scene import SceneRenderer
from app.composer.video import VideoComposer
from app.agents.thumbnail_agent import ThumbnailAgent
from app.agents.youtube_publisher import YouTubePublisher
from app.agents.analytics_agent import AnalyticsAgent
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


def node_visual_assets(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    storyboard = state.get("storyboard")
    if storyboard is None:
        state["errors"].append("Visual asset generation requires a completed storyboard.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        state["visual_assets"] = AssetAgent().generate(
            storyboard,
            fact_check=state.get("fact_check"),
            project_id=state.get("project_id"),
            project_dir=project_dir,
        )
    except Exception as exc:
        state["errors"].append(f"Visual asset generation failed: {exc}")
        state["status"] = "failed"
    return state


def node_render_scenes(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    storyboard = state.get("storyboard")
    tts_result = state.get("tts_result")
    visual_assets = state.get("visual_assets")
    if storyboard is None or tts_result is None or visual_assets is None:
        state["errors"].append("Scene rendering requires storyboard, TTS, and visual assets.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        state["rendered_scenes"] = SceneRenderer().render_project(
            storyboard, tts_result, visual_assets, project_dir, state.get("project_id")
        )
    except Exception as exc:
        state["errors"].append(f"Scene rendering failed: {exc}")
        state["status"] = "failed"
    return state


def node_compose_video(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    storyboard = state.get("storyboard")
    rendered_scenes = state.get("rendered_scenes")
    if storyboard is None or rendered_scenes is None:
        state["errors"].append("Video composition requires a storyboard and rendered scenes.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        state["final_video"] = VideoComposer().compose(
            storyboard, rendered_scenes, project_dir, state.get("project_id")
        )
        state["final_video_path"] = state["final_video"].video_path
        state["status"] = "completed"
    except Exception as exc:
        state["errors"].append(f"Video composition failed: {exc}")
        state["status"] = "failed"
    return state


def node_thumbnail(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    registry = state.get("visual_assets")
    storyboard = state.get("storyboard")
    final_video = state.get("final_video")
    if registry is None or storyboard is None or final_video is None:
        state["errors"].append("Thumbnail generation requires storyboard, visual assets, and final video.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        state["thumbnail"] = ThumbnailAgent().generate(
            state["project_id"], state["topic"], registry, storyboard,
            final_video=final_video, project_dir=project_dir,
        )
        state["status"] = "completed"
    except Exception as exc:
        state["errors"].append(f"Thumbnail generation failed: {exc}")
        state["status"] = "failed"
    return state


def node_youtube_publish(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    final_video = state.get("final_video")
    thumbnail = state.get("thumbnail")
    if final_video is None or thumbnail is None:
        state["errors"].append("YouTube publishing requires a final video and thumbnail.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        state["youtube_publication"] = YouTubePublisher().publish(
            state["project_id"], state["topic"], final_video, thumbnail,
            script=state.get("script"), project_dir=project_dir,
        )
        state["status"] = "completed"
    except Exception as exc:
        state["errors"].append(f"YouTube publishing failed: {exc}")
        state["status"] = "failed"
    return state


def node_analytics(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    publication = state.get("youtube_publication")
    if publication is None:
        state["errors"].append("Analytics requires a YouTube publication.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        state["analytics"] = AnalyticsAgent().collect(publication, project_dir)
    except Exception as exc:
        state["errors"].append(f"Analytics collection failed: {exc}")
        state["status"] = "failed"
    return state


def node_feedback(state: VideoState) -> VideoState:
    state["status"] = "in_progress"
    history = state.get("analytics")
    if history is None:
        state["errors"].append("Feedback requires collected analytics.")
        state["status"] = "failed"
        return state
    try:
        project_dir = Path("projects") / state["project_id"]
        _, state["feedback"] = AnalyticsAgent().analyze(
            history, topic=state["topic"], script=state.get("script"),
            thumbnail=state.get("thumbnail"), duration_seconds=state.get("final_video").duration_seconds if state.get("final_video") else None,
            scene_count=state.get("final_video").scene_count if state.get("final_video") else None,
            asset_count=len(state.get("visual_assets").assets) if state.get("visual_assets") else None,
            project_dir=project_dir,
        )
        state["status"] = "completed"
    except Exception as exc:
        state["errors"].append(f"Feedback analysis failed: {exc}")
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
    workflow.add_node("visual_assets", node_visual_assets)
    workflow.add_node("render_scenes", node_render_scenes)
    workflow.add_node("compose_video", node_compose_video)
    workflow.add_node("thumbnail", node_thumbnail)
    workflow.add_node("youtube_publish", node_youtube_publish)
    workflow.add_node("analytics", node_analytics)
    workflow.add_node("feedback", node_feedback)
    workflow.add_node("render", node_render)
    workflow.add_node("compose", node_compose)

    workflow.add_edge(START, "start")
    workflow.add_edge("start", "research")
    workflow.add_edge("research", "fact_check")
    workflow.add_edge("fact_check", "script")
    workflow.add_edge("script", "storyboard")
    workflow.add_edge("storyboard", "tts")
    workflow.add_edge("tts", "visual_assets")
    workflow.add_edge("visual_assets", "render_scenes")
    workflow.add_edge("render_scenes", "compose_video")
    workflow.add_edge("compose_video", "thumbnail")
    workflow.add_edge("thumbnail", "youtube_publish")
    workflow.add_edge("youtube_publish", "analytics")
    workflow.add_edge("analytics", "feedback")
    workflow.add_edge("feedback", END)
    return workflow
