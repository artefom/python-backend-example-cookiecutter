"""
common fixtures and classes for tests

# The link to the testing practices
# https://fastapi.tiangolo.com/advanced/async-tests/#example
"""

import logging
from collections.abc import AsyncGenerator, Generator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.routing import APIRouter
from pydantic import BaseModel

from {{cookiecutter.__project_slug}}.api.spec import ApiSection
from {{cookiecutter.__project_slug}}.main import make_app
from {{cookiecutter.__project_slug}}.slog import GcpStructuredFormatter
from {{cookiecutter.__project_slug}}.testing_utils import JsonLogs

logger = logging.getLogger(__name__)


class PingResponse(BaseModel):
    text: str


async def _ping(value: str) -> PingResponse:
    """
    A test-only endpoint used to exercise the middleware and logging.

    Real applications register their own routes; the demo ``/echo`` endpoint
    is intentionally not relied upon by the tests.
    """
    logger.info(
        "Processing ping request.",
        extra={"structuredLoggingContext": {"value": value}},
    )
    return PingResponse(text=value)


@pytest.fixture()
def structured_logs_capture() -> Generator[JsonLogs]:
    output = JsonLogs()

    root_logger = logging.getLogger()

    # Copy existing loggers and clear the array
    # (do not just re-assign so references to old handlers list remain valid)
    handlers = root_logger.handlers.copy()
    root_logger.handlers.clear()

    # Add stream logger that writes to our output
    handler = logging.StreamHandler(output)

    handler.formatter = GcpStructuredFormatter()

    root_logger.handlers.append(handler)

    try:
        yield output
    finally:
        # Return loggers back
        root_logger.handlers.clear()
        root_logger.handlers.extend(handlers)


@pytest_asyncio.fixture()
async def app() -> FastAPI:
    """FastAPI app fixture for tests that need to add custom routes"""
    application = make_app("")

    # Register a test-only endpoint so the tests don't depend on the demo
    # ``/echo`` endpoint, which is usually removed in real projects.
    router = APIRouter()
    ApiSection(router, "/ping", "test").register("GET", "", _ping)
    application.include_router(router)

    return application


# The 'raw' client of our application.
#
# During tests we skip the whole main() ... function
# and create the app directly.
#
# Usually we would connect to any databases, initialize 'ClientSession' to
# access external services, etc.. in the main function.
#
# Since the main will not be called, we need to mock these connections
# in this client explicitly
#
# Making the client could be a pretty expensive operation, so we specify here scope
# to be module.
@pytest_asyncio.fixture()
async def client(
    app: FastAPI,  # pylint: disable=redefined-outer-name
) -> AsyncGenerator[httpx.AsyncClient]:
    # Feel free to connect here to database, or create any global contest
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as aclient:
        yield aclient
