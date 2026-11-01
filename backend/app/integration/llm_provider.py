"""Explicit reasoning-provider selection; scientific tools always stay on Nebius."""

from .anthropic_llm import AnthropicLLMProvider
from .nebius_llm import NebiusLLMProvider


def requested_provider(settings, request):
    if request.workflow == "preparation":
        return None
    if request.use_llm:
        return request.llm_provider or settings.agent_llm_provider
    # Preserve the original explicit Nebius opt-in contract.
    return "nebius" if request.use_nebius_llm else None


def configured_provider(settings):
    return (
        AnthropicLLMProvider(settings)
        if settings.agent_llm_provider == "anthropic"
        else NebiusLLMProvider(settings)
    )
