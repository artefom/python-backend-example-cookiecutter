"""
OpenTelemetry tracing setup. Spans are always recorded so their ids can be
stamped onto log lines; export happens only when an endpoint is configured.
Supports any OLTP collector. Currently only GCP/Newrelic are in scope.
"""

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

logger = logging.getLogger(__name__)

GOOGLE_ENDPOINT_DOMAIN = "googleapis.com"


@dataclass(frozen=True)
class TraceSettings:
    service_name: str

    environment: str | None = None

    # OTLP/gRPC endpoint spans are shipped to (if set)
    otlp_endpoint: str | None = None

    otlp_headers: str | None = None

    # Only needed when sending to gcp.
    gcp_project_id: str | None = None


_provider_installed = False


def _build_resource(settings: TraceSettings) -> Resource:
    attributes: dict[str, str] = {SERVICE_NAME: settings.service_name}
    if settings.environment:
        attributes["deployment.environment.name"] = settings.environment
    if settings.gcp_project_id:
        attributes["gcp.project_id"] = settings.gcp_project_id
    return Resource.create(attributes)


def parse_headers(headers: str | None) -> dict[str, str]:
    """``"a=1,b=2"`` -> ``{"a": "1", "b": "2"}``; blanks are ignored."""
    parsed: dict[str, str] = {}
    for pair in (headers or "").split(","):
        if not pair.strip():
            continue
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"OTLP header {pair!r} is not of the form key=value")
        parsed[key.strip()] = value.strip()
    return parsed


def is_google_endpoint(endpoint: str) -> bool:
    host = (urlparse(endpoint).hostname or "").lower()
    return host == GOOGLE_ENDPOINT_DOMAIN or host.endswith(f".{GOOGLE_ENDPOINT_DOMAIN}")


def _google_channel_credentials(project_id: str | None):
    import google.auth
    import google.auth.transport.requests
    import grpc
    from google.auth.transport.grpc import AuthMetadataPlugin

    credentials, _ = google.auth.default(quota_project_id=project_id)
    auth_plugin = AuthMetadataPlugin(
        credentials=credentials, request=google.auth.transport.requests.Request()
    )
    return grpc.composite_channel_credentials(
        grpc.ssl_channel_credentials(),
        grpc.metadata_call_credentials(auth_plugin),
    )


def build_exporter(settings: TraceSettings) -> SpanExporter | None:
    """
    The OTLP exporter described by ``settings``, or ``None`` when no endpoint is
    configured. A Google endpoint additionally gets OAuth channel credentials,
    and yields ``None`` when none can be found.
    """
    if not settings.otlp_endpoint:
        return None

    headers = parse_headers(settings.otlp_headers)
    if is_google_endpoint(settings.otlp_endpoint):
        from google.auth.exceptions import DefaultCredentialsError

        try:
            credentials = _google_channel_credentials(settings.gcp_project_id)
        except DefaultCredentialsError:
            logger.warning(
                "No Google credentials found; spans will not be exported to %s",
                settings.otlp_endpoint,
            )
            return None
        return OTLPSpanExporter(
            endpoint=settings.otlp_endpoint,
            credentials=credentials,
            headers=headers,
        )
    return OTLPSpanExporter(endpoint=settings.otlp_endpoint, headers=headers)


def configure(settings: TraceSettings) -> None:
    """
    Install the tracer provider, the exporter (if configured) and instrument
    outgoing aiohttp requests.
    Safe to call more than once; only the first call has an effect.
    """
    global _provider_installed

    if _provider_installed:
        return

    provider = TracerProvider(resource=_build_resource(settings))

    exporter = build_exporter(settings)
    if exporter is not None:
        # Batched off the request path; the provider flushes it on shutdown.
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info("Exporting spans over OTLP to %s", settings.otlp_endpoint)
    else:
        logger.info("Spans are not exported; they are recorded for logs only")

    trace.set_tracer_provider(provider)
    AioHttpClientInstrumentor().instrument()

    _provider_installed = True
    logger.debug("OpenTelemetry tracing configured")


def instrument_app(app: FastAPI, excluded_urls: str = "health,metrics") -> None:
    """
    Create a span for every incoming request handled by ``app``
    """
    FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded_urls)
