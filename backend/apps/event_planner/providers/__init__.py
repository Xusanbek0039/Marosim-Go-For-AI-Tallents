"""Provider registry. Tests install a fake with ``set_override`` (the real vendor is never called in tests)."""

from decimal import Decimal

from django.conf import settings

from .anthropic_provider import AnthropicProvider
from .base import ERRORS, BaseProvider, ProviderError, ProviderReply, ProviderRequest

_REGISTRY = {"anthropic": AnthropicProvider}
_override: BaseProvider | None = None


def set_override(provider: BaseProvider | None) -> None:
    global _override
    _override = provider


def get_provider(name: str) -> BaseProvider:
    if _override is not None:
        return _override
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ProviderError("ai_not_configured")
    return cls()


def is_configured(name: str) -> bool:
    try:
        return get_provider(name).is_configured()
    except ProviderError:
        return False


def estimated_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> Decimal | None:
    """Only when the provider reported usage *and* a price for the model is configured."""
    if input_tokens is None or output_tokens is None:
        return None
    price = settings.AI_PLANNER["PRICES_USD_PER_MTOK"].get(model)
    if not price:
        return None
    per_input, per_output = (Decimal(str(p)) for p in price)
    return ((Decimal(input_tokens) * per_input + Decimal(output_tokens) * per_output) / Decimal(1_000_000)).quantize(
        Decimal("0.000001")
    )


__all__ = [
    "ERRORS",
    "BaseProvider",
    "ProviderError",
    "ProviderReply",
    "ProviderRequest",
    "estimated_cost_usd",
    "get_provider",
    "is_configured",
    "set_override",
]
