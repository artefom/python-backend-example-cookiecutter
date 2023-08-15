"""
Server entry-point with FastAPI app defined
"""

import asyncio
import logging
import logging.config
import os
from typing import Any

import sentry_sdk
import uvicorn
import uvloop
from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse
from starlette_exporter import handle_metrics
from starlette_exporter.middleware import PrometheusMiddleware

from {{cookiecutter.__project_slug}}.api import api_router
from {{cookiecutter.__project_slug}}.tracking import TrackingMiddleware

logger = logging.getLogger(__name__)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)-8s| %(message)s",
            "datefmt": "%H:%M:%S",
        },
        "json": {
            "()": "{{cookiecutter.__project_slug}}.slog.GcpStructuredFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": os.environ.get("LOG_FORMATTER", "standard"),
            "level": "INFO",
        },
    },
    "loggers": {
        "uvicorn": {"level": "WARNING"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


def make_app():
    root_path = os.environ.get("API_ROOT_PATH", "")

    app = FastAPI(root_path=root_path)

    app.add_middleware(
        PrometheusMiddleware,
        filter_unhandled_paths=True,
        group_paths=True,
        app_name="{{cookiecutter.__project_kebab}}",
        buckets=[
            0.01,
            0.025,
            0.05,
            0.075,
            0.1,
            0.25,
            0.5,
            0.75,
            1.0,
            2.5,
            5.0,
            7.5,
            10.0,
        ],
        skip_paths=[
            f"{root_path}{path}"
            for path in ["/health", "/metrics", "/", "/docs", "/openapi.json"]
        ],
    )
    # Enable context based tracking
    app.add_middleware(TrackingMiddleware)

    app.add_route("/metrics", handle_metrics)

    # Health check endpoint
    @app.get("/health", tags=["health"])  # type: ignore
    async def health() -> str:
        """Checks health of application, including database and all systems"""
        return "OK"

    @app.get("/")
    async def index(request: Request) -> RedirectResponse:
        # the redirect must be absolute (start with /) because
        # it needs to handle both trailing slash and no trailing slash
        # /app -> /app/docs
        # /app/ -> /app/docs
        return RedirectResponse(f"{str(request.base_url).rstrip('/')}/docs")

    app.include_router(api_router())

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


async def _main_async(host: str = "0.0.0.0", port: int = 8000):
    app = make_app()
    config = uvicorn.Config(app, host, port, log_config=None, access_log=False)
    api_server = uvicorn.Server(config)
    logging.info("Serving on http://%s:%s", host, port)
    await api_server.serve()


def main():
    sentry_sdk.init(
        dsn=os.environ.get("SENTRY_DSN"),
        # Set traces_sample_rate to 1.0 to capture 100% of transactions for performance
        # monitoring. We recommend adjusting this value in production.
        traces_sample_rate=1.0,
    )

    # Configure logging
    logging.config.dictConfig(LOGGING_CONFIG)
    uvloop.install()
    asyncio.run(_main_async())


# Main entry-point of the application
# Feel free to add command-line interface, connection to database,
# initialize global variables, run background tasks, etc..
if __name__ == "__main__":
    main()
