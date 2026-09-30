"""Provider registration and model metadata."""

PROVIDERS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
}


def get_supported_providers() -> list[str]:
    return list(PROVIDERS.keys())
