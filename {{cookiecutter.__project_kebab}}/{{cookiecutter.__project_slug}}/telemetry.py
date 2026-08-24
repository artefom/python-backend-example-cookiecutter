"""
OpenTelemetry tracing setup.

Tracing is instrumented, but **no span exporter is configured** — spans are
created (giving every request a valid, sampled trace/span id) and then dropped.
The point today is not to ship traces anywhere but to make those ids available
so they can be stamped onto our structured logs (see ``slog.py``), which lets us
group all log lines of a single request.

To start exporting later, attach a ``BatchSpanProcessor`` to the provider, e.g.:

    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

(add the ``opentelemetry-exporter-otlp`` dependency for that).

Outbound propagation allowlist
------------------------------

Trace ids are internal correlation ids, so we do not hand them to arbitrary
destinations. ``TRACE_PROPAGATION_ALLOWLIST`` (see ``propagation_allowed``)
restricts which hosts receive the ``traceparent``/``tracestate``/``baggage``
headers on outbound requests. Left unset it allows everything, which is the
behaviour you get without any configuration.

When a destination is not allowlisted we still record the client span and its
metrics — only the headers are withheld. The downstream therefore starts its own
trace instead of continuing ours, which is the whole point: our call is still
observable on our side, and nothing internal leaks to them.
"""

import logging
import os
from contextvars import ContextVar
from functools import lru_cache
from types import SimpleNamespace

import aiohttp
from fastapi import FastAPI
from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.propagators.textmap import (
    CarrierT,
    Getter,
    Setter,
    TextMapPropagator,
    default_getter,
    default_setter,
)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from yarl import URL

logger = logging.getLogger(__name__)

SERVICE = "{{cookiecutter.__project_kebab}}"

TRACE_PROPAGATION_ALLOWLIST_ENV = "TRACE_PROPAGATION_ALLOWLIST"

# Guard so the global provider is only registered once per process, regardless
# of how the app is launched (CLI runner vs. uvicorn --factory).
_provider_configured = False

# Set by the gate TraceConfig below for the duration of a single outbound request
# whose destination must not receive our trace headers, and read by
# _AllowlistPropagator.inject.
#
# This is deliberately our own ContextVar rather than a value in OpenTelemetry's
# context: our TraceConfig hooks run *before* the instrumentation's on every
# aiohttp signal, so we would also detach first, out of order with the span
# context the instrumentation attaches on top of ours. On the shared OTel context
# var that leaves the flag set for the rest of the task, silently withholding the
# header from every later call in the same request.
_propagation_blocked: ContextVar[bool] = ContextVar(
    "trace_propagation_blocked", default=False
)

# Everything the default global propagator (tracecontext + baggage) can write.
_TRACE_HEADERS = ("traceparent", "tracestate", "baggage")


@lru_cache(maxsize=16)
def _parse_allowlist(raw: str) -> tuple[str, ...]:
    """
    Normalise the raw ``TRACE_PROPAGATION_ALLOWLIST`` value into host patterns.

    Cached on the raw value so the split/strip work happens once per distinct
    setting rather than on every outbound request.
    """
    return tuple(
        entry.rstrip(".")
        for entry in (part.strip().lower() for part in raw.split(","))
        if entry
    )


def propagation_allowed(host: str | None) -> bool:
    """
    Whether the trace headers may be forwarded to ``host``.

    ``TRACE_PROPAGATION_ALLOWLIST`` is a comma-separated, case-insensitive list of
    hosts. Ports are ignored — match on the host only. An entry starting with a
    dot matches that domain and any subdomain (``.example.com`` matches both
    ``example.com`` and ``api.example.com``); any other entry must match exactly.

    An unset/empty list — or a single ``*`` — allows every destination, so trace
    context propagates everywhere unless the allowlist is explicitly configured.
    """
    patterns = _parse_allowlist(os.environ.get(TRACE_PROPAGATION_ALLOWLIST_ENV, ""))
    if not patterns or "*" in patterns:
        return True
    if not host:
        # No host to check (e.g. a unix-socket connector) and an allowlist is in
        # force, so we cannot claim the destination is trusted.
        return False

    host = host.strip().rstrip(".").lower()
    return any(
        host == pattern[1:] or host.endswith(pattern)
        if pattern.startswith(".")
        else host == pattern
        for pattern in patterns
    )


