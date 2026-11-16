"""
Tests for tracing setup and trace-context propagation
"""

import re
from collections.abc import AsyncGenerator

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer
from opentelemetry import trace

from . import tracing
from .tracing import TraceSettings

# W3C traceparent: version-traceid-spanid-flags
_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")

async_test = pytest.mark.asyncio(loop_scope="module")


class _RecordingServer:
    """Local HTTP server that records the headers of the last request."""

    def __init__(self) -> None:
        self.received: dict[str, str] = {}
        app = web.Application()
        app.router.add_get("/ok", self._ok)
        self.server = TestServer(app, host="127.0.0.1")

    def url(self, path: str) -> str:
        return str(self.server.make_url(path))

    async def _ok(self, request: web.Request) -> web.Response:
        self.received = dict(request.headers)
        return web.Response(text="ok")


@pytest_asyncio.fixture()
async def server() -> AsyncGenerator[_RecordingServer]:
    recording = _RecordingServer()
    await recording.server.start_server()
    try:
        yield recording
    finally:
        await recording.server.close()


@pytest_asyncio.fixture()
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    tracing.configure(TraceSettings("tracing-test"))
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@async_test
async def test_traceparent_injected(
    server: _RecordingServer, session: aiohttp.ClientSession
):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("parent") as parent:
        async with session.get(server.url("/ok")) as response:
            assert response.status == 200

    match = _TRACEPARENT_RE.match(server.received["traceparent"])
    assert match, f"malformed traceparent: {server.received.get('traceparent')!r}"
    trace_id, span_id, flags = match.groups()

    ctx = parent.get_span_context()
    assert trace_id == format(ctx.trace_id, "032x")
    assert span_id != format(ctx.span_id, "016x")
    assert int(flags, 16) & 0x01


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("https://telemetry.googleapis.com", True),
        ("https://telemetry.googleapis.com:443", True),
        ("https://otlp.eu01.nr-data.net:4317", False),
        ("https://evil-googleapis.com", False),
    ],
)
def test_is_google_endpoint(endpoint: str, expected: bool):
    assert tracing.is_google_endpoint(endpoint) is expected


def test_parse_headers():
    assert tracing.parse_headers(None) == {}
    assert tracing.parse_headers(" api-key=abc , x=1,") == {"api-key": "abc", "x": "1"}
    with pytest.raises(ValueError):
        tracing.parse_headers("no-equals-sign")


def test_google_exporter_skipped_without_credentials(monkeypatch: pytest.MonkeyPatch):
    from google.auth.exceptions import DefaultCredentialsError

    def no_credentials(project_id: str | None):
        raise DefaultCredentialsError("no ADC")

    monkeypatch.setattr(tracing, "_google_channel_credentials", no_credentials)
    settings = TraceSettings(
        "tracing-test", otlp_endpoint="https://telemetry.googleapis.com"
    )
    assert tracing.build_exporter(settings) is None
