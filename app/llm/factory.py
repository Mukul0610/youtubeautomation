from langchain_core.language_models import BaseChatModel

from app.config import settings
from app.llm.config import get_provider, resolve_model_name


def get_available_provider_names() -> list[str]:
    return ["openai", "anthropic", "gemini"]


def create_model(provider: str | None = None, model_name: str | None = None, *, agent_name: str | None = None) -> BaseChatModel:
    """Create a LangChain-compatible chat model using configuration.

    This is intentionally centralized so providers can be swapped without touching
    agents. If the provider is not available in the environment, the factory raises
    a clear ValueError instead of silently falling back to a broken runtime.
    """
    selected_provider = (provider or get_provider()).lower()
    resolved_model = model_name or resolve_model_name(agent_name)

    if not resolved_model:
        raise ValueError(
            "No model configured. Set LLM_MODEL or an agent-specific model variable such as RESEARCH_MODEL."
        )

    if selected_provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("langchain-openai is required for the OpenAI provider.") from exc

        return ChatOpenAI(model=resolved_model, temperature=0.2)

    if selected_provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("langchain-anthropic is required for the Anthropic provider.") from exc

        return ChatAnthropic(model=resolved_model, temperature=0.2)

    if selected_provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("langchain-google-genai is required for the Gemini provider.") from exc

        return ChatGoogleGenerativeAI(
            model=resolved_model,
            temperature=0.2,
            max_output_tokens=4096,
        )

    raise ValueError(f"Unsupported LLM provider: {selected_provider}")


__all__ = ["create_model", "get_available_provider_names"]
