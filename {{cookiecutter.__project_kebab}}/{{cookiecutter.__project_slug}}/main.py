"""
Server entry-point with FastAPI app defined
"""

import asyncio
import logging
import logging.config
from dataclasses import dataclass
from typing import Any

import fastapi
import uvicorn
import uvloop
from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse
from starlette_exporter import handle_metrics
from starlette_exporter.middleware import PrometheusMiddleware

from {{cookiecutter.__project_slug}}.api import api_router
from {{cookiecutter.__project_slug}}.api.spec import register_default_exception_handler
from {{cookiecutter.__project_slug}}.tracking import TrackingMiddleware

logger = logging.getLogger(__name__)


def make_app(root_path: str) -> FastAPI:
    app = FastAPI(root_path=root_path)

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
    # Enable context based tracking
    app.add_middleware(TrackingMiddleware)

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

    app.include_router(api_router())

    register_default_exception_handler(app)

    # We need to specify custom OpenAPI to add app.root_path to servers
    def custom_openapi() -> Any:
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title="{{cookiecutter.project_name}}",
            version="0.1.0",
            description="{{cookiecutter.description}}",
            routes=app.routes,
        )
        openapi_schema["servers"] = [{"url": app.root_path}]
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi  # noqa

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
    logging.info("Serving on http://%s:%s", settings.host, settings.port)
    await api_server.serve()


def main(settings: AppSettings):
    uvloop.install()
    asyncio.run(_main_async(settings))
