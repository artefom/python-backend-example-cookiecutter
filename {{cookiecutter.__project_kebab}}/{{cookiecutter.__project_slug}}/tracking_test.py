"""
Context based tracking middleware tests
"""
import asyncio
import logging
from unittest.mock import ANY

import pytest
from starlette.requests import Request
from starlette.responses import Response

from .slog import logging_context
from .tracking import RequestView, ResponseView, TrackingMiddleware

logger = logging.getLogger(__name__)


@pytest.fixture()
def f_request() -> Request:
    return Request(
        scope={
            "method": "GET",
            "type": "http",
            "http_version": "1.1",
            "headers": [
                (b"x-request-id", b"abc"),
                (b"user-agent", b"agent"),
                (b"Content-Length", b"10"),
            ],
            "client": ("10.1.1.10", "10"),
            "path": "/v1/path",
            "query_string": "",
        },
    )


@pytest.fixture()
def f_response() -> Response:
    return Response(headers={"Content-Length": "10"})


def test_request_view(f_request: Request):  # pylint: disable=W0621
    view = RequestView(f_request)
    assert view.client_addr == "10.1.1.10:10"
    assert view.url_path == "/v1/path"
    assert view.method == "GET"
    assert view.http_version == "HTTP/1.1"
    assert view.request_id == "abc"
    assert view.content_length == 10
    assert view.user_agent == "agent"


def test_response_view(f_response: Response):  # pylint: disable=W0621
    view = ResponseView(f_response)
    assert view.content_length == 10


@pytest.mark.asyncio
async def test_tracking_middleware(
    f_request: Request,  # pylint: disable=W0621
    f_response: Response,  # pylint: disable=W0621
    structured_logs_capture,
):
    async def api_call(request: Request):  # pylint: disable=W0613
        with logging_context(b=20):
            logger.info("slow api call")
            await asyncio.sleep(0.2)
        return f_response

    tracking = TrackingMiddleware(None)  # type: ignore
    await tracking.dispatch(f_request, api_call)

    assert structured_logs_capture.parse() == [
        {
            "severity": "INFO",
            "time": ANY,
            "message": "slow api call",
            "logging.googleapis.com/labels": {
                "logger": "{{cookiecutter.__project_slug}}.tracking_test",
                "request_id": "abc",
                "b": 20,
            },
        },
        {
            "severity": "INFO",
            "message": "GET /v1/path HTTP/1.1",
            "time": ANY,
            "httpRequest": {
                "protocol": "HTTP/1.1",
                "remoteIp": "10.1.1.10:10",
                "requestMethod": "GET",
                "requestSize": 10,
                "requestUrl": "/v1/path",
                "responseSize": 10,
                "status": 200,
                "userAgent": "agent",
                "latency": ANY,
            },
            "logging.googleapis.com/labels": {
                "logger": "{{cookiecutter.__project_slug}}.tracking",
                "request_id": "abc",
            },
        },
    ]

    # latency in string format as "0.123s"
    latency = float(structured_logs_capture.parse()[1]["httpRequest"]["latency"][:-1])
    assert 0.19 <= latency <= 0.21
