"""
Server entry-point with FastAPI app defined
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import aiohttp
import fastapi
import uvicorn
import uvloop
from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse
from opentelemetry import propagate, trace
from pydantic import BaseModel
from starlette_exporter import handle_metrics
from starlette_exporter.middleware import PrometheusMiddleware

from {{cookiecutter.__project_slug}}.api import api_router
from {{cookiecutter.__project_slug}}.api.spec import register_default_exception_handler
from {{cookiecutter.__project_slug}}.telemetry import propagation_allowed, setup_tracing
from {{cookiecutter.__project_slug}}.tracking import TrackingMiddleware

logger = logging.getLogger(__name__)


class TraceDemoResponse(BaseModel):
    """Diagnostic view of the current trace and what gets propagated."""

    # The active server span for this request. This same trace_id is stamped
    # onto the request's GCP log line (logging.googleapis.com/trace).
    trace_id: str
    span_id: str
    sampled: bool
    # The headers an outbound request carries, produced by the same propagator
    # the aiohttp client instrumentation uses. Contains `traceparent`.
    propagated_headers: dict[str, str]
    # Populated only when `url` is supplied: the result of a real outbound
    # aiohttp call. Point it at a header-echo service (e.g.
    # https://httpbin.org/headers) to see the traceparent the downstream saw.
    downstream_status: int | None = None
    downstream_body: Any | None = None
    downstream_error: str | None = None
    # Whether the outbound call was allowed to carry the trace headers, i.e.
    # whether the host passed TRACE_PROPAGATION_ALLOWLIST (see telemetry.py).
    downstream_traceparent_forwarded: bool | None = None


async def trace_demo(url: str | None = None) -> TraceDemoResponse:
    """Show the live trace context and the trace headers being propagated"""
    span_context = trace.get_current_span().get_span_context()

    # inject() writes the active trace context into the given carrier exactly
    # as the aiohttp client instrumentation does before sending a request.
    propagated_headers: dict[str, str] = {}
    propagate.inject(propagated_headers)

    response = TraceDemoResponse(
        trace_id=format(span_context.trace_id, "032x"),
        span_id=format(span_context.span_id, "016x"),
        sampled=span_context.trace_flags.sampled,
        propagated_headers=propagated_headers,
    )

    if url:
        # Report the allowlist decision up front so it is visible even when the
        # call itself fails.
        response.downstream_traceparent_forwarded = propagation_allowed(
            urlparse(url).hostname
        )

        # A real outbound call: the aiohttp instrumentation opens a child span
        # and injects `traceparent` into the request automatically — unless the
        # host is not allowlisted, in which case the headers are withheld.
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(url) as downstream,
            ):
                response.downstream_status = downstream.status
                try:
                    response.downstream_body = await downstream.json()
                except aiohttp.ContentTypeError:
                    response.downstream_body = (await downstream.text())[:2000]
        except Exception as exc:  # noqa: BLE001 - diagnostic endpoint, report any error
            response.downstream_error = f"{type(exc).__name__}: {exc}"

    return response


def make_app(root_path: str) -> FastAPI:

    app = FastAPI(root_path=root_path)

    # Enable context based tracking
    app.add_middleware(TrackingMiddleware)

    # WARNING: The order of the middleware is important.
    # PrometheusMiddleware is added after TrackingMiddleware so it wraps (and
    # measures) it. setup_tracing() below then wraps the whole stack in an even
    # outer OpenTelemetry middleware (see the note on that call), so the request
    # span is active across both of these — that is what lets TrackingMiddleware's
    # access log carry the trace context. Prometheus therefore excludes only the
    # OTel middleware's own (sub-millisecond) overhead, well below its buckets.
    app.add_middleware(
        PrometheusMiddleware,
        filter_unhandled_paths=True,
        group_paths=True,
        app_name="{{cookiecutter.__project_kebab}}",
        buckets=[0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5]
        + [0.75, 1.0, 2.5, 5.0, 7.5, 10.0],
        skip_paths=[
            f"{root_path}{path}"
            for path in ["/health", "/metrics", "/", "/docs", "/openapi.json"]
        ],
    )

    # Instrument the app with OpenTelemetry tracing. instrument_app overrides
    # build_middleware_stack to wrap the *entire* user middleware stack in the
    # OTel middleware, so the request span is outermost and active for all other
    # middleware regardless of where this is called relative to add_middleware.
    setup_tracing(app)

    app.add_route("/metrics", handle_metrics)

    async def health() -> fastapi.Response:
        """Checks health of application, including database and all systems"""
        return fastapi.Response("OK")

    async def index(request: Request) -> RedirectResponse:
        # the redirect must be absolute (start with /) because
        # it needs to handle both trailing slash and no trailing slash
        # /app -> /app/docs
        # /app/ -> /app/docs
        return RedirectResponse(f"{str(request.base_url).rstrip('/')}/docs")

    app.add_api_route("/health", health, methods=["get"], include_in_schema=False)
    app.add_api_route("/", index, methods=["get"], include_in_schema=False)

    # Diagnostic endpoint to observe tracing in action (visible in /docs).
    app.add_api_route("/trace-demo", trace_demo, methods=["get"], tags=["telemetry"])

    app.include_router(api_router())

    register_default_exception_handler(app)

    app.openapi_schema = get_openapi(
        title="{{cookiecutter.project_name}}",
        version="0.1.0",
        description="{{cookiecutter.description}}",
        routes=app.routes,
    )
    app.openapi_schema["servers"] = [{"url": app.root_path}]

    return app


@dataclass
class AppSettings:
    host: str
    port: int
    root_path: str


async def _main_async(settings: AppSettings):
    app = make_app(settings.root_path)
    config = uvicorn.Config(
        app,
        settings.host,
        settings.port,
        log_config=None,
        access_log=False,
    )
    api_server = uvicorn.Server(config)
    logger.info("Serving on http://%s:%s", settings.host, settings.port)
    await api_server.serve()


def main(settings: AppSettings):
    uvloop.install()
    asyncio.run(_main_async(settings))
