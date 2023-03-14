"""
Server entrypoint with FastAPI app defined
"""

import os
from typing import Any, Dict

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from starlette_exporter import handle_metrics
from starlette_exporter.middleware import PrometheusMiddleware

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    # Set traces_sample_rate to 1.0 to capture 100% of transactions for performance
    # monitoring. We recommend adjusting this value in production.
    traces_sample_rate=1.0,
)


ROOT_PATH = os.environ.get("API_ROOT_PATH", "/")

app = FastAPI(root_path=ROOT_PATH)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[
        "http://localhost:8080",
        "http://localhost:8000",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    PrometheusMiddleware,
    filter_unhandled_paths=True,
    group_paths=True,
    app_name="{{cookiecutter.__project_kebab}}",
    buckets=[0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0],
    skip_paths=[
        f"{ROOT_PATH}{path}"
        for path in ["/health", "/metrics", "/", "/docs", "/openapi.json"]
    ],
)


app.add_route("/metrics", handle_metrics)


# Health check endpoint
@app.get("/health", tags=["health"])  # type: ignore
async def health() -> str:
    """Checks health of application, uncluding database and all systems"""
    return "OK"


@app.get("/")  # type: ignore
async def index() -> Dict[str, str]:
    return {
        "message": (
            f"Hello World."
            f" Test environment variable is: {os.getenv('TEST_ENV_VAR')}"
        )
    }


# We need to specify custom openapi to add app.root_path to servers
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