class _AllowlistPropagator(TextMapPropagator):
    """
    Wraps the global propagator to withhold injection for non-allowlisted hosts.

    Only ``inject`` is gated, and only while ``_propagation_blocked`` is set for
    the current outbound request. Extraction of inbound context is untouched, so
    we still join traces started by our callers.
    """

    def __init__(self, wrapped: TextMapPropagator) -> None:
        self._wrapped = wrapped

    def inject(
        self,
        carrier: CarrierT,
        context: Context | None = None,
        setter: Setter[CarrierT] = default_setter,
    ) -> None:
        if _propagation_blocked.get():
            return
        self._wrapped.inject(carrier, context, setter)

    def extract(
        self,
        carrier: CarrierT,
        context: Context | None = None,
        getter: Getter[CarrierT] = default_getter,
    ) -> Context:
        return self._wrapped.extract(carrier, context, getter)

    @property
    def fields(self) -> set[str]:
        return self._wrapped.fields


def _allowlist_trace_config() -> aiohttp.TraceConfig:
    """
    An aiohttp TraceConfig that flags non-allowlisted destinations.

    Registered ahead of the instrumentation's own config, so it runs before the
    ``inject()`` at the end of its ``on_request_start`` and can suppress it.
    """

    async def request_start(
        _session: aiohttp.ClientSession,
        ctx: SimpleNamespace,
        params: aiohttp.TraceRequestStartParams,
    ) -> None:
        # Each TraceConfig gets its own per-request SimpleNamespace, so this
        # attribute cannot collide with the instrumentation's own state.
        ctx.propagation_token = (
            None
            if propagation_allowed(params.url.host)
            else _propagation_blocked.set(True)
        )

    async def request_finished(
        _session: aiohttp.ClientSession,
        ctx: SimpleNamespace,
        _params: object,
    ) -> None:
        token = getattr(ctx, "propagation_token", None)
        if token is not None:
            _propagation_blocked.reset(token)
            ctx.propagation_token = None

    async def request_redirect(
        _session: aiohttp.ClientSession,
        _ctx: SimpleNamespace,
        params: aiohttp.TraceRequestRedirectParams,
    ) -> None:
        # on_request_start fires only once, before aiohttp's redirect loop, and
        # the same headers are reused for the redirected request — so an
        # allowlisted host redirecting elsewhere would carry our trace context to
        # a destination we never approved.
        location = params.response.headers.get("Location")
        if location is None:
            return
        target = params.url.join(URL(location))
        if not propagation_allowed(target.host):
            for header in _TRACE_HEADERS:
                params.headers.pop(header, None)

    trace_config = aiohttp.TraceConfig()
    trace_config.on_request_start.append(request_start)
    trace_config.on_request_redirect.append(request_redirect)
    trace_config.on_request_end.append(request_finished)
    trace_config.on_request_exception.append(request_finished)
    return trace_config


def _ensure_provider() -> None:
    global _provider_configured
    if _provider_configured:
        return

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: SERVICE}))
    # Intentionally no SpanProcessor/exporter: spans are recorded with valid
    # trace/span ids (default ParentBased(ALWAYS_ON) sampler) but never exported.
    trace.set_tracer_provider(provider)

    # Gate outbound trace headers on TRACE_PROPAGATION_ALLOWLIST. Wrapping the
    # global propagator covers every injection point, not just aiohttp's.
    propagate.set_global_textmap(_AllowlistPropagator(propagate.get_global_textmap()))

    # Propagate trace context into outbound aiohttp client requests: each call
    # opens a child span and injects the W3C `traceparent` header, so downstream
    # services continue the same trace. This is process-global (patches every
    # ClientSession) and self-skips if aiohttp is not installed.
    AioHttpClientInstrumentor().instrument(
        trace_configs=[_allowlist_trace_config()],
    )

    _provider_configured = True
    logger.debug("OpenTelemetry tracing configured (no exporter)")


def setup_tracing(app: FastAPI) -> None:
    """Configure the global tracer provider (once) and instrument ``app`` so a
    span is opened per HTTP request."""
    _ensure_provider()
    FastAPIInstrumentor.instrument_app(app, tracer_provider=trace.get_tracer_provider())
