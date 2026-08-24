"""
Example unit tests file
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from aiohttp.test_utils import TestServer
from fastapi import FastAPI, Response
from fastapi.routing import APIRouter
from httpx import AsyncClient

from {{cookiecutter.__project_slug}}.api.spec import ApiSection
from {{cookiecutter.__project_slug}}.testing_utils import JsonLogs


@asynccontextmanager
async def _header_recording_server() -> AsyncIterator[
    tuple[TestServer, dict[str, str]]
]:
    """A local server that records the headers of every request it receives.

    Yields the server and the (mutable) dict of headers from the last request, so
    tests can assert on what the outbound call actually carried.
    """
    from aiohttp import web

    received: dict[str, str] = {}

    async def handler(request: web.Request) -> web.Response:
        received.update(request.headers)
        return web.json_response({"headers": dict(request.headers)})

    server_app = web.Application()
    server_app.router.add_get("/", handler)
    server = TestServer(server_app)
    await server.start_server()
    try:
        yield server, received
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_unhandled_exception_logs_request_id(
    app: FastAPI,
    client: AsyncClient,
    structured_logs_capture: JsonLogs,
) -> None:
    async def boom() -> Response:
        raise RuntimeError("boom")

    router = APIRouter()
    ApiSection(router, "/boom", "test").register("GET", "", boom)
    app.include_router(router)

    request_id = "test-request-id-123"
    response = await client.get("/boom", headers={"X-Request-ID": request_id})

    assert response.status_code == 500

    logs = structured_logs_capture.parse()
    error_log = next(
        (
            line
            for line in logs
            if "Unhandled exception occurred" in line.get("message", "")
        ),
        None,
    )
    assert error_log is not None, "Expected 'Unhandled exception occurred' log entry"
    assert error_log["x_request_id"] == request_id


@pytest.mark.asyncio
async def test_app_is_instrumented(app: FastAPI) -> None:
    # FastAPIInstrumentor.instrument_app stamps this flag on the app.
    assert getattr(app, "_is_instrumented_by_opentelemetry", False) is True


@pytest.mark.asyncio
async def test_request_log_carries_trace_context(
    client: AsyncClient,
    structured_logs_capture: JsonLogs,
) -> None:
    response = await client.get("/ping", params={"value": "hi"})
    assert response.status_code == 200

    logs = structured_logs_capture.parse()
    access_log = next((line for line in logs if "httpRequest" in line), None)
    assert access_log is not None, "Expected an access log line with httpRequest"
    # The per-request span must be active while the access log is emitted.
    assert "logging.googleapis.com/trace" in access_log
    assert "logging.googleapis.com/spanId" in access_log


@pytest.mark.asyncio
async def test_outbound_aiohttp_carries_traceparent(app: FastAPI) -> None:
    # Depending on `app` ensures make_app() -> setup_tracing() has run, which
    # registers the SDK provider and instruments the aiohttp client globally.
    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    from opentelemetry import trace

    received: dict[str, str] = {}

    async def handler(request: web.Request) -> web.Response:
        received.update(request.headers)
        return web.Response(text="ok")

    server_app = web.Application()
    server_app.router.add_get("/", handler)
    server = TestServer(server_app)
    await server.start_server()
    try:
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("client-parent") as span:
            trace_id = format(span.get_span_context().trace_id, "032x")
            async with (
                aiohttp.ClientSession() as session,
                session.get(server.make_url("/")) as resp,
            ):
                assert resp.status == 200
    finally:
        await server.close()

    # The outbound request carried the active trace context as a W3C header.
    assert "traceparent" in received, received
    assert trace_id in received["traceparent"]


@pytest.mark.asyncio
async def test_trace_demo_reports_propagated_headers(client: AsyncClient) -> None:
    response = await client.get("/trace-demo")
    assert response.status_code == 200

    body = response.json()
    # The endpoint reports the live server-span trace id...
    assert body["trace_id"] != "0" * 32
    # ...and the traceparent it would propagate embeds that same trace id.
    assert "traceparent" in body["propagated_headers"]
    assert body["trace_id"] in body["propagated_headers"]["traceparent"]
    assert body["downstream_status"] is None


@pytest.mark.asyncio
async def test_trace_demo_downstream_receives_traceparent(client: AsyncClient) -> None:
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    async def echo_headers(request: web.Request) -> web.Response:
        return web.json_response({"headers": dict(request.headers)})

    downstream = web.Application()
    downstream.router.add_get("/", echo_headers)
    server = TestServer(downstream)
    await server.start_server()
    try:
        response = await client.get(
            "/trace-demo", params={"url": str(server.make_url("/"))}
        )
    finally:
        await server.close()

    assert response.status_code == 200
    body = response.json()
    assert body["downstream_status"] == 200
    # The downstream actually received the traceparent, carrying the same trace.
    received = body["downstream_body"]["headers"]
    assert "Traceparent" in received or "traceparent" in received
    traceparent = received.get("Traceparent") or received.get("traceparent")
    assert body["trace_id"] in traceparent


@pytest.mark.asyncio
async def test_outbound_traceparent_withheld_for_non_allowlisted_host(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aiohttp
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from {{cookiecutter.__project_slug}}.telemetry import TRACE_PROPAGATION_ALLOWLIST_ENV

    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, "api.partner.com")

    # The allowlist withholds the header but must NOT cost us the client span,
    # so capture spans to prove the call is still observable on our side.
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)

    try:
        async with (
            _header_recording_server() as (server, received),
            aiohttp.ClientSession() as session,
            session.get(server.make_url("/")) as resp,
        ):
            assert resp.status == 200
    finally:
        processor.shutdown()

    assert "traceparent" not in received, received
    assert "tracestate" not in received, received

    client_spans = [
        span
        for span in exporter.get_finished_spans()
        if span.kind is trace.SpanKind.CLIENT
    ]
    assert client_spans, "the outbound client span must still be recorded"


@pytest.mark.asyncio
async def test_outbound_traceparent_forwarded_for_allowlisted_host(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aiohttp
    from opentelemetry import trace

    from {{cookiecutter.__project_slug}}.telemetry import TRACE_PROPAGATION_ALLOWLIST_ENV

    # TestServer binds 127.0.0.1; ports are ignored by the matcher.
    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, "127.0.0.1")

    async with _header_recording_server() as (server, received):
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("client-parent") as span:
            trace_id = format(span.get_span_context().trace_id, "032x")
            async with (
                aiohttp.ClientSession() as session,
                session.get(server.make_url("/")) as resp,
            ):
                assert resp.status == 200

    assert "traceparent" in received, received
    assert trace_id in received["traceparent"]


@pytest.mark.asyncio
async def test_blocked_call_does_not_leak_into_later_allowlisted_call(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A withheld call must not disable propagation for the rest of the task."""
    import aiohttp
    from opentelemetry import trace

    from {{cookiecutter.__project_slug}}.telemetry import TRACE_PROPAGATION_ALLOWLIST_ENV

    # 127.0.0.1 is allowlisted, localhost is not — same server, two host spellings.
    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, "127.0.0.1")

    async with _header_recording_server() as (server, received):
        blocked_url = server.make_url("/").with_host("localhost")
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("client-parent"):
            async with aiohttp.ClientSession() as session:
                async with session.get(blocked_url) as resp:
                    assert resp.status == 200
                assert "traceparent" not in received, received

                received.clear()
                async with session.get(server.make_url("/")) as resp:
                    assert resp.status == 200

    assert "traceparent" in received, received


