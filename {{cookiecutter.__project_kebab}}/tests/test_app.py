"""
Example unit tests file
"""

import pytest
from fastapi import FastAPI, Response
from fastapi.routing import APIRouter
from httpx import AsyncClient

from {{cookiecutter.__project_slug}}.api.spec import ApiSection
from {{cookiecutter.__project_slug}}.testing_utils import JsonLogs


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
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_index(client: AsyncClient) -> None:
    response = await client.get("/docs")
    assert response.status_code == 200
