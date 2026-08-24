"""
Context based tracking middleware tests
"""

import re

import pytest
from httpx import AsyncClient
from starlette.requests import Request

from {{cookiecutter.__project_slug}}.testing_utils import JsonLogs

from .tracking import RequestView

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def test_request_view():
    """RequestView is a small parsing helper, covered directly with a raw scope."""
    view = RequestView(
        Request(
            scope={
                "type": "http",
                "method": "GET",
                "http_version": "1.1",
                "headers": [
                    (b"x-request-id", b"abc"),
                    (b"user-agent", b"agent"),
                    (b"content-length", b"10"),
                ],
                "client": ("10.1.1.10", "10"),
                "path": "/v1/path",
                "query_string": "",
            }
        )
    )
    assert view.client_addr == "10.1.1.10:10"
    assert view.url_path == "/v1/path"
    assert view.method == "GET"
    assert view.http_version == "HTTP/1.1"
    assert view.request_id == "abc"
    assert view.content_length == 10
    assert view.user_agent == "agent"


@pytest.mark.asyncio
async def test_request_id_echoed_and_logging_context(
    client: AsyncClient,
    structured_logs_capture: JsonLogs,
):
    response = await client.get(
        "/ping",
        params={"value": "hello"},
        headers={"X-Request-ID": "abc"},
    )

    assert response.status_code == 200
    # The request id is echoed back on the response.
    assert response.headers["x-request-id"] == "abc"

    logs = structured_logs_capture.parse()
    # The handler log, the middleware access log and one from the httpx client.
    assert len(logs) == 3

    # The handler's own log inherits the request id from the logging context.
    handler_log = next(
        entry for entry in logs if entry["message"] == "Processing ping request."
    )
    assert handler_log["x_request_id"] == "abc"

    # The middleware emits a structured access log for the request.
    access_log = next(
        entry for entry in logs if entry["message"] == "GET /ping?value=hello HTTP/1.1"
    )
    assert access_log["x_request_id"] == "abc"
    assert access_log["httpRequest"]["requestMethod"] == "GET"
    assert access_log["httpRequest"]["requestUrl"] == "/ping?value=hello"
    assert access_log["httpRequest"]["status"] == 200
    # Latency is reported as a "0.123s" string.
    assert float(access_log["httpRequest"]["latency"][:-1]) >= 0


@pytest.mark.asyncio
async def test_request_id_generated_when_absent(client: AsyncClient):
    response = await client.get("/ping", params={"value": "hello"})

    request_id = response.headers["x-request-id"]
    assert _UUID4_RE.match(request_id), f"expected UUID4, got {request_id!r}"