@pytest.mark.asyncio
async def test_redirect_to_non_allowlisted_host_drops_traceparent(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """aiohttp reuses the injected headers across redirects, so the redirect
    target has to be re-checked against the allowlist."""
    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    from {{cookiecutter.__project_slug}}.telemetry import TRACE_PROPAGATION_ALLOWLIST_ENV

    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, "127.0.0.1")

    received: dict[str, str] = {}

    async def final(request: web.Request) -> web.Response:
        received.update(request.headers)
        return web.Response(text="ok")

    async def redirect(request: web.Request) -> web.Response:
        # Same server, but the host spelling that is *not* allowlisted.
        target = request.url.with_host("localhost").with_path("/final")
        raise web.HTTPFound(location=str(target))

    server_app = web.Application()
    server_app.router.add_get("/final", final)
    server_app.router.add_get("/redirect", redirect)
    server = TestServer(server_app)
    await server.start_server()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(server.make_url("/redirect")) as resp,
        ):
            assert resp.status == 200
    finally:
        await server.close()

    assert "traceparent" not in received, received


@pytest.mark.asyncio
async def test_trace_demo_reports_traceparent_withheld(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from {{cookiecutter.__project_slug}}.telemetry import TRACE_PROPAGATION_ALLOWLIST_ENV

    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, "api.partner.com")

    async with _header_recording_server() as (server, _received):
        response = await client.get(
            "/trace-demo", params={"url": str(server.make_url("/"))}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["downstream_status"] == 200
    assert body["downstream_traceparent_forwarded"] is False


@pytest.mark.asyncio
async def test_trace_demo_reports_traceparent_forwarded(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from {{cookiecutter.__project_slug}}.telemetry import TRACE_PROPAGATION_ALLOWLIST_ENV

    monkeypatch.setenv(TRACE_PROPAGATION_ALLOWLIST_ENV, "127.0.0.1")

    async with _header_recording_server() as (server, received):
        response = await client.get(
            "/trace-demo", params={"url": str(server.make_url("/"))}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["downstream_traceparent_forwarded"] is True
    assert body["trace_id"] in received["traceparent"]


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_index(client: AsyncClient) -> None:
    response = await client.get("/docs")
    assert response.status_code == 200
