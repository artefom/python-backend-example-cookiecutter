"""
Tracking middleware
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from functools import cached_property

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uvicorn.protocols import utils as uviutils

from {{cookiecutter.__project_slug}}.slog import logging_context

logger = logging.getLogger(__name__)


@dataclass
class RequestView:
    request: Request

    @property
    def client_addr(self) -> str:
        client = self.request.scope.get("client")
        if not client:
            return ""
        return f"{client[0]}:{client[1]}"

    @property
    def url_path(self) -> str:
        return uviutils.get_path_with_query_string(self.request.scope)  # type: ignore

    @property
    def method(self) -> str:
        return self.request["method"]

    @property
    def http_version(self) -> str:
        version = self.request["http_version"]
        return f"HTTP/{version}"

    @cached_property
    def request_id(self) -> str:
        return self.request.headers.get("x-request-id") or str(uuid.uuid4())

    @property
    def content_length(self) -> int | None:
        try:
            return int(self.request.headers["content-length"])
        except KeyError:
            return None

    @property
    def user_agent(self) -> str | None:
        return self.request.headers.get("user-agent")


class TrackingMiddleware:
    """Pure-ASGI middleware that scopes logging context to the request,
    stamps ``X-Request-ID`` on the response and emits a structured access log.

    Implemented as raw ASGI (rather than ``BaseHTTPMiddleware``) to avoid the
    per-request anyio task-group / memory-stream overhead that
    ``BaseHTTPMiddleware`` adds to every request.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_view = RequestView(Request(scope, receive))
        request_id = request_view.request_id

        status_code = 0
        response_size: int | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_size
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                try:
                    response_size = int(headers["content-length"])
                except KeyError, ValueError:
                    response_size = None

            await send(message)

        with logging_context(x_request_id=request_id):
            start_time = asyncio.get_running_loop().time()
            await self.app(scope, receive, send_wrapper)
            end_time = asyncio.get_running_loop().time()

            logger.info(
                "%s %s %s",
                request_view.method,
                request_view.url_path,
                request_view.http_version,
                extra={
                    "httpRequest": {
                        "requestMethod": request_view.method,
                        "requestUrl": request_view.url_path,
                        "remoteIp": request_view.client_addr,
                        "protocol": request_view.http_version,
                        "userAgent": request_view.user_agent,
                        "requestSize": request_view.content_length,
                        "responseSize": response_size,
                        "latency": f"{round(end_time - start_time, 6)}s",
                        "status": status_code,
                    }
                },
            )
