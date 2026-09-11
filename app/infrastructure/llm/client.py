"""Which provider serves a given model, and how to reach it.

`get_client(model)` is the single construction point for every LLM client
in the app. Callers that used to write `AsyncAnthropic()` now write
`get_client(SOME_MODEL)` and are otherwise unchanged — the returned object
duck-types the Anthropic client either way (see `openai_compat`).

Switching models is a config change:

    LLM_CLAUDE_MODEL="deepseek-v4-flash"  # or any id in _PROVIDERS' prefixes
    DEEPSEEK_API_KEY=...

Routing is by model id prefix, so a run can mix providers — the risk judge
on one, the debate on another — without a global switch. `LLM_PROVIDER`
overrides the inference wholesale for the case a prefix cannot express:
an OpenAI-compatible gateway serving models under their original names.
When set to `openai-compatible`, point `LLM_BASE_URL` and `LLM_API_KEY` at
the gateway.

Adding a provider that speaks the OpenAI dialect is one entry in
`_PROVIDERS`. Adding one that does not means a new shim next to
`openai_compat.py` exposing the same `messages.create` surface.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic, BadRequestError

from app.infrastructure.llm.openai_compat import LLMBadRequestError, OpenAICompatClient

ANTHROPIC = "anthropic"

# What `get_client` hands back. Structural, not nominal: the ports accept
# an injected fake in tests and a real client in production, and the only
# contract any of them relies on is `.messages.create(**kwargs)`.
LLMClient = Any


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    api_key_env: str
    base_url: str
    # The provider's hard ceiling on output tokens per call. The shim clamps
    # to it rather than letting a request that asks for more 400 at the wire.
    # `None` means "no clamp" — the caller's number is sent as-is.
    max_output_tokens: int | None
    # Model-id prefixes that route here.
    prefixes: tuple[str, ...]
    base_url_env: str | None = None
    # extra_body key for this provider's reasoning toggle, or None when it
    # has none. Named rather than boolean because the shim has to write the
    # key, and because the next provider to add one will not call it
    # "thinking".
    thinking_param: str | None = None
    # Name of the output-token cap on the wire. OpenAI's GPT-5 family 400s
    # on `max_tokens` ("Use 'max_completion_tokens' instead"); DeepSeek
    # still takes the original name.
    max_tokens_param: str = "max_tokens"
    # Model-id prefixes that take a top-level `reasoning_effort` including
    # "none". OpenAI's counterpart to `thinking_param`, but scoped to models
    # rather than the provider: gpt-4.1 rejects the parameter outright and
    # the original gpt-5 has no "none".
    reasoning_effort_models: tuple[str, ...] = ()


_PROVIDERS: dict[str, ProviderSpec] = {
    ANTHROPIC: ProviderSpec(
        name=ANTHROPIC,
        api_key_env="ANTHROPIC_API_KEY",
        base_url="",
        max_output_tokens=None,
        prefixes=("claude-",),
    ),
    "deepseek": ProviderSpec(
        name="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        base_url_env="DEEPSEEK_BASE_URL",
        # 384K on both V4 models, against the research agent's 16000 — so
        # the clamp never fires today. Carried anyway rather than set to
        # None: it was 8192 on the retired deepseek-chat, which WOULD have
        # silently truncated the memo, and the next provider added here is
        # more likely to resemble that one than this one.
        max_output_tokens=384_000,
        prefixes=("deepseek",),
        thinking_param="thinking",
    ),
    "openai": ProviderSpec(
        name="openai",
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        base_url_env="OPENAI_BASE_URL",
        max_output_tokens=None,
        prefixes=("gpt-", "o1", "o3", "o4"),
        # Accepted by every current chat model, not just the GPT-5 family
        # that requires it, so it is safe provider-wide.
        max_tokens_param="max_completion_tokens",
        # Verified live on gpt-5.6-luna 2026-09-11: "none" accepted,
        # "minimal" rejected. Supported: none/low/medium/high/xhigh.
        reasoning_effort_models=("gpt-5.",),
    ),
    # Escape hatch: any endpoint speaking the OpenAI dialect, named
    # explicitly via LLM_PROVIDER because its model ids carry no prefix
    # this table could match on.
    "openai-compatible": ProviderSpec(
        name="openai-compatible",
        api_key_env="LLM_API_KEY",
        base_url="",
        base_url_env="LLM_BASE_URL",
        max_output_tokens=None,
        prefixes=(),
    ),
}


class ProviderNotConfigured(RuntimeError):
    """Raised at construction, not at the first API call.

    Deliberate: a missing key that surfaces as a 401 thirty turns into a
    run has already cost real money, and reads like a model problem rather
    than a config problem.
    """


def resolve_provider(model: str | None) -> ProviderSpec:
    override = os.getenv("LLM_PROVIDER")
    if override:
        if override not in _PROVIDERS:
            raise ProviderNotConfigured(
                f"LLM_PROVIDER={override!r} is not a known provider "
                f"({', '.join(sorted(_PROVIDERS))})"
            )
        return _PROVIDERS[override]

    if model:
        for spec in _PROVIDERS.values():
            if spec.prefixes and model.startswith(spec.prefixes):
                return spec

    # Anthropic stays the default so an unset/unknown model behaves exactly
    # as it did before this layer existed.
    return _PROVIDERS[ANTHROPIC]


class RoutingClient:
    """One client object that picks the provider per request.

    Needed because `run_synthesis` threads a SINGLE client through two roles
    that read two different model env vars (Research Manager and Risk Judge).
    Before provider routing existed that was free — every model was
    Anthropic. Now a shared client would send whichever of the two is not
    Anthropic to the wrong API, so the shared object dispatches on the
    `model` of each call instead of being bound to one at construction.

    Sub-clients are built lazily and kept for the life of this object, so a
    caller that shares it across samples still shares a connection pool per
    provider — which is why nodes.py constructed one client in the first
    place.
    """

    def __init__(self) -> None:
        self._by_model: dict[str, Any] = {}
        self.messages = _RoutingMessages(self)

    def _for(self, model: str | None):
        key = model or ""
        if key not in self._by_model:
            # `key`, never `model`: get_client(None) would hand back
            # another RoutingClient and recurse. The empty string falls
            # through prefix matching to the default provider, which is
            # the same answer without the loop.
            self._by_model[key] = get_client(key)
        return self._by_model[key]


class _RoutingMessages:
    def __init__(self, owner: RoutingClient) -> None:
        self._owner = owner

    async def create(self, **kwargs: Any):
        return await self._owner._for(kwargs.get("model")).messages.create(**kwargs)


def get_client(model: str | None = None, *, api_key: str | None = None):
    """The client for `model`. Duck-types `anthropic.AsyncAnthropic`.

    Called with no model, returns a `RoutingClient` that resolves the
    provider per request — for the callers that share one client across
    calls that do not all use the same model.
    """
    if model is None and not os.getenv("LLM_PROVIDER"):
        return RoutingClient()

    spec = resolve_provider(model)
    key = api_key or os.getenv(spec.api_key_env)

    if spec.name == ANTHROPIC:
        # Left to the SDK's own env handling when unset, which is what the
        # bare `AsyncAnthropic()` calls this replaced relied on.
        return AsyncAnthropic(api_key=key) if key else AsyncAnthropic()

    if not key:
        raise ProviderNotConfigured(
            f"model {model!r} routes to provider {spec.name!r}, which needs "
            f"{spec.api_key_env} in the environment"
        )

    base_url = (spec.base_url_env and os.getenv(spec.base_url_env)) or spec.base_url
    if not base_url:
        raise ProviderNotConfigured(
            f"provider {spec.name!r} needs a base URL — set {spec.base_url_env}"
        )

    return OpenAICompatClient(
        api_key=key,
        base_url=base_url,
        max_output_tokens=spec.max_output_tokens,
        provider=spec.name,
        thinking_param=spec.thinking_param,
        max_tokens_param=spec.max_tokens_param,
        reasoning_effort_models=spec.reasoning_effort_models,
    )


def is_anthropic(model: str | None) -> bool:
    return resolve_provider(model).name == ANTHROPIC


def _rejects_temperature(message: str) -> bool:
    """Whether a 400's message is a model refusing `temperature` itself.

    Anthropic (claude-sonnet-5): "temperature is deprecated for this model".
    OpenAI (gpt-5.6-luna with reasoning on, 2026-09-11): "Unsupported value:
    'temperature' does not support 0.2 with this model. Only the default (1)
    value is supported."
    """
    message = message.lower()
    return "temperature" in message and ("deprecated" in message or "unsupported" in message)


async def create_with_temperature_fallback(client: LLMClient, **kwargs):
    """`client.messages.create(**kwargs)`, but if the model rejects
    `temperature` outright, retry once without it.

    Found live (2026-08-25, running the Phase 6 determinism check against
    claude-sonnet-5 as Risk Judge/Research Manager): `temperature=0.0` 400s
    with "temperature is deprecated for this model" — not merely ignored,
    REJECTED. Haiku 4.5 (this project's RISK_MODEL) accepted the identical
    parameter on the same run; whether a given model still honors
    `temperature` is therefore a live API fact, not something safe to
    special-case from a hardcoded model list that goes stale the moment a
    new model ships. GPT-5.x rejects it too, in different words, whenever
    reasoning is on (see `_translate_reasoning_effort`).

    Reacting to the API's own error is the general fix, but it changes what
    a determinism/stability claim MEANS for a model like this: there is no
    lever left to set, so "replayed at temperature=0" silently becomes
    "replayed at whatever this model's fixed default is" — printed loudly
    here specifically so that distinction is never silently absorbed into a
    passing check.
    """
    try:
        return await client.messages.create(**kwargs)
    except (BadRequestError, LLMBadRequestError) as e:
        if "temperature" in kwargs and _rejects_temperature(str(e)):
            print(
                f"[reasoning_config] {kwargs.get('model')} rejects `temperature` "
                f"— retrying without it. Any determinism/stability claim for "
                f"this call no longer rests on a temperature lever, only on the "
                f"model's own fixed default."
            )
            kwargs = {k: v for k, v in kwargs.items() if k != "temperature"}
            return await client.messages.create(**kwargs)
        raise


__all__ = [
    "LLMBadRequestError",
    "LLMClient",
    "RoutingClient",
    "ProviderNotConfigured",
    "ProviderSpec",
    "create_with_temperature_fallback",
    "get_client",
    "is_anthropic",
    "resolve_provider",
]
