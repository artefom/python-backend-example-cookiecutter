"""
Tracking middleware
"""
import asyncio
import logging
from dataclasses import dataclass
from functools import cached_property

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
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
        return uviutils.get_path_with_query_string(self.request.scope)

    @property
    def method(self) -> str:
        return self.request["method"]

    @property
    def http_version(self) -> str:
        version = self.request["http_version"]
        return f"HTTP/{version}"

    @cached_property
    def request_id(self) -> str | None:
        return self.headers.get("x-request-id")

    @property
    def content_length(self) -> int | None:
        try:
            content_length = self.headers["Content-Length"]
            return int(content_length)
        except KeyError:
            return None

    @property
    def user_agent(self) -> str | None:
        return self.headers.get("user-agent")

    @cached_property
    def headers(self) -> dict:
        return dict(self.request.headers.items())


@dataclass
class ResponseView:
    response: Response

    @property
    def content_length(self) -> int | None:
        try:
            content_length = self.response.headers["Content-Length"]
            return int(content_length)
        except KeyError:
            return None


class TrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        request_view = RequestView(request)

        with logging_context(request_id=request_view.request_id):
            # measure request time
            start_time = asyncio.get_event_loop().time()
            response = await call_next(request)
            end_time = asyncio.get_event_loop().time()

            response_view = ResponseView(response)

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
                        "responseSize": response_view.content_length,
                        "latency": f"{round(end_time - start_time, 6)}s",
                        "status": response.status_code,
                    }
                },
            )

        return response
