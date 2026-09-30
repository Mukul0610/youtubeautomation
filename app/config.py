import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self) -> None:
        self.reload()

    def reload(self) -> "Settings":
        self.llm_provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self.llm_model = os.getenv("LLM_MODEL", "")
        self.research_model = os.getenv("RESEARCH_MODEL", "")
        self.factcheck_model = os.getenv("FACTCHECK_MODEL", "")
        self.script_model = os.getenv("SCRIPT_MODEL", "")
        self.storyboard_model = os.getenv("STORYBOARD_MODEL", "")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.google_api_key = os.getenv("GOOGLE_API_KEY", "")
        self.tts_provider = os.getenv("TTS_PROVIDER", "")
        self.tts_model = os.getenv("TTS_MODEL", "")
        self.tts_voice = os.getenv("TTS_VOICE", "default")
        self.tts_language = os.getenv("TTS_LANGUAGE", "en")
        self.tts_speed = float(os.getenv("TTS_SPEED", "1.0"))
        self.tts_api_key = os.getenv("TTS_API_KEY", "")
        self.sarvam_api_key = os.getenv("SARVAM_API_KEY", "")
        self.auto_approve = os.getenv("AUTO_APPROVE", "true").strip().lower() in {"1", "true", "yes", "on"}
        return self


settings = Settings()
