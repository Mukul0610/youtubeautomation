from app.config import settings


def resolve_model_name(agent_name: str | None = None) -> str:
    agent_key = f"{agent_name}_model" if agent_name else "llm_model"
    if agent_name:
        configured = getattr(settings, f"{agent_name}_model", "")
        if configured:
            return configured
    return settings.llm_model


def get_provider() -> str:
    return settings.llm_provider
